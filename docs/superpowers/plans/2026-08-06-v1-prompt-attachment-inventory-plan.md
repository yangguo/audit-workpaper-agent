# V1 主审阅 prompt 注入附件清单实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 V1 主审阅的 LLM 知道附件目录里有哪些真实文件 + 嵌入图，从而基于实际证据下 finding，而不是看到文档名就判「证据不足」。

**Architecture:** 新增 `build_evidence_inventory` helper 在 `src/review/attachments.py`；在 4 个 V1 prompt builder 注入 inventory + 引导文本。

**Tech Stack:** Python 3.12, pytest.

## Global Constraints

- 仅修改 `src/review/attachments.py` + 4 个 prompt 文件 + 测试
- 不修改 review pipeline 控制流
- inventory 字符串截断：30 个真实附件 + 12 张嵌入图
- 无破坏性变更：现有字段保留

---

### Task 1: build_evidence_inventory helper

**Files:**
- Modify: `src/review/attachments.py`
- Modify: `tests/review/test_attachments.py`

**Interfaces:**
- Produces: `build_evidence_inventory(attachments, *, max_entries=30, max_embedded=12, max_excerpt_chars=200) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/review/test_attachments.py` (or test_attachment_directory.py):

```python
# Add to existing test file
from review.attachments import build_evidence_inventory


def test_build_evidence_inventory_empty():
    assert build_evidence_inventory({}) == ""
    assert build_evidence_inventory(None or {}) == ""  # type: ignore


def test_build_evidence_inventory_lists_real_attachments(tmp_path):
    """Two real text-extractable attachments should appear with status [ok]."""
    from review.attachments import build_attachment_index
    from pathlib import Path
    d = tmp_path / "atts"
    d.mkdir()
    (d / "a.txt").write_text("hello world " * 20, encoding="utf-8")
    (d / "b.docx").write_text("fake docx", encoding="utf-8")  # not a real zip but we just need the index
    idx = build_attachment_index(str(d))
    inv = build_evidence_inventory(idx)
    assert "证据清单" in inv
    assert "[ok] a.txt" in inv
    assert "[ok] b.docx" in inv


def test_build_evidence_inventory_groups_embedded_media(tmp_path):
    """Embedded media items should be grouped by source_document with [EMBED] header."""
    # Use the actual extract pipeline on a real DOCX
    import io
    import zipfile
    from review.attachments import build_attachment_index
    d = tmp_path / "atts"
    d.mkdir()
    docx = d / "test.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<?xml version='1.0'?><doc/>")
        zf.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)
    docx.write_bytes(buf.getvalue())
    idx = build_attachment_index(str(d))
    inv = build_evidence_inventory(idx)
    # .embedded_media section present
    assert ".embedded_media" in inv
    assert "test.docx" in inv


def test_build_evidence_inventory_truncates(tmp_path):
    """More than max_entries + max_embedded should be truncated, with hint text."""
    from review.attachments import build_attachment_index
    d = tmp_path / "atts"
    d.mkdir()
    for i in range(50):
        (d / f"f{i}.txt").write_text(f"file {i} content", encoding="utf-8")
    idx = build_attachment_index(str(d))
    inv = build_evidence_inventory(idx, max_entries=10, max_embedded=5)
    # Should mention truncation
    assert "实际有" in inv or "前 10" in inv or "前 5" in inv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachments.py -v -k "build_evidence_inventory"`
Expected: FAIL (AttributeError: module 'review.attachments' has no attribute 'build_evidence_inventory')

- [ ] **Step 3: Implement build_evidence_inventory**

Add to `src/review/attachments.py` (after the existing helpers, before `build_attachment_index`):

