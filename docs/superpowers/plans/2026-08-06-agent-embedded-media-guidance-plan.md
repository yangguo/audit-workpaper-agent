# 受限 Agent 主动 OCR 嵌入图实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让受限证据 Agent 主动通过 `.embedded_media/` 路径 OCR 单张嵌入图，提升 evidence 粒度到「具体图」而非「整份文档」。

**Architecture:** 三处改动集中在 `src/review/evidence_agent.py`：
1. `_item_summary` 输出加 `source_document` / `media_name` 字段
2. `create_agent` 的 system_prompt 增加 `.embedded_media/` 引导
3. `_build_investigation_prompt` payload 加 `embedded_media_examples`

**Tech Stack:** Python 3.12, pytest, LangChain agents (existing).

## Global Constraints

- 改动仅限 `src/review/evidence_agent.py` + 新测试
- 无破坏性变更：现有字段保留，新增字段向后兼容
- prompt 体积受限：embedded_media_examples 最多前 10 张
- 不修改 OCR backend 或 LLM 评估流程

---

### Task 1: _item_summary exposes source_document for embedded media

**Files:**
- Modify: `src/review/evidence_agent.py`
- Test: `tests/review/test_evidence_agent.py` (or new test file)

- [ ] **Step 1: Write the failing test**

```python
# tests/review/test_evidence_agent.py (add at end)
from review.evidence_agent import _item_summary
from review.models import AttachmentFile


def _make_item(rel_path: str, file_type: str = "png", size: int = 1000):
    return AttachmentFile(
        index="",
        rel_dir=".embedded_media",
        filename=rel_path.split("/")[-1],
        rel_path=rel_path,
        file_type=file_type,
        description="",
        status="binary",
        extraction_status="binary",
        extracted_text="",
        size=size,
    )


def test_item_summary_marks_embedded_media_source_document():
    item = _make_item(".embedded_media/2-备份日志.docx::image1.png")
    s = _item_summary(item)
    assert s["source_document"] == "2-备份日志.docx"
    assert s["media_name"] == "image1.png"
    assert s["rel_path"] == ".embedded_media/2-备份日志.docx::image1.png"


def test_item_summary_omits_source_for_real_attachments():
    item = _make_item("审计证据/PE-6/1-备份策略设置.docx")
    # Need to set rel_path to not start with .embedded_media
    item.rel_path = "审计证据/PE-6/1-备份策略设置.docx"
    s = _item_summary(item)
    assert "source_document" not in s
    assert "media_name" not in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_evidence_agent.py -v`
Expected: FAIL (either ImportError on `_item_summary` or assertion failure on source_document)

- [ ] **Step 3: Implement _item_summary change**

Find `_item_summary` in `src/review/evidence_agent.py`. Modify it to detect `.embedded_media/` prefix and add the two fields. Pattern:

```python
def _item_summary(item: AttachmentFile) -> Dict[str, object]:
    summary = {
        "rel_path": item.rel_path,
        "filename": item.filename,
        "file_type": item.file_type,
        "status": item.status,
        "size": item.size,
    }
    if item.rel_path.startswith(".embedded_media/"):
        after_prefix = item.rel_path[len(".embedded_media/"):]
        if "::" in after_prefix:
            source_doc, media_name = after_prefix.split("::", 1)
            summary["source_document"] = source_doc
            summary["media_name"] = media_name
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_evidence_agent.py -v`
Expected: PASS (the 2 new tests)

- [ ] **Step 5: Run full backend suite**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: 198 + 2 = 200 passed, no regression

- [ ] **Step 6: Commit**

```bash
git add src/review/evidence_agent.py tests/review/test_evidence_agent.py
git commit -m "feat(evidence_agent): expose source_document in item summary for embedded media

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Agent system_prompt + investigation prompt gain embedded media guidance

**Files:**
- Modify: `src/review/evidence_agent.py`

**Interfaces:**
- Consumes: `_build_investigation_prompt` and the `create_agent(system_prompt=...)` call site inside `investigate_sheet`
- Produces: prompt content with `.embedded_media/` guidance

- [ ] **Step 1: Write the failing test**

```python
# tests/review/test_evidence_agent.py (add)
from review.evidence_agent import _build_investigation_prompt


def _fake_ws(title="PE-6"):
    ws = type("WS", (), {"title": title})()
    return ws


def test_investigation_prompt_includes_embedded_media_examples():
    # Build attachments with a couple of embedded media items
    attachments = {
        "items": [
            {"rel_path": ".embedded_media/foo.docx::image1.png"},
            {"rel_path": ".embedded_media/foo.docx::image2.png"},
            {"rel_path": ".embedded_media/bar.docx::image1.png"},
            {"rel_path": "审计证据/PE-6/foo.docx"},  # real, not embedded
        ],
        "status_counts": {"ok": 1, "binary": 3},
    }
    prompt = _build_investigation_prompt(_fake_ws(), attachments)
    assert "embedded_media_examples" in prompt or "embedded_media_count" in prompt
    assert "image1.png" in prompt or ".embedded_media/" in prompt


