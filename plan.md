# Salesforce UI Localization Agent — Developer Reference

## Project Overview

An autonomous LangGraph agent that translates Salesforce `.stf` (Translation Workbench) files into a target language using a configurable LLM backend (currently DeepSeek via OpenAI-compatible API). It implements a **Proactive RAG** architecture: the Parser proactively fetches only the relevant glossary terms from PostgreSQL, the Translator processes segments in batches via the LLM, and verification is handled entirely by **zero-token deterministic Python** (Auditor for glossary compliance, Validator for structural integrity). If any segment fails, a **Self-Healing Loop** isolates the specific failures and sends them back to the LLM with a targeted penalty prompt. Only 100% enterprise-compliant data is reassembled into the final `.stf` file.

---

## Repository Layout

```
sf_localization_agent/
├── app/
│   ├── __main__.py          # CLI entry point; wires graph + checkpointer; writes output .stf
│   ├── graph.py             # LangGraph DAG definition + conditional routing logic
│   ├── state.py             # AgentState TypedDict + all domain TypedDicts
│   ├── db/
│   │   ├── models.py        # SQLModel ORM: GlossaryTerm + TranslationMemory tables
│   │   └── session.py       # Async SQLAlchemy engine, session factory, create_tables()
│   ├── nodes/
│   │   ├── parser.py        # .stf parser + proactive glossary fetch (RAG)
│   │   ├── translator.py    # Gemini LLM call — batched (50–100), retry isolation, penalty prompts
│   │   ├── auditor.py       # Zero-token glossary compliance via exact string matching
│   │   └── validator.py     # Zero-token structural integrity: merge fields (regex) + char limits
│   └── utils/
│       └── prompts.py       # TRANSLATE_SYSTEM constant + build_translate_prompt() builder
├── tests/
│   ├── test_parser.py       # 7 unit tests: .stf parsing, column detection, merge fields, char limits
│   ├── test_auditor.py      # 5 unit tests: glossary compliance, case insensitivity, edge cases
│   ├── test_validator.py    # 7 unit tests: structural checks, .stf reconstruction, failure aggregation
│   └── fixtures/
│       └── sample.stf       # 4-segment Salesforce .stf file with merge fields (test input)
├── Dockerfile               # python:3.12-slim; installs requirements; CMD: python -m app
├── docker-compose.yml       # Two services: db (postgres:16-alpine) + app; healthcheck dependency
├── .dockerignore             # Excludes .env, __pycache__, .pytest_cache
├── .env.example             # Template for required environment variables
├── pytest.ini               # asyncio_mode=auto; asyncio_default_fixture_loop_scope=function
└── requirements.txt         # Pinned dependencies (langgraph, langchain-google-genai, sqlmodel, etc.)
```

---

## How It Works — Data Flow