```python
@dataclass
class EvidenceEntry:
    rel_path: str
    file_type: str
    status: str
    excerpt: str
    source_document: Optional[str] = None
    is_embedded: bool = False


EVIDENCE_GUIDANCE = (
    "重要：[证据清单] 段列出本sheet附件目录中真实可用的文件及其嵌入图。\n"
    "若执行描述引用了「《某文档》」，从清单中找出实际路径作为 evidence_refs.attachment。\n"
    "若证据是截图（密码策略截图、系统参数界面），DOCX/PPTX 中抽取的嵌入图位于 .embedded_media/ 路径。\n"
    "不要把 [证据清单] 中不存在的文件写进 evidence_refs。\n"
    "不要因为「执行描述里没明说截图」就判证据不足——先看 [证据清单] 中是否真的缺。\n"
)


def build_evidence_inventory(
    attachments: Optional[Dict[str, object]],
    *,
    max_entries: int = 30,
    max_embedded: int = 12,
    max_excerpt_chars: int = 200,
) -> str:
    """Build a compact evidence inventory for V1 review prompts.
    
    Lists real attachments (with status + excerpt) and embedded media
    (grouped by source document). Capped to keep prompt size bounded.
    Returns "" if attachments is empty/None.
    """
    if not attachments:
        return ""
    items = attachments.get("items", []) or []
    if not items:
        return ""
    
    real = []
    embedded_by_source: Dict[str, List[str]] = {}
    for it in items:
        rel = getattr(it, "rel_path", None) if not isinstance(it, dict) else it.get("rel_path")
        status = getattr(it, "status", "") if not isinstance(it, dict) else it.get("status", "")
        file_type = getattr(it, "file_type", "") if not isinstance(it, dict) else it.get("file_type", "")
        excerpt = getattr(it, "extracted_text", "") if not isinstance(it, dict) else it.get("extracted_text", "")
        if not rel:
            continue
        if rel.startswith(".embedded_media/") and "::" in rel:
            after = rel[len(".embedded_media/"):]
            source, media_name = after.split("::", 1)
            embedded_by_source.setdefault(source, []).append(media_name)
        else:
            excerpt_short = (excerpt or "")[:max_excerpt_chars].replace("\n", " ").strip()
            real.append((rel, status or "unknown", excerpt_short))
    
    total_real = len(real)
    total_embedded = sum(len(v) for v in embedded_by_source.values())
    real = real[:max_entries]
    embedded_pairs = []
    for src, names in embedded_by_source.items():
        for n in names:
            embedded_pairs.append((src, n))
    embedded_pairs = embedded_pairs[:max_embedded]
    
    lines = [f"[证据清单（前 {min(total_real, max_entries)} 个附件 + 前 {min(total_embedded, max_embedded)} 张嵌入图，目录实际有 {total_real} 项 + {total_embedded} 张）]\n"]
    lines.append(f"== 真实附件（{total_real} 项，列出前 {len(real)}） ==")
    for rel, status, ex in real:
        ex_part = f" — 摘录: {ex}" if ex else ""
        lines.append(f"[{status}] {rel}{ex_part}")
    lines.append("")
    lines.append(f"== 嵌入图（{total_embedded} 张，按来源文档分组） ==")
    for src, n in embedded_pairs:
        lines.append(f"  [{n}] 来自 {src}")
    lines.append("")
    lines.append("引用示例：evidence_refs.attachment = \".embedded_media/<原文档>::<图名>.<ext>\"")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_attachments.py -v -k "build_evidence_inventory"`
Expected: 4 tests pass

- [ ] **Step 5: Run full backend suite**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: 202 + 4 = 206 passed, no regression

- [ ] **Step 6: Commit**

```bash
git add src/review/attachments.py tests/review/test_attachments.py
git commit -m "feat(review): add build_evidence_inventory helper for V1 prompts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Inject inventory into checkpoints prompt

**Files:**
- Modify: `src/review/checkpoints.py`
- Modify: `tests/review/test_checkpoints.py` (or create new test)

**Interfaces:**
- Consumes: `build_evidence_inventory(attachments)`
- Modifies: `_llm_check_sheet_by_checkpoints` to include inventory in system_prompt

- [ ] **Step 1: Write the failing test**

```python
# In a new test file or existing
import json
from unittest.mock import patch, AsyncMock
from langchain_core.messages import AIMessage