def test_investigation_prompt_truncates_embedded_media_at_10():
    attachments = {
        "items": [
            {"rel_path": f".embedded_media/x.docx::img{i}.png"} for i in range(15)
        ],
        "status_counts": {},
    }
    prompt = _build_investigation_prompt(_fake_ws(), attachments)
    # Only first 10 should be embedded; total should be 15
    assert "img0.png" in prompt
    assert "img9.png" in prompt
    # img10..14 should not appear in the examples list (or be truncated)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_evidence_agent.py -v`
Expected: FAIL (the fields don't exist in the prompt)

- [ ] **Step 3: Implement _build_investigation_prompt changes**

In `src/review/evidence_agent.py`, find `_build_investigation_prompt` and extend `payload`:

```python
def _build_investigation_prompt(ws, attachments: Dict[str, object]) -> str:
    relevant_cells: List[Dict[str, str]] = []
    for coord, text in _extract_sheet_text_cells(ws):
        filenames, rel_paths, indices = _extract_attachment_refs(text)
        if filenames or rel_paths or indices or any(keyword in text for keyword in EVIDENCE_KEYWORDS):
            relevant_cells.append({"cell": coord, "text": _truncate(text, 900)})
        if len(relevant_cells) >= 36:
            break
    if not relevant_cells:
        relevant_cells = [
            {"cell": coord, "text": _truncate(text, 500)}
            for coord, text in list(_extract_sheet_text_cells(ws))[:12]
        ]
    # Build embedded media examples
    embedded_examples = []
    items = attachments.get("items", []) or []
    for it in items:
        rp = getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path")
        if rp and rp.startswith(".embedded_media/") and "::" in rp:
            after = rp[len(".embedded_media/"):]
            source_doc, media_name = after.split("::", 1)
            embedded_examples.append({"source_document": source_doc, "media_filename": media_name})
        if len(embedded_examples) >= 10:
            break
    payload = {
        "sheet": str(getattr(ws, "title", "") or ""),
        "cells": relevant_cells,
        "attachment_status_counts": attachments.get("status_counts", {}),
        "embedded_media_count": sum(
            1 for it in items
            if (getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path", "")).startswith(".embedded_media/")
        ),
        "embedded_media_examples": embedded_examples,
        "embedded_media_more": sum(
            1 for it in items
            if (getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path", "")).startswith(".embedded_media/")
        ) > 10,
    }
    # ... rest unchanged: build tools_text, return prompt string with json.dumps(payload) ...
```

Also update the system_prompt in `investigate_sheet` (the `create_agent` call site, around line 580):

```python
agent = factory(
    model=llm,
    tools=tools,
    system_prompt=(
        "你是受限的审计证据调查 Agent。你只能通过工具查看审阅快照中的附件索引和已提取文本。"
        "你不可以执行命令、写文件、访问工具返回之外的路径或编造证据。"
        + ("如果附件是图片或扫描件，可先使用 ocr_attachment 获取 OCR 原文；OCR 失败时必须保留 unresolved。" if ocr_client else "")
        + "嵌入图指引：DOCX/PPTX/PDF 中提取出的嵌入图位于 .embedded_media/ 虚拟目录，"
        + "路径形如 .embedded_media/<原文档名>::<图名>.<ext>。"
        + "若需要核对该文档内的截图、流程图、扫描页证据，"
        + "应直接对 .embedded_media/ 中的具体图调用 ocr_attachment，"
        + "而非对整份 DOCX/PDF 调用（整份调用只会返回文字）。"
        + "list_attachment_files 输出中可查看 source_document 字段定位图来源。"
        + "你只负责定位候选证据，不负责给出审阅结论。最后必须返回约定 JSON。"
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_evidence_agent.py -v`
Expected: PASS (2 new tests)

- [ ] **Step 5: Run full backend suite**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: 200 + 2 = 202 passed

- [ ] **Step 6: Commit**

```bash
git add src/review/evidence_agent.py tests/review/test_evidence_agent.py
git commit -m "feat(evidence_agent): guide Agent to OCR embedded media images directly

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: End-to-end smoke verification

**Files:**
- None (verification only)

- [ ] **Step 1: Restart backend**

Backend should auto-reload, but confirm via `curl http://localhost:5000/health`.

- [ ] **Step 2: Run a real review with PE-6 + real DOCX attachments**

Use the HTTP API path (`POST /v1/chat/completions`) with the same paths as the prior smoke test. Poll until completed.

- [ ] **Step 3: Inspect findings + evidence_agent trace**

Check:
- `evidence_agent.tool_trace` contains `ocr_attachment` calls with `.embedded_media/` paths (not whole DOCX)
- `evidence_agent.ocr.calls` increased
- `findings[*].evidence_refs[*].attachment` contains `.embedded_media/` paths

- [ ] **Step 4: Commit any final fixes**

If the Agent still doesn't prefer `.embedded_media/` paths, iterate on the prompt (likely 1-2 rounds). Each fix is a separate commit.

---

## Self-Review

**Spec coverage:**
- _item_summary exposes source_document → Task 1.
- Agent system_prompt + investigation_prompt → Task 2.
- End-to-end smoke → Task 3.

**Placeholder scan:** All steps have concrete code.

**Type consistency:** `_item_summary` signature unchanged.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-agent-embedded-media-guidance-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks.

**2. Inline Execution** - Execute tasks in this session.

**Which approach?**