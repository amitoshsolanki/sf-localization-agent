# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `sf_localization_agent/`.

```bash
# Start the PostgreSQL database (required before running the app)
docker compose up -d db

# Stop DB (keep data) / Stop and wipe all data
docker compose down
docker compose down -v

# Inspect the database directly
docker exec sf_localization_agent-db-1 psql -U user -d sf_localization -c "SELECT * FROM glossary_terms;"

# Run the agent
python -m app --input <path/to/file.stf>
python -m app --input <path/to/file.stf> --target-language ar --output out.stf
# Output defaults to <input>.<lang>.stf if --output is omitted

# Run all tests (no DB or LLM needed)
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_parser.py -v

# Run a single test by name
python -m pytest tests/test_parser.py::test_parse_segments -v
```

The test fixture used across all unit tests is `tests/fixtures/sample.stf` (4-segment file with merge fields). `tests/fixtures/sample.labels` is used by the extractor tests.

## Architecture

This is a **LangGraph agent** that translates Salesforce `.stf` (Translation Workbench) bilingual files. The graph runs as a single async invocation from `app/__main__.py`.

**Graph flow:**
```
parser → translator → auditor → validator ──► extractor → END
                          ▲          │ (failures + loop_count < 3)
                          └──────────┘ self-healing retry loop
```

- **`parser_node`** — Reads the tab-delimited `.stf` file, detects sections and column headers, extracts all segments (both TRANSLATED and OUTDATED/UNTRANSLATED), and proactively fetches matching approved glossary terms from PostgreSQL (Proactive RAG). Sets `target_language` from file metadata if not supplied via CLI.
- **`translator_node`** — Calls the LLM in concurrent batches. On retry, re-translates only `failed_segment_ids` with a penalty prompt listing exact violations. Merges new results with preserved good translations.
- **`auditor_node`** — Pure Python, zero LLM tokens. Checks every glossary term: if `source_term` appears in a segment's source text, `approved_translation` must appear in the translated text (case-insensitive substring match).
- **`validator_node`** — Pure Python, zero LLM tokens. Checks for `missing_translation`, `merge_field_altered` (regex on `{!Var.Name}` tokens), and `char_limit_exceeded`. Aggregates `failed_segment_ids` from both auditor and its own issues. Reconstructs the output `.stf` only when there are zero failures.
- **`extractor_node`** — Runs only on success. Calls the LLM to identify short reusable UI terms and inserts them into `glossary_terms` with `approved=False` for human review.

**`AgentState`** (`app/state.py`) is a `TypedDict` passed through the entire graph. Each node receives the full state and returns a partial dict with only the fields it modifies.

The retry cap is `MAX_RETRIES = 3` in `app/graph.py`. When the cap is hit, the validator routes to `__end__` (not `extractor`) — so `output_stf` will be `None` and no glossary extraction runs.

## LLM Configuration

The `app/llm.py` factory supports four providers, selected via `.env`:

| Provider | Key env vars |
|---|---|
| `openai` (current — DeepSeek) | `LLM_PROVIDER=openai`, `LLM_MODEL=deepseek-chat`, `OPENAI_API_BASE=https://api.deepseek.com`, `OPENAI_API_KEY=...` |
| `openai` (native OpenAI) | `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o`, `OPENAI_API_KEY=...` (no `OPENAI_API_BASE`) |
| `gemini` | `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-2.0-flash`, `GOOGLE_API_KEY=...` |
| `anthropic` | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-6`, `ANTHROPIC_API_KEY=...` |
| `ollama` | `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3` |

Per-node overrides are supported: `TRANSLATOR_LLM_PROVIDER`, `TRANSLATOR_LLM_MODEL`, `EXTRACTOR_LLM_PROVIDER`, etc.

Both `translator_node` and `extractor_node` use `.with_structured_output(..., method="json_mode")` — this sends `response_format: json_object` instead of `json_schema`, required for DeepSeek and other OpenAI-compatible APIs that don't support the schema variant.

## Database

PostgreSQL runs on port **5433** (not 5432 — avoids conflict with a local install). Tables are created automatically by `create_tables()` on startup.

- **`glossary_terms`** — Curated approved translations. Only rows with `approved=True` are fetched by the parser and enforced by the auditor. Auto-extracted terms land here with `approved=False`.
- **`translation_memory`** — Schema exists but no node writes to it.
- **`checkpoints`** / **`checkpoint_blobs`** / **`checkpoint_writes`** — LangGraph persistence tables for graph state replay.

Glossary enforcement only applies to **approved** terms. To promote an auto-extracted term: `UPDATE glossary_terms SET approved=true WHERE id=<n>;`

## .stf File Format

Tab-delimited bilingual file exported by Salesforce Translation Workbench. Structure:

```
# Comment / metadata lines
Language code: ar
Type: Bilingual

------------------TRANSLATED-------------------

# KEY	LABEL	TRANSLATION	OUT OF DATE

ButtonOrLink.Account.SendContract	Send Contract	أرسل العقد	-

------------------OUTDATED AND UNTRANSLATED-----------------

# KEY	LABEL

CustomLabel.WelcomeMessage	Welcome, {!User.FirstName}!
CustomField.Account.Industry.FieldLabel	Industry
```

- Section separators are lines starting with 5+ dashes; they trigger column re-detection for the next header.
- Column headers are `#`-prefixed tab-separated lines. The parser matches them case-insensitively against known aliases (`key`/`fullname`/`name`, `label`/`source`/`value`, `translation`/`translated value`).
- The KEY format is `Type.Object.ApiName[.SubType]` — the first segment is the component type used to look up char limits.
- Merge fields (`{!Variable.Name}`) must be preserved verbatim in translations. The validator checks both that expected tokens are present and that no new ones were injected.
- Raw lines are preserved in `stf_lines` so the validator can reconstruct the output file in-place without re-serialising the entire document.

**Character limits by component type** (default 255 for unlisted types):

| Type | Limit | Type | Limit |
|---|---|---|---|
| CustomLabel | 1000 | QuickAction | 765 |
| CustomField | 255 | WebLink | 1000 |
| CustomTab | 40 | Flow | 255 |
| ValidationRule | 255 | Layout | 80 |

## Key Constraints

- `datetime` fields in `GlossaryTerm` and `TranslationMemory` must be naive UTC (no `tzinfo`) — the PostgreSQL columns are `TIMESTAMP WITHOUT TIME ZONE`. `_now()` in `models.py` strips timezone with `.replace(tzinfo=None)`.
- `TRANSLATE_BATCH_SIZE` (default 5) controls concurrency. All batches run via `asyncio.gather` — lowering this reduces rate-limit errors.
- LangGraph checkpoint persistence requires `psycopg` (psycopg3). If not installed, the app falls back to running without persistence and prints a warning — it still works.
- On Windows, `__main__.py` sets `WindowsSelectorEventLoopPolicy` for psycopg3 compatibility.