```
Input .stf file
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PARSER NODE (Python)                                                │
│  1. Reads tab-delimited .stf file, detects sections + column headers│
│  2. Extracts ALL segments (translated + untranslated, both sections)│
│  3. Determines char limits from component Type (parsed from KEY)    │
│  4. PROACTIVE RAG: queries PostgreSQL for only the glossary terms   │
│     whose source_term appears in the extracted source texts          │
│  5. Stores glossary_context in state for downstream nodes           │
└────────────────────────┬────────────────────────────────────────────┘
                         │  segments, stf_lines, translation_col, glossary_context
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TRANSLATOR NODE (LLM — currently DeepSeek via OpenAI API)          │
│  • Batches segments (configurable via env, default 5)              │
│  • Each batch gets: glossary rules + length constraints + segments  │
│  • On retry: only re-translates failed segments with PENALTY PROMPT │
│  • Batches run concurrently via asyncio.gather                      │
│  • Merges new translations with existing good translations          │
└────────────────────────┬────────────────────────────────────────────┘
                         │  translated_segments, loop_count++
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ AUDITOR NODE (Pure Python — zero LLM tokens)                        │
│  • Reads glossary from state (no DB query)                          │
│  • For each glossary term whose source appears in a segment:        │
│    checks that approved_translation appears in translated text      │
│  • Case-insensitive exact substring matching                        │
│  • Produces glossary_violations list                                │
└────────────────────────┬────────────────────────────────────────────┘
                         │  glossary_violations
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ VALIDATOR NODE (Pure Python — zero LLM tokens)                      │
│  • missing_translation: no output for a segment                     │
│  • merge_field_altered: expected {!Var} missing OR unexpected       │
│    {!Var} injected (detected via regex)                              │
│  • char_limit_exceeded: len(translation) > segment.char_limit       │
│  • ALL issue types are BLOCKING (trigger retry)                     │
│  • Aggregates failed_segment_ids from glossary_violations +         │
│    validation_issues                                                 │
│  • If zero failures: reconstructs output .stf file                  │
└────────────────────────┬────────────────────────────────────────────┘
                         │  validation_issues, failed_segment_ids, output_stf
                         │
                         ├─── failures AND loop_count < 3 ──► SELF-HEALING LOOP
                         │                                     (back to Translator)
                         │    • Only failed segments re-sent
                         │    • Penalty prompt lists exact errors
                         │    • Good translations preserved
                         │
                         └─── no failures OR loop_count == 3 ──► END
                                                                  │
                                                           Output .stf file
```

---

## AgentState Reference

Defined in `app/state.py`. All nodes receive the full state and return a partial dict.

| Field | Type | Set by | Description |
|---|---|---|---|
| `input_file_path` | `str` | Caller | Path to the source .stf file |
| `target_language` | `str` | Caller | ISO 639-1 code, e.g. `"fr"`, `"de"`, `"ja"` |
| `segments` | `list[TranslationSegment]` | Parser | All segments from .stf (both sections) |
| `stf_lines` | `list[str]` | Parser | All raw lines preserved for reconstruction |
| `translation_col` | `int` | Parser | Column index for the Translation field |
| `glossary_context` | `str` | Parser | Proactively fetched glossary as JSON string |
| `translated_segments` | `list[TranslatedSegment]` | Translator | LLM output; accumulated across retries |
| `glossary_violations` | `list[GlossaryViolation]` | Auditor | Terms the LLM mistranslated |
| `failed_segment_ids` | `list[str]` | Validator | Combined failures from auditor + validator |
| `loop_count` | `int` | Translator | Incremented each attempt; caps at `MAX_RETRIES=3` |
| `validation_issues` | `list[ValidationIssue]` | Validator | All structural issues found |
| `output_stf` | `Optional[str]` | Validator | Final reconstructed .stf; `None` if any failures |
| `errors` | `list[str]` | Parser | Hard errors (file not found, no header, etc.) |

### Domain TypedDicts

**`TranslationSegment`** — one extractable text unit:
- `id`: derived from full KEY (unique per file)
- `source_text`: original text from LABEL column
- `component_type`: first segment of KEY (e.g. `"CustomField"`, `"ButtonOrLink"`)
- `component_key`: full KEY (e.g. `"CustomField.Account.Industry.FieldLabel"`)
- `merge_fields`: list of `{!Var.Name}` tokens found in source_text
- `char_limit`: max characters allowed (derived from component_type)
- `line_index`: index into `stf_lines` for reconstruction

**`TranslatedSegment`** — LLM response:
- `id`: matches the `TranslationSegment.id`
- `translated_text`: the translated string

**`GlossaryViolation`** — one failed term check:
- `segment_id`, `source_term`, `approved_translation`, `found_in_translation`

**`ValidationIssue`** — one constraint failure:
- `segment_id`, `issue_type`, `details`

---

## Node Reference

### `parser_node` — `app/nodes/parser.py`

Reads the .stf file, extracts segments, and proactively fetches relevant glossary.

