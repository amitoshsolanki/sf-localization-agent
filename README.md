# Salesforce UI Localization Agent

An autonomous AI agent that translates Salesforce `.stf` (Translation Workbench) bilingual files using a configurable LLM. It enforces glossary consistency, validates structural integrity, and self-heals failed segments — producing a ready-to-import translation file.

## How it works

```
Parser → Translator → Auditor → Validator ──► Extractor → Done
                          ▲          │
                          └──────────┘  (self-healing retry, up to 3×)
```

- **Parser** — reads the `.stf` file, extracts all segments, fetches matching approved glossary terms from the database
- **Translator** — sends segments to the LLM in batches; on retry, only re-sends failed segments with a penalty prompt
- **Auditor** — deterministic check: ensures approved glossary terms are used verbatim
- **Validator** — deterministic check: ensures merge fields (`{!Var.Name}`) are preserved and character limits are respected; reconstructs the output file
- **Extractor** — on success, asks the LLM to identify new glossary candidates (saved as unapproved for human review)

## Prerequisites

- Python 3.12+
- Docker (for PostgreSQL)
- An API key for your chosen LLM provider

## Setup

**1. Clone and install dependencies**
```bash
git clone https://github.com/amitoshsolanki/sf-localization-agent.git
cd sf-localization-agent
pip install -r requirements.txt
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env with your API key and preferred LLM provider
```

**3. Start the database**
```bash
docker compose up -d db
```

## Usage

```bash
# Translate a .stf file (language auto-detected from file metadata)
python -m app --input path/to/export.stf

# Specify language and output path explicitly
python -m app --input path/to/export.stf --target-language ar --output path/to/out.stf
```

Output defaults to `<input>.<lang>.stf` if `--output` is omitted.

## LLM Configuration

Set `LLM_PROVIDER` and `LLM_MODEL` in `.env`:

| Provider | `LLM_PROVIDER` | Additional vars |
|---|---|---|
| DeepSeek (default) | `openai` | `LLM_MODEL=deepseek-chat`, `OPENAI_API_BASE=https://api.deepseek.com`, `OPENAI_API_KEY=...` |
| OpenAI | `openai` | `LLM_MODEL=gpt-4o`, `OPENAI_API_KEY=...` |
| Google Gemini | `gemini` | `LLM_MODEL=gemini-2.0-flash`, `GOOGLE_API_KEY=...` — `pip install langchain-google-genai` |
| Anthropic Claude | `anthropic` | `LLM_MODEL=claude-sonnet-4-6`, `ANTHROPIC_API_KEY=...` — `pip install langchain-anthropic` |
| Ollama (local) | `ollama` | `LLM_MODEL=llama3` — `pip install langchain-ollama` |

Per-node overrides are supported: e.g. `TRANSLATOR_LLM_PROVIDER=anthropic`.

## Glossary

Approved glossary terms are stored in the `glossary_terms` database table. The agent enforces them automatically during translation and flags any violations for retry.

Auto-extracted terms land in the same table with `approved=False`. To approve one:
```sql
UPDATE glossary_terms SET approved=true WHERE id=<n>;
```

## Running tests

```bash
python -m pytest tests/ -v
```

No database or LLM API key required for tests.

## Docker

```bash
docker compose up -d db       # start database
docker compose down           # stop (keep data)
docker compose down -v        # stop and wipe all data
```
