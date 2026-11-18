# Project: Dynamic Cognitive Orchestrator（推演局）

## Mission
A multi-agent cognitive deduction terminal. Users input any contentious topic or decision; the system decomposes conflict axes, casts heterogeneous virtual agents into physically context-isolated darkrooms, optionally stages a roundtable clash, and synthesizes an actionable truth report via the "Director".

## Modular Repository Layout
- `main.py` — FastAPI entrypoint (`uvicorn main:app`), static asset serving (`GET /`), and API routes
- `tuiyanju/` — Modular backend package (`config.py`, `models.py`, `prompts.py`, `orchestrator.py`, `demo.py`, `rate_limit.py`)
- `index.html` + `theme.css` + `export_utils.js` — Dark-gold strategic reading terminal & `full`/`share`/MD/TXT export engine
- `prompts/` — Prompt source-of-truth files (`system.md`, `runtime.md`, `casting.md`, `agent.md`, `roundtable.md`, `director.md`)
- `schemas/analysis.json` — Structured output JSON schema
- `evals/` — `cases.jsonl` (10 benchmark cases), `rubric.md` (100-point rubric), and `runner.py` (offline validator & live LLM judge CLI)
- `tests/` — Pytest suite (`test_api.py`, `test_orchestrator.py`, `test_naming_and_evals.py`) and Node.js suite (`test_export_utils.js`)
- `.env.example` — Environment configuration template (never commit `.env`)

## Architecture Rules (Non-Negotiable)
- NEVER hardcode domain prompts inside Python code — always read from `prompts/` files via `tuiyanju/prompts.py`
- NEVER overwrite `prompts/system.md` or `.env` unless explicitly instructed
- Backend uses async `httpx.AsyncClient` and SSE streaming (`text/event-stream`)
- Support all three execution modes (`multi_agent`, `single_stream`, `demo` + automatic demo fallback when no API key is configured)
- All user-facing UI and report text is Simplified Chinese

## API Contract
- `GET /` — Serves `index.html` directly (no `file://` CORS issues)
- `POST /api/analyze` — Accepts `topic`, `model`, `depth`, `audience`, `agent_count`, `issue_type`, `active_modules`, `focus_perspectives`, `context`, `extra_instructions`, `orchestration_mode`
- `GET /api/health` — Health check, supported orchestration modes, and API credential readiness
- `GET /api/models` — Available upstream models with curated fallback list
- `GET /api/modules` — Enhancement modules catalog

## Verification Commands
```bash
uvicorn main:app --host 127.0.0.1 --port 8000
pytest
node tests/test_export_utils.js
python evals/runner.py --mode validate
```