- **Inputs used:** `input_file_path`, `target_language`
- **Outputs written:** `segments`, `stf_lines`, `translation_col`, `glossary_context`, `errors`
- **Section detection:** identifies TRANSLATED and UNTRANSLATED sections via dash separators; parses `#`-prefixed column headers per section
- **Column detection:** auto-detects KEY, LABEL, TRANSLATION columns from `#`-prefixed headers (case-insensitive)
- **Type extraction:** component type parsed from first segment of KEY (e.g. `CustomField.Obj.Field` → `CustomField`)
- **All rows included:** both translated and untranslated segments are extracted for (re-)translation
- **Character limits** (`CHAR_LIMITS` dict): CustomLabel=1000, CustomField=255, CustomTab=40, etc. Default=255
- **Proactive RAG:** queries `glossary_terms` table for `target_language`, filters to only terms whose `source_term` appears in any extracted source text
- **Merge field detection:** `MERGE_FIELD_RE = re.compile(r"\{![^}]+\}")`

### `translator_node` — `app/nodes/translator.py`

Calls the configured LLM in batches to translate segments.

- **Inputs used:** `segments`, `glossary_context`, `failed_segment_ids`, `glossary_violations`, `validation_issues`
- **Outputs written:** `translated_segments`, `loop_count`
- **Batch size:** env `TRANSLATE_BATCH_SIZE` (default 5), batches run concurrently via `asyncio.gather`
- **Retry isolation:** on retry, only re-translates segments listed in `failed_segment_ids`; merges results with existing good translations
- **Penalty prompt:** on retry, includes both glossary violation feedback and structural failure feedback, targeted to the specific failed segments
- **Structured output:** `.with_structured_output(_TranslationResponse, method="json_mode")` — uses `json_object` response format (compatible with DeepSeek and other OpenAI-compatible APIs that don't support `json_schema`)

### `auditor_node` — `app/nodes/auditor.py`

Zero-token deterministic glossary compliance check.

- **Inputs used:** `glossary_context`, `segments`, `translated_segments`
- **Outputs written:** `glossary_violations`
- **No DB dependency:** reads glossary from state (fetched by parser)
- **Algorithm:** for each glossary term, if `source_term` (case-insensitive) appears in a segment's source text, then `approved_translation` (case-insensitive) must appear in the translated text

### `validator_node` — `app/nodes/validator.py`

Zero-token deterministic structural integrity check + .stf reconstruction.

- **Inputs used:** `segments`, `translated_segments`, `glossary_violations`, `stf_lines`, `translation_col`
- **Outputs written:** `validation_issues`, `failed_segment_ids`, `output_stf`
- **All issue types are BLOCKING:** `missing_translation`, `merge_field_altered`, `char_limit_exceeded`
- **Merge field validation:** checks expected fields are present AND no unexpected fields injected (regex)
- **Failure aggregation:** combines segment IDs from `glossary_violations` + own `validation_issues` into `failed_segment_ids`
- **.stf reconstruction:** fills Translation column in preserved records; only produced when zero failures

### `extractor_node` — `app/nodes/extractor.py`

LLM-based glossary term extraction from successful translations.

- **Inputs used:** `output_stf`, `segments`, `translated_segments`, `target_language`
- **Outputs written:** `extracted_glossary_count`
- **Runs only on success:** skips entirely if `output_stf` is None
- **LLM call:** sends translated segments to the configured LLM, asks it to identify short reusable technical/UI terms; uses `method="json_mode"` for compatibility with OpenAI-compatible APIs
- **DB logic:** for each extracted term, checks if an approved entry exists for `source_term + target_language`; if not, inserts with `approved=False`
- **Never overwrites:** existing approved glossary terms are preserved

---

## LangGraph Graph — `app/graph.py`

```
parser ──► translator ──► auditor ──► validator ──┬──► extractor ──► END
                ▲                                  │
                ├──────────────────────────────────┘
                │  (SELF-HEALING LOOP: if failed_segment_ids AND loop_count < 3)
                │
                └── (max retries exceeded) ──► END
```

- Built with `StateGraph(AgentState)`
- Entry point: `parser`
- Fixed edges: `parser → translator`, `translator → auditor`, `auditor → validator`, `extractor → END`
- **Conditional edge on `validator`:** `_route_after_validation()` returns `"translator"` (retry), `"extractor"` (success), or `"__end__"` (max retries)
- Self-healing loop isolates failures: only failed segments are re-translated on retry

---

## Updating LLM

The provider and model are controlled via `.env`. The `app/llm.py` factory supports four providers and also allows per-node overrides (e.g. `TRANSLATOR_LLM_PROVIDER`, `EXTRACTOR_LLM_MODEL`).

**Current setup (`.env`):**
```
LLM_PROVIDER=openai
LLM_MODEL=deepseek-chat
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_API_KEY=<your-deepseek-key>
```

**Switching providers:**

| Provider | Required `.env` keys | Notes |
|---|---|---|
| DeepSeek (current) | `LLM_PROVIDER=openai`, `LLM_MODEL=deepseek-chat`, `OPENAI_API_BASE=https://api.deepseek.com`, `OPENAI_API_KEY=...` | OpenAI-compatible; uses `json_mode` for structured output |
| OpenAI | `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o`, `OPENAI_API_KEY=...` | Remove `OPENAI_API_BASE` to hit OpenAI directly |
| Google Gemini | `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-2.0-flash`, `GOOGLE_API_KEY=...` | `pip install langchain-google-genai` |
| Anthropic Claude | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-6`, `ANTHROPIC_API_KEY=...` | `pip install langchain-anthropic` |
| Ollama (local) | `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3` | `pip install langchain-ollama`; no API key needed |

**Note:** `json_mode` (used by translator and extractor) requires that the model supports `response_format: json_object`. All providers above support this. Do **not** switch back to the default `json_schema` method unless your provider explicitly supports it.

**To reduce rate limit errors:** lower `TRANSLATE_BATCH_SIZE` in `.env` (current default: 5).

---

## Character Limits by Component Type

| Salesforce Type | Char Limit |
|---|---|
| CustomLabel | 1000 |
| CustomField | 255 |
| CustomTab | 40 |
| ValidationRule | 255 |
| QuickAction | 765 |
| WebLink | 1000 |
| Flow | 255 |
| ReportType | 255 |
| CustomApplication | 255 |
| GlobalPicklistValue | 255 |
| RecordType | 255 |
| Layout | 80 |
| *(default)* | 255 |

---

## .stf File Format

Tab-delimited Bilingual file, exported by Salesforce Translation Workbench. Structure:

```
# Comment lines (start with #)
# Metadata comments...
Language code: ar
Type: Bilingual
Translation type: Metadata

------------------TRANSLATED-------------------

# KEY	LABEL	TRANSLATION	OUT OF DATE

ButtonOrLink.Account.SendContract	Send Contract	أرسل العقد	-
CustomLabel.SaveButton	Save	حفظ	*

------------------OUTDATED AND UNTRANSLATED-----------------

# KEY	LABEL

CustomLabel.WelcomeMessage	Welcome, {!User.FirstName}!
CustomField.Account.Industry.FieldLabel	Industry
```

- **Preamble:** comment lines (`#`), metadata (`Language code:`, `Type:`, etc.) — preserved in output
- **Section separators:** lines of dashes (`---...TRANSLATED---...`, `---...UNTRANSLATED---...`) — preserved
- **Column headers:** `#`-prefixed, tab-separated (`# KEY\tLABEL\tTRANSLATION\tOUT OF DATE`)
- **TRANSLATED section:** 4 columns — KEY, LABEL, TRANSLATION, OUT OF DATE
- **UNTRANSLATED section:** 2 columns — KEY, LABEL (translation column appended on output)
- **KEY format:** `Type.Object.ApiName[.SubType]` — component type extracted from first segment
- **Out of Date:** `*` = outdated translation, `-` = current
- **All rows translated:** parser creates segments for every data row (both sections)

---

## Database Layer

### `GlossaryTerm` table — `glossary_terms`

Curated approved translations. Populated manually before running the agent.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | auto-increment |
| `source_term` | str (indexed) | English term to match |
| `target_language` | str (indexed) | ISO 639-1 code |
| `approved_translation` | str | Exact string the LLM must use |
| `context` | str (nullable) | UI context hint for disambiguation |
| `created_at` / `updated_at` | datetime (UTC) | Audit trail |

### `TranslationMemory` table — `translation_memory`

History of completed translations. **Defined but not currently written by any node.**

---

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | Yes | `gemini` | LLM backend: `openai`, `gemini`, `anthropic`, `ollama` |
| `LLM_MODEL` | Yes | `gemini-2.0-flash` | Model name for the chosen provider |
| `OPENAI_API_KEY` | If `LLM_PROVIDER=openai` | — | API key; used for OpenAI or compatible APIs (DeepSeek, etc.) |
| `OPENAI_API_BASE` | No | — | Override base URL for OpenAI-compatible APIs (e.g. `https://api.deepseek.com`) |
| `GOOGLE_API_KEY` | If `LLM_PROVIDER=gemini` | — | Google AI API key |
| `ANTHROPIC_API_KEY` | If `LLM_PROVIDER=anthropic` | — | Anthropic API key |
| `DATABASE_URL` | No | `postgresql+asyncpg://user:password@localhost:5432/sf_localization` | Async SQLAlchemy connection string |
| `TRANSLATE_BATCH_SIZE` | No | `5` | Segments per LLM call |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `<NODE>_LLM_PROVIDER` | No | — | Per-node provider override, e.g. `TRANSLATOR_LLM_PROVIDER=anthropic` |
| `<NODE>_LLM_MODEL` | No | — | Per-node model override, e.g. `EXTRACTOR_LLM_MODEL=claude-haiku-4-5-20251001` |

---

## Running the Agent

### Local (Python directly)

```bash
# Translate a .stf file to French
python -m app --input path/to/export.stf --target-language fr

# With explicit output path
python -m app --input path/to/export.stf --target-language de --output path/to/out.stf

# Use the test fixture
python -m app --input tests/fixtures/sample.stf --target-language fr
```

Use `C:\Users\amito\AppData\Local\Programs\Python\Python313\python.exe` if `python` is not on PATH.

Output defaults to `<input>.<lang>.stf` if `--output` is omitted.

---

## Testing

```bash
C:\Users\amito\AppData\Local\Programs\Python\Python313\python.exe -m pytest tests/ -v
```

All 19 tests pass with no external services required.

| File | Tests | Coverage |
|---|---|---|
| `tests/test_parser.py` | 7 | .stf parsing, column detection, merge fields, char limits, missing file, skip translated rows |
| `tests/test_auditor.py` | 5 | Glossary compliance, violation detection, case insensitivity, irrelevant terms, empty glossary |
| `tests/test_validator.py` | 7 | Clean pass, missing translation, merge field altered/injected, char limit, glossary aggregation, .stf reconstruction |

---

## Docker Setup

Two containers managed by Docker Compose:

| Container | Image | Role |
|---|---|---|
| `db` | `postgres:16-alpine` | PostgreSQL 16; glossary, translation memory, checkpoint tables |
| `app` | Built from `Dockerfile` | Runs the localization agent |

```bash
docker compose up --build          # Start both
docker compose up -d db            # DB only (for local dev)
docker compose down                # Stop (keep data)
docker compose down -v             # Stop and wipe DB
```

---

## Environment Notes (Windows-specific)

- **Port conflict:** Docker `db` is mapped to port 5433 to avoid conflict with local PostgreSQL.
- **Event loop:** `__main__.py` sets `WindowsSelectorEventLoopPolicy` on Windows for psycopg3 compatibility.
