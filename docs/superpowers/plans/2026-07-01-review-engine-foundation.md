# Review Engine Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the foundational, dependency-free layer of `wpreview/analyze_excel.py` into a new `src/review/` package: data models, Excel utilities, finding validation/repair, and an async LLM-call helper — all unit-tested in isolation.

**Architecture:** Four focused modules under `src/review/` (`models` → `excel_utils` → `validation` → `llm`), ported from the reference file with two adaptations: (1) no `jsonschema` dependency — the finding schema is validated by a hand-written validator; (2) the LLM helper is async over `langchain_openai.ChatOpenAI` (replacing the reference's sync OpenAI SDK + ThreadPoolExecutor) so it fits the project's async LangGraph agent. A pytest test suite is introduced (none exists yet).

**Tech Stack:** Python 3.12, openpyxl, langchain-openai (`ChatOpenAI`), pytest, pytest-asyncio. Imports are rooted at `src/` (e.g. `from review.models import Finding`).

**Reference file:** `D:\User Data\yangfan15\Desktop\projects\wpreview\analyze_excel.py` — line ranges cited per task.

---

## File Structure

- Create: `tests/__init__.py` (empty, marks test root)
- Create: `tests/review/__init__.py` (empty)
- Create: `tests/review/conftest.py` (shared fixtures)
- Create: `tests/review/test_models.py`
- Create: `tests/review/test_excel_utils.py`
- Create: `tests/review/test_validation.py`
- Create: `tests/review/test_llm.py`
- Create: `src/review/__init__.py` (empty)
- Create: `src/review/models.py` — `Finding`, `AttachmentPreviewItem`, severity maps, schema constant, excerpt constants
- Create: `src/review/excel_utils.py` — `_is_empty`, `_get_cell_value`, `_get_cell_text`, `_truncate`, `_detect_layout`, `_extract_sheet_text_cells`, `_build_sheet_text_for_llm`, `_normalize_sheet_id`
- Create: `src/review/validation.py` — `_excerpt_matches`, `_validate_finding_result`, `_repair_finding_result`, `_validate_llm_results`, `_verify_evidence_refs`
- Create: `src/review/llm.py` — `LLM_CALL_STATS`, `_llm_stat`, `_classify_llm_error`, `_to_langchain_messages`, `_try_parse_json`, `_llm_chat` (async), `_llm_request_json_list` (async), `get_review_llm`
- Modify: `pyproject.toml` — add `[dependency-groups] dev` with pytest + pytest-asyncio, add `[tool.pytest.ini_options]`

---

## Task 0: Test infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`, `tests/review/__init__.py`, `tests/review/conftest.py`

- [ ] **Step 1: Add dev dependencies and pytest config to `pyproject.toml`**

Append to `pyproject.toml` (after the existing `[tool.uv]` block):

```toml
[dependency-groups]
dev = [
    "pytest>=8.3,<9",
    "pytest-asyncio>=0.24,<0.25",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty test package markers**

Create `tests/__init__.py` and `tests/review/__init__.py` as empty files.

- [ ] **Step 3: Create `tests/review/conftest.py` with a shared workbook fixture**

```python
import openpyxl
import pytest


@pytest.fixture
def blank_workbook():
    return openpyxl.Workbook()


@pytest.fixture
def layout_workbook():
    """A sheet with a standard layout: header row 1, standard col A, exec col B."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A2"] = "获取系统用户清单并检查权限。"
    ws["B2"] = "我们导出用户清单，截图保存。"
    return wb
```

- [ ] **Step 4: Install dev dependencies**

Run: `uv sync --group dev`
Expected: pytest and pytest-asyncio install successfully.

- [ ] **Step 5: Verify pytest runs (no tests collected yet)**

Run: `uv run pytest -q`
Expected: `no tests ran` (exit code 5 is fine for now) or 0 — no collection errors.

- [ ] **Step 6: Create the `review` package**

Create `src/review/__init__.py` as an empty file (so `from review.models import ...` resolves once `src` is on `pythonpath`).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/ src/review/__init__.py
git commit -m "chore: 引入 pytest 测试基础设施与 review 包骨架"
```

---

## Task 1: `models.py` — Finding dataclass and constants

**Reference:** `analyze_excel.py` lines 19-110.

**Files:**
- Create: `src/review/models.py`
- Test: `tests/review/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/review/test_models.py`:

```python
from review.models import (
    Finding,
    AttachmentPreviewItem,
    _SEVERITY_DISPLAY,
    _SEVERITY_FROM_CHINESE,
    _EXCERPT_MAX_LEN,
    _EXCERPT_CONSTRUCTED_MARKER,
    _FINDING_RESULT_SCHEMA,
)


def test_severity_display_maps_p_codes_to_chinese():
    assert _SEVERITY_DISPLAY["P0"] == "高"
    assert _SEVERITY_DISPLAY["P1"] == "中"
    assert _SEVERITY_DISPLAY["P2"] == "低"


def test_severity_from_chinese_round_trips():
    assert _SEVERITY_FROM_CHINESE["高"] == "P0"
    assert _SEVERITY_FROM_CHINESE["中"] == "P1"
    assert _SEVERITY_FROM_CHINESE["低"] == "P2"


def test_excerpt_constants():
    assert _EXCERPT_MAX_LEN == 2000
    assert _EXCERPT_CONSTRUCTED_MARKER == "[非逐字原文]"


def test_finding_defaults_are_backward_compatible():
    f = Finding(
        issue_type="t",
        severity="P1",
        sheet="SA-1",
        cell=None,
        snippet="s",
        basis="b",
        suggestion="sug",
    )
    assert f.status == "fail"
    assert f.risk_type == ""
    assert f.evidence_refs == "[]"
    assert f.conclusion == ""
    assert f.reasons == "[]"
    assert f.fix_suggestion_detail == "{}"
    assert f.unknown_reason == ""
    assert f.needs_review is False


def test_finding_is_frozen():
    import pytest
    f = Finding(issue_type="t", severity="P1", sheet="SA-1", cell=None,
                snippet="s", basis="b", suggestion="sug")
    with pytest.raises(Exception):
        f.status = "pass"  # type: ignore[misc]


def test_finding_result_schema_required_fields():
    required = _FINDING_RESULT_SCHEMA["required"]
    assert required == ["status", "conclusion", "evidence_refs"]


def test_attachment_preview_item_fields():
    item = AttachmentPreviewItem(
        index="1", rel_dir="d", filename="f.png", rel_path="d/f.png",
        file_type="png", description="desc", status="OK",
    )
    assert item.filename == "f.png"
    assert item.status == "OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/review/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review.models'`.

- [ ] **Step 3: Write minimal implementation**

`src/review/models.py`:

```python
"""Data models for the review engine (ported from analyze_excel.py)."""
from dataclasses import dataclass
from typing import Any, Dict, Optional


# Severity mapping: internal P0/P1/P2 <-> display 高/中/低
_SEVERITY_DISPLAY = {"P0": "高", "P1": "中", "P2": "低"}
_SEVERITY_FROM_CHINESE = {"高": "P0", "中": "P1", "低": "P2"}

# Maximum length for excerpt text in evidence_refs
_EXCERPT_MAX_LEN = 2000
# Marker added when an excerpt was constructed (not verbatim from a cell)
_EXCERPT_CONSTRUCTED_MARKER = "[非逐字原文]"


# Unified Finding result JSON Schema — documents the shape each LLM result
# must conform to. Validation is enforced by review.validation by hand
# (no jsonschema dependency).
_FINDING_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["status", "conclusion", "evidence_refs"],
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail", "unknown"]},
        "conclusion": {"type": "string", "minLength": 4},
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
        },
        "evidence_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cell_or_range"],
                "properties": {
                    "sheet": {"type": "string"},
                    "cell_or_range": {"type": "string"},
                    "attachment": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
            },
        },
        "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
        "risk_type": {
            "type": "string",
            "enum": ["覆盖性", "一致性", "证据不足", "方法性", "逻辑性", "跨字段一致性"],
        },
        "fix_suggestion": {
            "type": "object",
            "properties": {
                "missing_field": {"type": "string"},
                "supplement_explanation": {"type": "string"},
                "required_evidence_type": {"type": "string"},
            },
        },
        "unknown_reason": {"type": "string"},
    },
}


@dataclass(frozen=True)
class Finding:
    issue_type: str
    severity: str  # internal P0/P1/P2; output maps to 高/中/低
    sheet: str
    cell: Optional[str]
    snippet: str
    basis: str
    suggestion: str
    # --- extended fields (all have defaults, backward compatible) ---
    status: str = "fail"  # pass / fail / unknown
    risk_type: str = ""  # 覆盖性 / 一致性 / 证据不足 / ...
    evidence_refs: str = "[]"  # JSON string of list[dict]
    conclusion: str = ""
    reasons: str = "[]"  # JSON string of list[str]
    fix_suggestion_detail: str = "{}"  # JSON string of dict
    unknown_reason: str = ""
    needs_review: bool = False


@dataclass(frozen=True)
class AttachmentPreviewItem:
    index: str
    rel_dir: str
    filename: str
    rel_path: str
    file_type: str
    description: str
    status: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/review/test_models.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/review/models.py tests/review/test_models.py
git commit -m "feat(review): 移植 Finding 模型与常量到 review.models"
```

---

## Task 2: `excel_utils.py` — openpyxl helpers

**Reference:** `analyze_excel.py` lines 287-314 (`_get_cell_text`), 629-690 (`_is_empty`, `_get_cell_value`, `_truncate`, `_detect_layout`, `_extract_sheet_text_cells`), 1199-1263 (`_normalize_sheet_id`, `_build_sheet_text_for_llm`).

**Files:**
- Create: `src/review/excel_utils.py`
- Test: `tests/review/test_excel_utils.py`

- [ ] **Step 1: Write the failing test**

`tests/review/test_excel_utils.py`:

```python
import openpyxl
from review.excel_utils import (
    _is_empty,
    _get_cell_value,
    _get_cell_text,
    _truncate,
    _detect_layout,
    _extract_sheet_text_cells,
    _build_sheet_text_for_llm,
    _normalize_sheet_id,
)


def test_is_empty():
    assert _is_empty(None) is True
    assert _is_empty("   ") is True
    assert _is_empty("x") is False
    assert _is_empty(0) is False


def test_truncate():
    assert _truncate("short", 10) == "short"
    assert _truncate("1234567890ab", 5) == "12345..."


def test_get_cell_value_handles_merged_cells(layout_workbook):
    ws = layout_workbook.active
    ws.merge_cells("A3:B3")
    ws["A3"] = "合并值"
    assert _get_cell_value(ws, "B3") == "合并值"


def test_get_cell_value_empty_returns_none(layout_workbook):
    ws = layout_workbook.active
    assert _get_cell_value(ws, "Z9") is None


def test_get_cell_text_strips_constructed_marker(layout_workbook):
    ws = layout_workbook.active
    ws["A2"] = "用户清单"
    assert _get_cell_text(ws, "A2[非逐字原文]") == "用户清单"
    assert _get_cell_text(ws, "") == ""


def test_detect_layout_finds_standard_and_exec(layout_workbook):
    ws = layout_workbook.active
    header_row, std_col, exec_cols = _detect_layout(ws)
    assert header_row == 1
    assert std_col == 1
    assert exec_cols == [2]


def test_detect_layout_returns_empty_when_no_layout(blank_workbook):
    ws = blank_workbook.active
    ws["A1"] = "无关文本"
    assert _detect_layout(ws) == (None, 0, [])


def test_extract_sheet_text_cells_yields_coord_text(layout_workbook):
    ws = layout_workbook.active
    cells = list(_extract_sheet_text_cells(ws))
    coords = {c for c, _ in cells}
    assert "A1" in coords and "A2" in coords
    text_map = dict(cells)
    assert text_map["A2"].startswith("我们导出用户清单")


def test_build_sheet_text_for_llm_respects_limits(layout_workbook):
    ws = layout_workbook.active
    text = _build_sheet_text_for_llm(ws, max_cells=1, max_chars=10_000)
    assert text.startswith("A1:")
    assert text.count("\n") == 0  # only one cell


def test_normalize_sheet_id():
    assert _normalize_sheet_id("sa-4c") == "SA4C"
    assert _normalize_sheet_id("PM_5") == "PM5"
    assert _normalize_sheet_id("  sa 4c ") == "SA4C"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/review/test_excel_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review.excel_utils'`.

- [ ] **Step 3: Write minimal implementation**

`src/review/excel_utils.py`:

```python
"""openpyxl helpers for the review engine (ported from analyze_excel.py)."""
from typing import Iterable, List, Optional, Tuple

from openpyxl.utils import get_column_letter

from review.models import _EXCERPT_CONSTRUCTED_MARKER


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _get_cell_value(ws, cell_ref: str) -> Optional[str]:
    """Get a cell value, resolving merged-cell anchors to the top-left value."""
    cell = ws[cell_ref]
    value = cell.value
    if value is None and ws.merged_cells.ranges:
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                value = ws.cell(row=merged_range.min_row, column=merged_range.min_col).value
                break
    if _is_empty(value):
        return None
    return str(value).strip()


def _get_cell_text(ws, cell_ref: str) -> str:
    """Safely get cell text, stripping the constructed-excerpt marker suffix."""
    if not cell_ref or not ws:
        return ""
    clean_ref = cell_ref.replace(_EXCERPT_CONSTRUCTED_MARKER, "").strip()
    if not clean_ref:
        return ""
    try:
        cell = ws[clean_ref]
        val = cell.value
        return str(val).strip() if val is not None else ""
    except Exception:
        return ""


def _truncate(text: str, n: int = 160) -> str:
    s = (text or "").strip()
    if len(s) <= n:
        return s
    return s[:n] + "..."


def _detect_layout(ws) -> Tuple[Optional[int], int, List[int]]:
    """Detect the header row, the standard-program column and exec columns."""
    max_scan_row = min(ws.max_row or 0, 40)
    max_scan_col = min(ws.max_column or 0, 30)
    for r in range(1, max_scan_row + 1):
        standard_col = None
        exec_cols: List[int] = []
        for c in range(1, max_scan_col + 1):
            v = _get_cell_value(ws, f"{get_column_letter(c)}{r}")
            if not v:
                continue
            if ("标准" in v and "审计程序" in v) or ("标准审计程序" in v):
                standard_col = c
            if "执行" in v and "审计程序" in v:
                exec_cols.append(c)
        if standard_col and exec_cols:
            exec_cols = sorted({c for c in exec_cols if c != standard_col})
            if exec_cols:
                return r, standard_col, exec_cols
    return None, 0, []


def _extract_sheet_text_cells(ws) -> Iterable[Tuple[str, str]]:
    for row in ws.iter_rows(values_only=False):
        for cell in row:
            if _is_empty(cell.value):
                continue
            value = cell.value
            if isinstance(value, str):
                text = value.strip()
            else:
                text = str(value).strip()
            if not text:
                continue
            yield cell.coordinate, text


def _build_sheet_text_for_llm(ws, max_cells: int = 260, max_chars: int = 24000) -> str:
    parts: List[str] = []
    total_chars = 0
    for coord, text in _extract_sheet_text_cells(ws):
        line = f"{coord}: {text}"
        if len(parts) >= max_cells:
            break
        if total_chars + len(line) + 1 > max_chars:
            break
        parts.append(line)
        total_chars += len(line) + 1
    return "\n".join(parts)


def _normalize_sheet_id(text: str) -> str:
    s = (text or "").strip().upper()
    s = s.replace(" ", "").replace("-", "").replace("_", "")
    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/review/test_excel_utils.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/review/excel_utils.py tests/review/test_excel_utils.py
git commit -m "feat(review): 移植 openpyxl 辅助函数到 review.excel_utils"
```

---

## Task 3: `validation.py` — finding validation, repair, evidence-ref verification

**Reference:** `analyze_excel.py` lines 116-149 (`_validate_finding_result`), 152-284 (`_repair_finding_result`, `_validate_llm_results`), 287-344 (`_excerpt_matches`, `_verify_evidence_refs`).

**Files:**
- Create: `src/review/validation.py`
- Test: `tests/review/test_validation.py`

- [ ] **Step 1: Write the failing test**

`tests/review/test_validation.py`:

```python
from review.validation import (
    _excerpt_matches,
    _validate_finding_result,
    _repair_finding_result,
    _validate_llm_results,
    _verify_evidence_refs,
)


def test_excerpt_matches_substring_after_normalisation():
    assert _excerpt_matches("系统截图", "请查看系统截图配置界面") is True
    assert _excerpt_matches("不存在", "这里是别的文字") is False
    assert _excerpt_matches("", "x") is False


def test_validate_pass_is_valid():
    ok, errors = _validate_finding_result({
        "status": "pass", "conclusion": "无问题结论", "evidence_refs": [],
    })
    assert ok, errors


def test_validate_fail_without_evidence_is_invalid():
    ok, errors = _validate_finding_result({
        "status": "fail", "conclusion": "有问题结论",
        "evidence_refs": [], "severity": "P0", "risk_type": "证据不足",
    })
    assert not ok
    assert any("evidence_refs" in e for e in errors)


def test_validate_fail_with_evidence_is_valid():
    ok, errors = _validate_finding_result({
        "status": "fail", "conclusion": "有问题结论",
        "evidence_refs": [{"cell_or_range": "A1"}],
        "severity": "P0", "risk_type": "证据不足",
    })
    assert ok, errors


def test_validate_unknown_requires_reason_and_severity():
    ok, _ = _validate_finding_result({
        "status": "unknown", "conclusion": "不确定结论",
        "evidence_refs": [], "unknown_reason": "短",
    })
    assert not ok
    ok2, _ = _validate_finding_result({
        "status": "unknown", "conclusion": "不确定结论",
        "evidence_refs": [], "unknown_reason": "这里有十个字符以上的原因说明",
        "severity": "P2", "risk_type": "证据不足",
    })
    assert ok2


def test_validate_rejects_bad_status():
    ok, _ = _validate_finding_result({
        "status": "maybe", "conclusion": "abcd", "evidence_refs": [],
    })
    assert not ok


def test_repair_migrates_chinese_status_and_severity():
    repaired = _repair_finding_result({
        "status": "有问题", "conclusion": "测试结论文本",
        "severity": "高", "risk_type": "证据不足",
    })
    assert repaired["status"] == "fail"
    assert repaired["severity"] == "P0"
    # fail without constructable evidence -> downgraded to unknown
    assert repaired["status"] == "unknown" or repaired["evidence_refs"]


def test_repair_downgrades_fail_without_evidence_to_unknown():
    repaired = _repair_finding_result({
        "status": "fail", "conclusion": "测试结论文本",
        "severity": "高", "risk_type": "证据不足",
    })
    assert repaired["status"] == "unknown"
    assert len(repaired["unknown_reason"]) >= 10
    assert repaired["severity"] == "P2"


def test_repair_constructs_evidence_refs_from_related_cells():
    repaired = _repair_finding_result({
        "status": "fail", "conclusion": "测试结论文本",
        "severity": "P1", "risk_type": "证据不足",
        "related_cells": ["A1", "B2"],
        "snippet": "原始摘录内容",
    })
    refs = repaired["evidence_refs"]
    assert isinstance(refs, list) and len(refs) == 2
    assert all(_EXCERPT_MARKER in r["cell_or_range"] for r in refs)  # constructed


_EXCERPT_MARKER = "[非逐字原文]"


def test_repair_pass_keeps_empty_evidence_refs():
    repaired = _repair_finding_result({
        "status": "无问题", "conclusion": "无问题结论",
    })
    assert repaired["status"] == "pass"
    assert repaired["evidence_refs"] == []


def test_validate_llm_results_returns_valid_and_retry_flag():
    items = [
        {"status": "pass", "conclusion": "无问题结论", "evidence_refs": []},
        {"status": "fail", "conclusion": "有问题结论", "evidence_refs": [],
         "severity": "P0", "risk_type": "证据不足"},
        "not a dict",
    ]
    valid, needs_retry = _validate_llm_results(items)
    assert isinstance(valid, list)
    assert needs_retry is True  # the non-dict item is unrepairable


def test_verify_evidence_refs_keeps_matching_drops_mismatched(layout_workbook):
    from review.excel_utils import _get_cell_value  # noqa: F401
    ws = layout_workbook.active
    ws["A2"] = "我们导出用户清单，截图保存。"
    refs = [
        {"cell_or_range": "A2", "excerpt": "导出用户清单"},
        {"cell_or_range": "A2", "excerpt": "完全不相关的摘录"},
        {"cell_or_range": "Z9", "excerpt": "无效单元格"},
    ]
    verified = _verify_evidence_refs(refs, ws)
    assert len(verified) == 2
    # mismatched excerpt replaced with actual cell text
    assert verified[1]["excerpt"].startswith("我们导出用户清单")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/review/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review.validation'`.

- [ ] **Step 3: Write minimal implementation**

`src/review/validation.py`:

```python
"""Finding validation, repair and evidence-ref verification (ported from analyze_excel.py).

No jsonschema dependency: the schema is enforced by hand here.
"""
import re
from typing import Any, List, Optional, Tuple

from review.models import (
    _EXCERPT_CONSTRUCTED_MARKER,
    _EXCERPT_MAX_LEN,
    _SEVERITY_FROM_CHINESE,
)

_VALID_STATUSES = {"pass", "fail", "unknown"}
_VALID_SEVERITIES = {"P0", "P1", "P2"}
_VALID_RISK_TYPES = {"覆盖性", "一致性", "证据不足", "方法性", "逻辑性", "跨字段一致性"}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def _excerpt_matches(excerpt: str, actual_text: str) -> bool:
    """Check if excerpt is a substring of actual_text after normalisation."""
    norm_ex = _PUNCT_RE.sub("", _WS_RE.sub("", excerpt or "")).lower()
    norm_at = _PUNCT_RE.sub("", _WS_RE.sub("", actual_text or "")).lower()
    if not norm_ex or not norm_at:
        return False
    return norm_ex in norm_at


def _validate_finding_result(obj: Any) -> Tuple[bool, List[str]]:
    """Validate a single finding dict. Returns (valid, errors).

    Beyond shape checks, enforces:
    - status == "fail" => evidence_refs non-empty
    - status == "unknown" => unknown_reason non-empty and >= 10 chars
    - status != "pass" => severity and risk_type required
    """
    if not isinstance(obj, dict):
        return False, ["result is not a dict"]
    errors: List[str] = []

    status = str(obj.get("status", "")).strip()
    if status not in _VALID_STATUSES:
        errors.append(f"status must be one of {sorted(_VALID_STATUSES)}; got {status!r}")

    conclusion = str(obj.get("conclusion", "")).strip()
    if len(conclusion) < 4:
        errors.append("conclusion must be a string of >= 4 chars")

    refs = obj.get("evidence_refs")
    if not isinstance(refs, list):
        errors.append("evidence_refs must be an array")

    sev = str(obj.get("severity", "")).strip()
    if sev and sev not in _VALID_SEVERITIES:
        errors.append(f"severity must be one of {sorted(_VALID_SEVERITIES)}; got {sev!r}")

    risk = str(obj.get("risk_type", "")).strip()
    if risk and risk not in _VALID_RISK_TYPES:
        errors.append(f"risk_type must be one of {sorted(_VALID_RISK_TYPES)}; got {risk!r}")

    if status == "fail":
        if not isinstance(refs, list) or len(refs) == 0:
            errors.append("status=fail but evidence_refs is empty")
    if status == "unknown":
        reason = str(obj.get("unknown_reason", "")).strip()
        if len(reason) < 10:
            errors.append("status=unknown but unknown_reason is empty or <10 chars")
    if status != "pass":
        if not sev:
            errors.append("status!=pass but severity is missing")
        if not risk:
            errors.append("status!=pass but risk_type is missing")

    return (len(errors) == 0, errors)


def _repair_finding_result(obj: Any) -> Optional[dict]:
    """Attempt to fix common issues in a finding dict. Returns repaired dict or None."""
    if not isinstance(obj, dict):
        return None
    repaired = dict(obj)

    # --- status migration: legacy Chinese -> pass/fail/unknown ---
    old_status = str(repaired.get("status", "")).strip()
    if old_status == "无问题":
        repaired["status"] = "pass"
    elif old_status == "有问题":
        repaired["status"] = "fail"
    elif old_status == "不确定":
        repaired["status"] = "unknown"
    status = repaired.get("status", "fail")

    # --- severity migration: 高/中/低 -> P0/P1/P2 ---
    sev = str(repaired.get("severity", "")).strip()
    if sev in _SEVERITY_FROM_CHINESE:
        repaired["severity"] = _SEVERITY_FROM_CHINESE[sev]
    elif sev not in ("P0", "P1", "P2", ""):
        repaired["severity"] = "P1"
    if status != "pass" and not repaired.get("severity"):
        repaired["severity"] = "P1"

    # --- conclusion: derive from basis if missing ---
    if not repaired.get("conclusion"):
        basis = str(repaired.get("basis", "")).strip()
        if basis:
            repaired["conclusion"] = basis[:200]
        else:
            repaired["conclusion"] = f"发现{status}类问题"

    # --- evidence_refs: construct from related_cells + snippet if missing ---
    refs = repaired.get("evidence_refs")
    constructed_from_fallback = False
    if not isinstance(refs, list) or not refs:
        constructed: List[dict] = []
        related = repaired.get("related_cells") or repaired.get("cell") or ""
        if isinstance(related, list):
            cells = related
        elif isinstance(related, str):
            cells = [c.strip() for c in re.split(r"[,;，；\s]+", related) if c.strip()]
        else:
            cells = []
        snippet_text = str(repaired.get("snippet", "") or repaired.get("basis", "")).strip()
        for c in cells:
            ref: dict = {"cell_or_range": c}
            if snippet_text:
                ref["excerpt"] = snippet_text[:_EXCERPT_MAX_LEN]
            constructed.append(ref)
        if not constructed and snippet_text:
            constructed.append({"cell_or_range": "", "excerpt": snippet_text[:_EXCERPT_MAX_LEN]})
        constructed_from_fallback = bool(constructed)
        if constructed_from_fallback:
            for ref in constructed:
                if isinstance(ref, dict) and ref.get("cell_or_range"):
                    ref["cell_or_range"] = str(ref.get("cell_or_range", "")) + _EXCERPT_CONSTRUCTED_MARKER
        repaired["evidence_refs"] = constructed

    # --- fail with empty evidence_refs => downgrade to unknown ---
    if repaired.get("status") == "fail":
        refs = repaired.get("evidence_refs") or []
        if not isinstance(refs, list) or len(refs) == 0:
            repaired["status"] = "unknown"
            repaired["unknown_reason"] = "无法引用原始证据佐证该判定，降级为不确定"
            repaired["severity"] = "P2"
            status = "unknown"

    # --- risk_type: default if missing ---
    if status != "pass" and not repaired.get("risk_type"):
        repaired["risk_type"] = "证据不足"

    # --- unknown_reason: auto-generate if missing ---
    if status == "unknown":
        reason = str(repaired.get("unknown_reason", "")).strip()
        if len(reason) < 10:
            repaired["unknown_reason"] = "LLM未说明不确定原因：需要补充更多信息以判定"

    # --- reasons: derive from basis if missing ---
    if not repaired.get("reasons"):
        basis = str(repaired.get("basis", "")).strip()
        if basis:
            repaired["reasons"] = [basis[:300]]
        else:
            repaired["reasons"] = [repaired.get("conclusion", "")]

    # --- fix_suggestion: derive from suggestion if missing ---
    if not repaired.get("fix_suggestion"):
        sug = str(repaired.get("suggestion", "")).strip()
        if sug:
            repaired["fix_suggestion"] = {"supplement_explanation": sug[:300]}
        else:
            repaired["fix_suggestion"] = {}

    return repaired


def _validate_llm_results(results_list: List[Any]) -> Tuple[List[dict], bool]:
    """Validate and repair a list of finding dicts.

    Returns (valid_results, needs_retry). If any result is unrepairable,
    needs_retry=True.
    """
    valid: List[dict] = []
    needs_retry = False
    for obj in results_list:
        if not isinstance(obj, dict):
            needs_retry = True
            continue
        ok, _ = _validate_finding_result(obj)
        if ok:
            valid.append(obj)
        else:
            repaired = _repair_finding_result(obj)
            if repaired is not None:
                ok2, _ = _validate_finding_result(repaired)
                if ok2:
                    valid.append(repaired)
                else:
                    needs_retry = True
            else:
                needs_retry = True
    return valid, needs_retry


def _verify_evidence_refs(evidence_refs: List[dict], ws) -> List[dict]:
    """Verify evidence_refs excerpts match actual cell text; repair or drop.

    Constructed refs (marker suffix) are preserved as-is.
    """
    if not ws:
        return evidence_refs
    verified: List[dict] = []
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            continue
        cell = ref.get("cell_or_range", "")
        excerpt = ref.get("excerpt", "")
        if _EXCERPT_CONSTRUCTED_MARKER in str(cell):
            verified.append(ref)
            continue
        clean_ref = str(cell).replace(_EXCERPT_CONSTRUCTED_MARKER, "").strip()
        try:
            ws_cell = ws[clean_ref] if clean_ref else None
            val = ws_cell.value if ws_cell is not None else None
        except Exception:
            val = None
        actual_text = str(val).strip() if val is not None else ""
        if actual_text and _excerpt_matches(excerpt, actual_text):
            verified.append(ref)
        elif actual_text:
            verified.append({**ref, "excerpt": actual_text[:_EXCERPT_MAX_LEN]})
        # else: cell invalid or empty -> drop
    return verified
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/review/test_validation.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/review/validation.py tests/review/test_validation.py
git commit -m "feat(review): 移植 finding 校验/修复/摘录核验到 review.validation"
```

---

## Task 4: `llm.py` — async LLM-call helper over ChatOpenAI

**Reference:** `analyze_excel.py` lines 736-745 (`LLM_CALL_STATS`, `_llm_stat`), 748-808 (`_classify_llm_error`, `_llm_backoff_sleep`, `_llm_chat`), 811-898 (`_llm_request_json_list`), 2407-2422 (`_try_parse_json`).

**Adaptations:** async (`asyncio.sleep`, `ChatOpenAI.ainvoke`); per-call `max_tokens` via `llm.bind(max_tokens=...)`; temperature fixed at construction (0.1). Messages are OpenAI-style dicts converted to LangChain messages.

**Files:**
- Create: `src/review/llm.py`
- Test: `tests/review/test_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/review/test_llm.py`:

```python
import os
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from review.llm import (
    LLM_CALL_STATS,
    _classify_llm_error,
    _to_langchain_messages,
    _try_parse_json,
    _llm_chat,
    _llm_stat,
)


class _FakeRunnable:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        outcome = self.outcomes[(self.calls - 1) % len(self.outcomes)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeLLM:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.bound = None

    def bind(self, **kwargs):
        self.bound = _FakeRunnable(self.outcomes)
        return self.bound


def test_classify_llm_error():
    assert _classify_llm_error(RuntimeError("Connection timed out")) == "timeout"
    assert _classify_llm_error(RuntimeError("rate limit hit 429")) == "rate_limit"
    assert _classify_llm_error(RuntimeError("context length exceeded")) == "context"
    assert _classify_llm_error(RuntimeError("502 bad gateway")) == "server"
    assert _classify_llm_error(RuntimeError("something else")) == "other"
    assert _classify_llm_error(RuntimeError("")) == "other"


def test_try_parse_json():
    assert _try_parse_json('{"results": [1, 2]}') == {"results": [1, 2]}
    assert _try_parse_json('noise {"a": 1} tail') == {"a": 1}
    assert _try_parse_json("no json here") is None
    assert _try_parse_json("") is None


def test_to_langchain_messages():
    msgs = _to_langchain_messages([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ])
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert isinstance(msgs[2], AIMessage)


def test_llm_stat_tracks_counts():
    LLM_CALL_STATS.clear()
    _llm_stat("stage1", "calls", 1)
    _llm_stat("stage1", "calls", 1)
    assert LLM_CALL_STATS["stage1"]["calls"] == 2


@pytest.mark.asyncio
async def test_llm_chat_returns_content_on_success(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([AIMessage(content="hello")])
    out = await _llm_chat(
        llm=llm, messages=[{"role": "user", "content": "hi"}],
        stage="t", max_attempts=1, max_tokens=64,
    )
    assert out == "hello"


@pytest.mark.asyncio
async def test_llm_chat_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([
        RuntimeError("timed out"),
        RuntimeError("timed out"),
        AIMessage(content="ok"),
    ])
    out = await _llm_chat(
        llm=llm, messages=[{"role": "user", "content": "hi"}],
        stage="t", max_attempts=3, max_tokens=64,
    )
    assert out == "ok"
    assert llm.bound.calls == 3


@pytest.mark.asyncio
async def test_llm_chat_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([RuntimeError("timed out")])
    with pytest.raises(RuntimeError):
        await _llm_chat(
            llm=llm, messages=[{"role": "user", "content": "hi"}],
            stage="t", max_attempts=2, max_tokens=64,
        )
    assert LLM_CALL_STATS["t"]["error_timeout"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/review/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review.llm'`.

- [ ] **Step 3: Write minimal implementation**

`src/review/llm.py`:

```python
"""Async LLM-call infrastructure for the review engine.

Adapted from analyze_excel.py: replaces the sync OpenAI SDK + ThreadPoolExecutor
with async calls over langchain_openai.ChatOpenAI so it fits the project's
async LangGraph agent. No jsonschema dependency.
"""
import asyncio
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from review.validation import _validate_llm_results

LLM_CALL_STATS: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

_ROLE_TO_MSG = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


def _llm_stat(stage: str, key: str, n: int = 1) -> None:
    if not stage or not key:
        return
    try:
        LLM_CALL_STATS[str(stage)][str(key)] += int(n)
    except Exception:
        return


def _classify_llm_error(err: Exception) -> str:
    s = str(err or "").strip().lower()
    if not s:
        return "other"
    if "timed out" in s or "timeout" in s:
        return "timeout"
    if "rate limit" in s or "429" in s:
        return "rate_limit"
    if "context length" in s or "maximum context" in s or "max tokens" in s:
        return "context"
    if "json" in s and ("parse" in s or "nonjson" in s or "非json" in s):
        return "parse"
    if "502" in s or "503" in s or "504" in s or "bad gateway" in s or "gateway" in s:
        return "server"
    return "other"


async def _llm_backoff_sleep(attempt: int, err_type: str) -> None:
    base = 1.2 * max(1, int(attempt))
    if err_type == "rate_limit":
        base = max(base, 6.0) * max(1, int(attempt))
    elif err_type in {"server", "timeout"}:
        base = max(base, 3.0) * max(1, int(attempt))
    try:
        scale = float(os.getenv("REVIEW_LLM_BACKOFF_SCALE", "1.0"))
    except Exception:
        scale = 1.0
    await asyncio.sleep(min(30.0, base) * max(0.0, scale))


def _to_langchain_messages(messages: List[Dict[str, str]]) -> List[Any]:
    out = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        cls = _ROLE_TO_MSG.get(role, HumanMessage)
        out.append(cls(content=content))
    return out


async def _llm_chat(
    *,
    llm,
    messages: List[Dict[str, str]],
    stage: str,
    max_attempts: int = 3,
    max_tokens: int = 2048,
) -> str:
    """Call the LLM with retry/backoff. Returns the response content string."""
    lc_messages = _to_langchain_messages(messages)
    bound = llm.bind(max_tokens=max_tokens)
    last_error: Optional[str] = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            _llm_stat(stage, "calls", 1)
            resp = await bound.ainvoke(lc_messages)
            content = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            elif not isinstance(content, str):
                content = str(content)
            _llm_stat(stage, "ok", 1)
            return content or ""
        except Exception as e:
            last_error = str(e)
            err_type = _classify_llm_error(e)
            _llm_stat(stage, f"error_{err_type}", 1)
            if attempt < max_attempts:
                await _llm_backoff_sleep(attempt, err_type)
            continue
    raise RuntimeError(last_error or "LLM调用失败")


def _try_parse_json(text: str):
    if not text:
        return None
    s = str(text).strip()
    start = None
    for i, ch in enumerate(s):
        if ch in "[{":
            start = i
            break
    if start is None:
        return None
    try:
        return json.loads(s[start:])
    except Exception:
        return None


async def _llm_request_json_list(
    *,
    llm,
    system_prompt: str,
    user_prompt: str,
    stage: str,
    max_attempts: int = 3,
) -> Tuple[Optional[List[Any]], Optional[str]]:
    """Call the LLM expecting a JSON list response ({results: [...]}).

    Retries on JSON parse / schema validation failures. Each item is validated
    and repaired via review.validation. Returns (parsed_list_or_None, error).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Optional[str] = None
    last_validation_errors: List[str] = []
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            current_messages = messages
            if last_validation_errors and attempt > 1:
                err_text = "；".join(last_validation_errors[:3])
                retry_note = (
                    f"\n\n[Retry hint] 上一次输出未通过结构化校验，问题：{err_text}。"
                    f"请严格按 system 字段定义重新输出，"
                    f"确保 status=pass/fail/unknown、severity=P0/P1/P2、"
                    f"fail 时 evidence_refs 必填且 excerpt 逐字来自原文。"
                )
                current_messages = [
                    messages[0],
                    {"role": "user", "content": user_prompt + retry_note},
                ]
            content = await _llm_chat(
                llm=llm, messages=current_messages, stage=stage,
                max_attempts=3, max_tokens=2048,
            )
            parsed = _try_parse_json(content)
            if isinstance(parsed, dict):
                parsed = parsed.get("results") or parsed.get("data") or parsed.get("items")
            if not isinstance(parsed, list):
                raise RuntimeError("LLM返回非JSON results 数组")
            valid_items, needs_retry = _validate_llm_results(parsed)
            if needs_retry:
                last_validation_errors = []
                for obj in parsed:
                    if isinstance(obj, dict):
                        ok, errs = _validate_finding_result_inline(obj)
                        if not ok:
                            last_validation_errors.extend(errs)
                if not last_validation_errors:
                    last_validation_errors = ["部分结果无法通过结构化校验"]
                if attempt < max_attempts:
                    _llm_stat(stage, "error_schema", 1)
                    await asyncio.sleep(min(8.0, 1.5 * attempt) * _backoff_scale())
                    continue
                parsed = valid_items
            return parsed, None
        except Exception as e:
            last_error = str(e)
            is_parse_error = "json" in str(e).lower() or "parse" in str(e).lower() or "非json" in str(e)
            if is_parse_error and attempt < max_attempts:
                _llm_stat(stage, "error_parse", 1)
                await asyncio.sleep(min(8.0, 1.5 * attempt) * _backoff_scale())
                continue
            if not is_parse_error:
                break
    return None, last_error or "LLM调用失败"


def _backoff_scale() -> float:
    try:
        return max(0.0, float(os.getenv("REVIEW_LLM_BACKOFF_SCALE", "1.0")))
    except Exception:
        return 1.0


# Local import alias to avoid a circular import at module load time:
# _llm_request_json_list needs per-item error detail without re-validating the
# whole schema machinery inline. Reuse the public validator.
from review.validation import _validate_finding_result as _validate_finding_result_inline  # noqa: E402


def get_review_llm() -> ChatOpenAI:
    """Build the ChatOpenAI used by the review engine, from project env."""
    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("REVIEW_LLM_MODEL", "doubao-seed-1-6-251015")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        max_retries=0,
        streaming=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/review/test_llm.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/review/llm.py tests/review/test_llm.py
git commit -m "feat(review): 移植异步 LLM 调用基础设施到 review.llm"
```

---

## Task 5: Foundation smoke test

**Files:**
- Test: `tests/review/test_foundation_smoke.py`

- [ ] **Step 1: Write a smoke test asserting all modules import and compose**

`tests/review/test_foundation_smoke.py`:

```python
"""Smoke test: the four foundation modules import cleanly and compose."""
from review.models import Finding
from review.excel_utils import _detect_layout, _get_cell_value
from review.validation import _validate_finding_result, _repair_finding_result
from review.llm import get_review_llm, _llm_request_json_list


def test_all_modules_import():
    assert Finding is not None
    assert _detect_layout is not None
    assert _validate_finding_result is not None
    assert get_review_llm is not None


def test_repair_then_validate_round_trip():
    repaired = _repair_finding_result({
        "status": "有问题", "conclusion": "测试结论文本",
        "severity": "高", "risk_type": "证据不足",
    })
    ok, errors = _validate_finding_result(repaired)
    assert ok, errors
```

- [ ] **Step 2: Run the full review test suite**

Run: `uv run pytest tests/review/ -v`
Expected: all tests pass (models 7, excel_utils 10, validation 12, llm 7, smoke 2 = 38 total).

- [ ] **Step 3: Run a quick import check from the src root**

Run: `cd src && python -c "from review.models import Finding; from review.llm import get_review_llm; print('ok')"`
Expected: prints `ok` (no ImportError).

- [ ] **Step 4: Commit**

```bash
git add tests/review/test_foundation_smoke.py
git commit -m "test(review): 新增基础层导入与组合冒烟测试"
```

---

## Self-Review

**1. Spec coverage (against §3 module list):**
- `models.py` → Task 1 ✓
- `excel_utils.py` → Task 2 ✓
- `validation.py` → Task 3 ✓
- `llm.py` → Task 4 ✓
- (`checkpoints`/`attachments`/`evidence_steps`/`procedure_pairs`/`findings_review`/`hallucination`/`pipeline`/`findings_store`/tool/agent/main/frontend → deferred to Plans 2-4, as scoped.)

**2. Placeholder scan:** No TBD/TODO. Every code step contains full code. The `_llm_request_json_list` references `_validate_finding_result_inline`, which is imported at module bottom — defined, not a placeholder.

**3. Type consistency:** `_validate_finding_result(obj) -> (bool, list)` used consistently; `_repair_finding_result(obj) -> dict|None`; `_llm_chat(*, llm, messages, stage, max_attempts, max_tokens) -> str` matches tests; `_FakeLLM.bind` returns an object with `ainvoke` matching `_llm_chat`'s `bound.ainvoke(lc_messages)` call. Severity enums (`P0/P1/P2`) and risk-type enums match between `models._FINDING_RESULT_SCHEMA` and `validation`'s `_VALID_*` sets.

**Notes for downstream plans:**
- `_llm_request_json_list` signature here is `(llm, system_prompt, user_prompt, stage, max_attempts)` — no `result_schema`/`schema_records` params (the reference's are dropped since validation is built-in). Downstream stage modules must call it with this signature.
- The review LLM is obtained via `get_review_llm()`; downstream stages receive an `llm` instance threaded from the pipeline.
- `LLM_CALL_STATS` is a module-level dict cleared per-run by the pipeline (Plan 3).
