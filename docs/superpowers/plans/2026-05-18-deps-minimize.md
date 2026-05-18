# Dependency Minimization (Goal A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minimize Python dependencies so the backend can start locally on Windows and the new frontend can run, without optional/unused packages.

**Architecture:** Reduce `pyproject.toml` dependencies to the minimal set required by `src/` imports for the main API server path. Keep optional stacks (alembic/pandas/opencv/etc.) out.

**Tech Stack:** Python 3.12 + uv; FastAPI.

---

## File Structure (Create/Modify Map)

- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/.worktrees/feat-frontend-chat/pyproject.toml`
  - Remove unused deps
  - Add missing required deps (`requests`)
  - Ensure platform-problematic deps stay excluded on Windows

---

### Task 1: Update pyproject dependencies

**Files:**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/.worktrees/feat-frontend-chat/pyproject.toml`

- [ ] **Step 1: Replace dependencies list with minimal set**

Keep (required by current backend code path):
- `fastapi`
- `uvicorn`
- `pydantic`
- `coze-coding-utils`
- `cozeloop`
- `langchain`
- `langchain-openai`
- `langgraph`
- `langgraph-checkpoint`
- `openpyxl`
- `python-pptx`
- `chardet`
- `requests`

Remove (unused for Goal A):
- `opencv-python`, `pandas`, `pypdf`, `docx2python`, `python-dotenv`, `alembic`, `SQLAlchemy`
- `psycopg2-binary`, `psycopg[binary]`, `psycopg-pool`, `langgraph-checkpoint-postgres`
- `langgraph-prebuilt`, `langgraph-sdk`, `langsmith`
- `Jinja2`, `boto3`, `coze-workload-identity`, `coze-coding-dev-sdk`
- `pycairo`, `dbus-python`, `PyGObject`

Concrete `dependencies = [...]` block to paste:

```toml
dependencies = [
    "langchain==1.0.3",
    "langchain-openai==1.0.1",
    "langgraph==1.0.2",
    "langgraph-checkpoint==3.0.0",
    "fastapi>=0.121,<1",
    "uvicorn>=0.38,<1",
    "pydantic>=2.12,<3",
    "coze-coding-utils>=0.2.6,<1",
    "cozeloop>=0.1.25,<1",
    "openpyxl>=3.1,<4",
    "python-pptx>=1.0,<2",
    "chardet>=5.2,<6",
    "requests>=2.31,<3",
]
```

- [ ] **Step 2: Run dependency sync**

Run:

```bash
uv sync
```

Expected:
- Exit code 0
- No attempt to build `PyGObject` on Windows

- [ ] **Step 3: Verify backend import smoke**

Run:

```bash
python -c "import src.main; print('import-ok')"
```

Expected:
- Prints `import-ok`

---

### Task 2: Runtime smoke (backend start)

**Files:**
- No code changes

- [ ] **Step 1: Start server**

Run:

```bash
python src/main.py -m http -p 5000
```

Expected:
- Server starts without `ModuleNotFoundError`

---

## Plan Self-Review

- No placeholders.
- Steps include exact file paths, exact dependency block, and exact verification commands.

