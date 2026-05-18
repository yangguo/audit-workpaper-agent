# Audit Workpaper Agent Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable, chat-style Next.js frontend (ported from doc-convert) with file upload to local backend storage and streaming chat via `/v1/chat/completions`.

**Architecture:** Keep frontend in `frontend/` (Next.js App Router). Keep backend in FastAPI (`src/main.py`). Frontend uploads files via Next API route (`/api/upload`) which proxies to backend `/upload`; chat runs browser→backend directly (requires CORS).

**Tech Stack:** Python 3.12 + FastAPI; Node.js + Next.js (App Router) + React + Tailwind.

---

## File Structure (Create/Modify Map)

**Backend**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/src/main.py`
  - Add CORS middleware driven by env
  - Add `POST /upload` endpoint (multipart) saving to `COZE_WORKSPACE_PATH/assets/uploads/`
- Create: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/src/api/upload.py`
  - Contain upload helpers + route function to keep `main.py` readable

**Frontend**
- Create: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/frontend/` (copy from `doc-convert/frontend/`)
- Modify (after copy):
  - `frontend/app/api/upload/route.ts` (ensure it proxies to this backend `/upload`)
  - `frontend/.env.example` (document `NEXT_PUBLIC_BACKEND_URL`)
  - Optional branding text in `frontend/app/layout.tsx`, `frontend/app/page.tsx`

**Docs**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/README.md` (how to run backend + frontend)

---

### Task 1: Backend upload endpoint (local filesystem)

**Files:**
- Create: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/src/api/upload.py`
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/src/main.py`

- [ ] **Step 1: Add `src/api/upload.py` with a safe save helper**

```python
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile


def _workspace_path() -> str:
    return os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")


def _uploads_dir() -> Path:
    return Path(_workspace_path()) / "assets" / "uploads"


def _safe_filename(original: str) -> str:
    name = Path(original).name
    name = name.replace("\\", "_").replace("/", "_")
    return name or "file"


def save_upload_to_assets(file: UploadFile) -> dict[str, Any]:
    uploads_dir = _uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(file.filename or "file")
    final_name = f"{uuid.uuid4().hex}_{safe_name}"
    abs_path = uploads_dir / final_name

    size = 0
    with abs_path.open("wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)

    rel_path = Path("assets") / "uploads" / final_name
    return {"original_name": safe_name, "path": str(rel_path).replace("\\", "/"), "size": size}
```

- [ ] **Step 2: Wire `POST /upload` in `src/main.py`**

```python
from fastapi import UploadFile, File as FastAPIFile

from src.api.upload import save_upload_to_assets
```

Add endpoint:

```python
@app.post("/upload")
async def upload(files: list[UploadFile] = FastAPIFile(...)):
    saved = []
    for f in files:
        saved.append(save_upload_to_assets(f))
    return {"files": saved}
```

- [ ] **Step 3: Manual verification of JSON contract (no server start yet)**
  - Confirm response schema matches the frontend expectation:
    - `{"files":[{"original_name": "...", "path": "assets/uploads/...", "size": 123}]}`

- [ ] **Step 4: Commit**

```bash
git add src/api/upload.py src/main.py
git commit -m "feat: add upload endpoint saving to assets/uploads"
```

---

### Task 2: Backend CORS middleware for browser chat

**Files:**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/src/main.py`

- [ ] **Step 1: Add env-driven origin list**

Decide one env key:
- `FRONTEND_ORIGINS` (comma-separated), default `http://localhost:3000`

- [ ] **Step 2: Add CORS middleware**

```python
import os
from fastapi.middleware.cors import CORSMiddleware

frontend_origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000")
allow_origins = [o.strip() for o in frontend_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
```

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: enable CORS for frontend origins"
```

---

### Task 3: Port frontend from doc-convert

**Files:**
- Create: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/frontend/**`

- [ ] **Step 1: Copy `doc-convert/frontend` to this repo as `frontend/`**
  - Source: `d:/User Data/yangfan15/Desktop/doc-convert/frontend`
  - Target: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/frontend`

- [ ] **Step 2: Update branding text (optional)**
  - `frontend/app/layout.tsx`
  - `frontend/app/page.tsx`

- [ ] **Step 3: Ensure upload proxy targets this backend**
  - Verify `frontend/app/api/upload/route.ts` is:

```ts
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000";
const res = await fetch(`${backendUrl}/upload`, { method: "POST", body: backendForm });
```

- [ ] **Step 4: Confirm `.env.example` exists and documents backend URL**

Example:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:5000
```

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add Next.js chat frontend"
```

---

### Task 4: Inject uploaded paths into the user message (frontend behavior)

**Files:**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/frontend/components/thread/index.tsx`
- Review: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/frontend/hooks/use-file-upload.tsx`

- [ ] **Step 1: Ensure upload response parsing supports `{ files: [{ path }] }`**

If the existing hook expects `saved_path` (doc-convert backend style), adjust to read:
- `data.files.map((f) => f.path)`

Example patch shape inside the hook:

```ts
const data = await res.json();
const paths: string[] = Array.isArray(data?.files) ? data.files.map((f: any) => String(f.path)) : [];
```

- [ ] **Step 2: Append a readable path list to user content**

```ts
const injected =
  uploadedPaths.length > 0
    ? `${content}\n\n已上传文件路径：\n${uploadedPaths.map((p) => `- ${p}`).join("\n")}`
    : content;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/use-file-upload.tsx frontend/components/thread/index.tsx
git commit -m "feat: inject uploaded file paths into chat message"
```

---

### Task 5: Documentation + local smoke run instructions

**Files:**
- Modify: `d:/User Data/yangfan15/Desktop/audit-workpaper-agent/README.md`

- [ ] **Step 1: Document required env**
  - Backend: `COZE_WORKSPACE_PATH` (optional), `FRONTEND_ORIGINS` (optional)
  - Frontend: `NEXT_PUBLIC_BACKEND_URL`

- [ ] **Step 2: Add “how to run” sections**
  - Backend run command (existing): `python src/main.py -m http -p 5000`
  - Frontend run command: `npm install` then `npm run dev` in `frontend/`
  - Note: do not auto-start servers; always ask for confirmation before running

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add frontend setup and run instructions"
```

---

## Plan Self-Review

- Spec coverage:
  - `/upload` local save + relative `assets/uploads/...` path: Task 1
  - CORS for browser calls to `/v1/chat/completions`: Task 2
  - Port frontend and proxy upload via Next: Task 3
  - Inject upload paths into chat: Task 4
  - Run docs: Task 5
- Placeholder scan: no TBD/TODO; each step has concrete file paths and code.
- Type consistency: upload response uses `{"files":[{"path": ...}]}` and frontend reads `data.files[].path`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-audit-workpaper-frontend.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks
2. Inline Execution - Execute tasks in this session using executing-plans, with checkpoints for review

Which approach?

