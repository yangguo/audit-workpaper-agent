# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An AI-powered audit workpaper review agent (底稿审阅智能体). The backend is a LangChain/LangGraph agent with FastAPI HTTP server. The frontend is a Next.js chat UI. The agent reads Excel audit workpapers, checks evidence sufficiency, and verifies attachment references.

## Commands

### Backend (Python)

```bash
# Install dependencies (uses uv with aliyun mirror)
uv sync

# Run the full agent flow (one-shot, no HTTP)
bash scripts/local_run.sh -m flow

# Run a single graph node
bash scripts/local_run.sh -m node -n <node_name>

# Start HTTP server
bash scripts/http_run.sh -p 5000

# Or directly:
python src/main.py -m http -p 5000
```

### Frontend (Next.js)

```bash
cd frontend
cp .env.example .env.local   # Set NEXT_PUBLIC_BACKEND_URL if needed
npm install
npm run dev                   # → http://localhost:3000
npm run lint
npm run build
```

## Architecture

### Backend (`src/`)

- **`src/main.py`** — FastAPI server entry point. Contains `GraphService` which wraps the LangGraph agent/workflow. Key endpoints:
  - `POST /run` — synchronous agent execution
  - `POST /stream_run` — SSE streaming execution
  - `POST /cancel/{run_id}` — cancel a running task
  - `POST /node_run/{node_id}` — run a single graph node
  - `POST /v1/chat/completions` — OpenAI-compatible chat API (non-stream returns `task_id`; poll `GET /v1/chat/completions/result/{task_id}`; completed result carries `review_id` when the agent ran `review_workpaper`)
  - `POST /upload` — file upload (max 10 files, 100MB each)
  - `GET /findings/{review_id}` — structured review findings (written by `review_workpaper` to a side store)
  - `GET /health`, `GET /graph_parameter`

- **`src/agents/agent.py`** — Agent definition. Loads LLM config from `config/agent_llm_config.json`, creates a `ChatOpenAI` instance (pointing to Doubao model via Ark API at `COZE_INTEGRATION_MODEL_BASE_URL`), and builds a LangChain agent with two tools and a checkpointer. Uses a sliding window of 40 messages.

- **`src/tools/`** — Two LangChain tools registered on the agent:
  - `analyze_worksheet(file_path)` — Opens an Excel workbook, auto-detects "标准审计程序" (standard) and "执行程序" (execution) columns by scanning header rows, extracts audit program rows. Used to preview structure before a full review.
  - `review_workpaper(file_path, checkpoints_path?, attachments_preview_path?, sheets?)` — Async. Runs the full deterministic review pipeline (ported from `wpreview/analyze_excel.py`) via `src/review/`, writes structured `Finding`s to a JSON side store (`assets/results/<review_id>_findings.json`), and returns a summary JSON (counts by severity/status/risk_type, top issues, `review_id`). The agent narrates a Markdown report from the summary; the frontend reads structured findings via `GET /findings/{review_id}`.

- **`src/review/`** — Review engine ported from `analyze_excel.py` (async over `ChatOpenAI`, no `jsonschema`): `models` (Finding + schema), `excel_utils`, `validation` (schema validate/repair + excerpt verification), `llm` (retry/backoff/stats), `hallucination` (cross-validation + adversarial challenge), `checkpoints` (loader + checkpoint LLM review), `attachments` (preview loader + ref matching), `evidence_steps` (evidence↔step LLM check), `procedure_pairs` (rule checks + A-C LLM judgement), `findings_review` (LLM re-review of rule findings), `pipeline` (`run_review` orchestrator). Tests under `tests/review/`.

- **`src/storage/findings_store.py`** — Side store: `save_findings`/`load_findings` to `${COZE_WORKSPACE_PATH}/assets/results/<review_id>_findings.json`.

- **`src/storage/`**:
  - `database/` — PostgreSQL via SQLAlchemy, reads `PGDATABASE_URL` from env or `coze_workload_identity` client. Falls back gracefully if unavailable.
  - `memory/` — LangGraph checkpointer: `AsyncPostgresSaver` with automatic `MemorySaver` fallback when DB is unreachable. Creates schema in `memory` search_path.
  - `s3/` — S3-compatible storage via boto3 with presigned URL support, multipart upload, streaming upload.

- **`src/utils/file/`** — General file utilities: type inference, text extraction from PDF/DOCX/XLSX/PPT

### Frontend (`frontend/`)

- Next.js 15 App Router + React 19 + Tailwind CSS 4 + shadcn/ui (Radix primitives)
- **`app/page.tsx`** — Root page, wraps `Thread` component in `StreamProvider`
- **`app/api/upload/route.ts`** — Upload proxy that forwards to the backend `/upload`, with size/number validation
- **`components/thread/`** — Chat thread UI (AI messages, human messages, markdown rendering, file previews)
- **`providers/Stream.tsx`** — Streaming context provider for SSE

### Config

- **`config/agent_llm_config.json`** — LLM model (`doubao-seed-2-0-pro-260215`), temperature, system prompt (`sp`), tool list. The agent loads this at build time.
- **`.coze`** — Coze platform project config, defines dev/deploy build/run commands

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `COZE_WORKSPACE_PATH` | Workspace root (defaults to `/workspace/projects`) |
| `COZE_WORKLOAD_IDENTITY_API_KEY` | LLM API key |
| `COZE_INTEGRATION_MODEL_BASE_URL` | LLM base URL (Ark API) |
| `PGDATABASE_URL` | PostgreSQL connection string (optional) |
| `FRONTEND_ORIGINS` | CORS origins for frontend (default: `http://localhost:3000`) |
| `COZE_PROJECT_ENV` | Set to `DEV` for local development |

## File Upload Path Convention

Uploaded files land at `${COZE_WORKSPACE_PATH}/assets/uploads/<uuid>_<name>`. The API returns relative paths starting from `assets/`. Agent tools resolve relative paths against `COZE_WORKSPACE_PATH`.