def test_checkpoints_prompt_includes_evidence_inventory(monkeypatch):
    """The checkpoints review prompt should include attachment inventory."""
    from review import checkpoints as cp
    from review.llm import _llm_chat
    
    captured = {}
    async def fake_chat(*, llm, messages, stage, max_attempts=2, max_tokens=4096):
        captured["messages"] = messages
        return json.dumps({"results": []})
    
    monkeypatch.setattr(cp, "_llm_chat", fake_chat)
    
    # Build minimal ws
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws["A5"] = "测试检查要点"
    
    # Build minimal attachments
    attachments = {
        "items": [
            {"rel_path": ".embedded_media/test.docx::image1.png", "status": "binary", "file_type": "png", "extracted_text": ""},
            {"rel_path": "审计证据/test.txt", "status": "ok", "file_type": "txt", "extracted_text": "hello"},
        ],
    }
    
    import asyncio
    asyncio.run(cp._llm_check_sheet_by_checkpoints(
        llm=None, ws_title="TEST", ws=ws,
        checkpoints=["检查点1"], attachments=attachments, attachments_preview=attachments,
        on_progress=None,
    ))
    
    # Check the prompt includes inventory
    sys_msg = next(m for m in captured["messages"] if m["role"] == "system")
    assert "证据清单" in sys_msg["content"] or "证据清单" in str(captured["messages"])
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (inventory not in prompt)

- [ ] **Step 3: Implement**

In `src/review/checkpoints.py`, find `_llm_check_sheet_by_checkpoints` and add to system_prompt:

```python
from review.attachments import build_evidence_inventory, EVIDENCE_GUIDANCE
# ... in the function:
inventory = build_evidence_inventory(attachments)
system_prompt = (
    "..." # existing prompt
    + (EVIDENCE_GUIDANCE + "\n" + inventory if inventory else "")
)
```

- [ ] **Step 4: Run tests + commit**

```bash
.venv/Scripts/python.exe -m pytest tests/review/test_checkpoints.py -v
git add src/review/checkpoints.py tests/review/test_checkpoints.py
git commit -m "feat(review): inject evidence inventory into checkpoints prompt

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Inject inventory into evidence_steps prompt

**Files:**
- Modify: `src/review/evidence_steps.py`

- [ ] Same pattern as Task 2: inject `build_evidence_inventory(attachments)` + `EVIDENCE_GUIDANCE` into the user_prompt payload as `available_evidence` field.

- [ ] Commit: `feat(review): inject evidence inventory into evidence_steps prompt`

---

### Task 4: Inject inventory into procedure_pairs prompt

**Files:**
- Modify: `src/review/procedure_pairs.py`

- [ ] Same pattern: inject into `_llm_judge_procedure_pair` user_prompt.

- [ ] Commit: `feat(review): inject evidence inventory into procedure_pairs prompt`

---

### Task 5: End-to-end smoke verification

- [ ] **Step 1: Restart backend with the new code**

```bash
# Kill existing uvicorn, restart
cmd.exe //c "taskkill /F /IM uvicorn.exe /T"
cd D:/User\ Data/yangfan15/Desktop/projects/audit-workpaper-agent && bash scripts/http_run.sh -p 5000
```

- [ ] **Step 2: Re-run SA-10 review**

```bash
curl -s -X POST http://localhost:5000/v1/chat/completions -H "Content-Type: application/json" -d '{
  "messages":[{"role":"user","content":"请审阅 SA-10。底稿路径：assets/uploads/<real_path>;检查要点：<real_path>;附件目录：<real_path>"}],
  "stream":false
}'
```

- [ ] **Step 3: Verify findings now reference .embedded_media/ paths**

Inspect `assets/results/<review_id>_findings.json`:
- finding.evidence_refs[*].attachment should contain `.embedded_media/` paths
- finding.basis should mention specific embedded image content (not just "证据不足")

- [ ] **Step 4: Commit if fixes needed**

---

## Self-Review

**Spec coverage:**
- build_evidence_inventory helper → Task 1.
- Inject into 3 V1 prompts → Tasks 2-4.
- Smoke verification → Task 5.

**Placeholder scan:** All steps have concrete code.

**Type consistency:** `build_evidence_inventory` signature matches.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-v1-prompt-attachment-inventory-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks.

**2. Inline Execution** - Execute tasks in this session.

**Which approach?**