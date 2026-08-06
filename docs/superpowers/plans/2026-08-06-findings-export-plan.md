# 检查结果报告导出功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为审阅结果增加导出 Excel 报告功能，用户可在前端一键下载包含全部发现点的 `.xlsx` 文件。

**Architecture:** 后端新增 `src/review/export.py` 用 `openpyxl` 将 findings JSON 渲染为 Excel 字节流；`src/main.py` 增加 `GET /findings/{review_id}/export?format=xlsx` 端点。前端将 `reviewId` 从 Stream context 经 view-model 传递到 `AnalysisResultPanel`，在面板右上角渲染导出按钮，点击后通过浏览器触发下载。

**Tech Stack:** Python 3.12, FastAPI, openpyxl, React/TypeScript/Next.js, Tailwind CSS, shadcn/ui Button, sonner toast.

## Global Constraints

- 后端生成 `.xlsx`，前端通过 GET 请求下载。
- 报告包含全部发现点的完整字段。
- 导出入口位于「分析结果」面板右上角。
- review_id 不存在或 findings 为空时返回 404。
- 使用项目已有的 `openpyxl`，前端不新增 Excel 生成依赖。

---

### Task 1: Backend Excel generator

**Files:**
- Create: `src/review/export.py`
- Test: `tests/review/test_export.py`

**Interfaces:**
- Consumes: `List[Dict[str, Any]]` (findings array from `load_findings`)
- Produces: `generate_findings_xlsx(findings: List[Dict[str, Any]]) -> bytes`

- [ ] **Step 1: Write the failing test**

```python
import io
import pytest
import openpyxl
from review.export import generate_findings_xlsx


def test_generate_findings_xlsx_includes_all_columns():
    findings = [{
        "issue_type": "问题A",
        "severity": "P0",
        "severity_display": "高",
        "sheet": "SA-1",
        "cell": "C5",
        "risk_type": "一致性",
        "status": "fail",
        "conclusion": "结论",
        "basis": "依据",
        "suggestion": "建议",
        "evidence_refs": [{"sheet": "SA-1", "cell_or_range": "C5", "excerpt": "原文"}],
        "cross_validate_issues": ["矛盾1"],
        "llm_status": "pass",
        "llm_comment": "复核说明",
        "unknown_reason": "",
    }]
    data = generate_findings_xlsx(findings)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws.title == "审阅发现汇总"
    headers = [ws.cell(row=1, column=c).value for c in range(1, 16)]
    assert headers[0] == "序号"
    assert headers[3] == "问题类型"
    assert ws.cell(row=2, column=4).value == "问题A"
    assert ws.cell(row=2, column=5).value == "P0 / 高"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_export.py::test_generate_findings_xlsx_includes_all_columns -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'review.export'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Export review findings to structured report formats."""
import io
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def generate_findings_xlsx(findings: List[Dict[str, Any]]) -> bytes:
    """Render a list of findings into an .xlsx workbook and return its bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "审阅发现汇总"

    headers = [
        "序号", "Sheet", "单元格", "问题类型", "严重级别", "风险类型",
        "状态", "结论", "判定依据", "整改建议", "证据引用",
        "交叉校验问题", "LLM 复核状态", "LLM 复核说明", "不确定原因",
    ]

    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    header_font = Font(bold=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    widths = [6, 12, 12, 35, 12, 12, 10, 35, 45, 45, 45, 30, 15, 30, 30]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    for idx, finding in enumerate(findings, start=1):
        row = idx + 1
        severity = finding.get("severity", "")
        severity_display = finding.get("severity_display", "")
        severity_str = f"{severity} / {severity_display}" if severity_display else severity

        conclusion = finding.get("llm_conclusion") or finding.get("conclusion") or ""

        evidence_refs = finding.get("evidence_refs", [])
        if isinstance(evidence_refs, list):
            evidence_str = "\n".join(
                f"{ref.get('sheet', '')}!{ref.get('cell_or_range', '')}: {ref.get('excerpt', '')[:200]}"
                for ref in evidence_refs
            )
        else:
            evidence_str = str(evidence_refs)

        cross_issues = finding.get("cross_validate_issues", [])
        if isinstance(cross_issues, list):
            cross_str = "；".join(cross_issues)
        else:
            cross_str = str(cross_issues)

        values = [
            idx,
            finding.get("sheet", ""),
            finding.get("cell", ""),
            finding.get("issue_type", ""),
            severity_str,
            finding.get("risk_type", ""),
            finding.get("status", ""),
            conclusion,
            finding.get("basis", ""),
            finding.get("suggestion", ""),
            evidence_str,
            cross_str,
            finding.get("llm_status", ""),
            finding.get("llm_comment", ""),
            finding.get("unknown_reason", ""),
        ]

        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = "A2"

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_export.py::test_generate_findings_xlsx_includes_all_columns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/review/export.py tests/review/test_export.py
git commit -m "feat(review): add findings Excel generator

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Backend export endpoint

**Files:**
- Modify: `src/main.py` (near existing `/findings/{review_id}` endpoint)

**Interfaces:**
- Consumes: `review_id: str`, `format: str = "xlsx"`
- Produces: `StreamingResponse` with Excel bytes

- [ ] **Step 1: Write the failing test**

```python
import io

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_export_findings_returns_xlsx(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    import json
    results_dir = tmp_path / "assets" / "results"
    results_dir.mkdir(parents=True)
    payload = {
        "review_id": "r123",
        "created_at": "2026-08-06T00:00:00",
        "source": "test.xlsx",
        "stats": {"total_findings": 1, "by_severity": {"P0": 1}},
        "findings": [{
            "issue_type": "问题A", "severity": "P0", "severity_display": "高",
            "sheet": "SA-1", "cell": "C5", "risk_type": "一致性", "status": "fail",
            "conclusion": "结论", "basis": "依据", "suggestion": "建议",
            "evidence_refs": [], "cross_validate_issues": [],
        }],
    }
    (results_dir / "r123_findings.json").write_text(json.dumps(payload), encoding="utf-8")

    res = client.get("/findings/r123/export?format=xlsx")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "findings_r123.xlsx" in res.headers["content-disposition"]
    # Should be a valid xlsx
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert wb.active.title == "审阅发现汇总"


def test_export_findings_missing_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    res = client.get("/findings/notexist/export?format=xlsx")
    assert res.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_export_endpoint.py -v` (or add to `tests/review/test_export.py`)
Expected: FAIL with 404 because route not registered.

- [ ] **Step 3: Write minimal implementation**

In `src/main.py`, after the existing `/findings/{review_id}` endpoint, add:

```python
import io

from fastapi import Query
from fastapi.responses import StreamingResponse
from review.export import generate_findings_xlsx


@app.get("/findings/{review_id}/export")
async def export_findings(review_id: str, format: str = Query("xlsx")):
    """Export review findings as an Excel report."""
    payload = load_findings(review_id)
    if not payload or not payload.get("findings"):
        raise HTTPException(status_code=404, detail="findings not found or empty")
    if format != "xlsx":
        raise HTTPException(status_code=400, detail="unsupported format")

    xlsx_bytes = generate_findings_xlsx(payload["findings"])
    filename = f"findings_{review_id}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/review/test_export.py
git commit -m "feat(api): add GET /findings/{review_id}/export endpoint

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Frontend view-model exposes reviewId

**Files:**
- Modify: `frontend/components/workbench/types.ts`
- Modify: `frontend/components/workbench/view-model.ts`
- Test: `frontend/components/workbench/__tests__/view-model.test.ts`

**Interfaces:**
- Consumes: `input.findings?.review_id`
- Produces: `WorkbenchViewModel.reviewId: string | undefined`

- [ ] **Step 1: Write the failing test**

In `frontend/components/workbench/__tests__/view-model.test.ts`, add:

```typescript
it("exposes reviewId from findings payload", () => {
  const input = buildInput({
    findings: {
      review_id: "r123",
      created_at: "",
      source: "test.xlsx",
      stats: {
        total_findings: 1,
        by_severity: { P0: 1, P1: 0, P2: 0 },
        by_status: {},
        by_risk_type: {},
        llm_call_stats: {},
        evidence_agent: {} as any,
        warning: "",
      },
      findings: [{
        issue_type: "问题", severity: "P0", sheet: "SA-1", cell: "C5",
        snippet: "", basis: "", suggestion: "", status: "fail", risk_type: "一致性",
      }],
    },
  });
  const model = buildWorkbenchViewModel(input);
  expect(model.reviewId).toBe("r123");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run`
Expected: FAIL with `Property 'reviewId' does not exist on type 'WorkbenchViewModel'`

- [ ] **Step 3: Write minimal implementation**

In `frontend/components/workbench/types.ts`, add to `WorkbenchViewModel`:

```typescript
export type WorkbenchViewModel = {
  // ... existing fields ...
  reviewId?: string;
};
```

In `frontend/components/workbench/view-model.ts`, in `buildWorkbenchViewModel`:

```typescript
const reviewId = input.findings?.review_id;
```

And return it:

```typescript
return {
  // ... existing fields ...
  reviewId,
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --run`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/workbench/types.ts frontend/components/workbench/view-model.ts frontend/components/workbench/__tests__/view-model.test.ts
git commit -m "feat(frontend): expose reviewId in workbench view model

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Frontend export button

**Files:**
- Modify: `frontend/components/workbench/AnalysisResultPanel.tsx`
- Modify: `frontend/components/workbench/WorkbenchShell.tsx`
- Modify: `frontend/components/thread/index.tsx`
- Test: `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`

**Interfaces:**
- Consumes: `reviewId?: string` from `WorkbenchShell`, passed to `AnalysisResultPanel`
- Produces: Click triggers download of `/findings/{reviewId}/export?format=xlsx`

- [ ] **Step 1: Write the failing test**

In `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`, add a test that renders `WorkbenchShell` with `reviewId="r123"` and checks for "导出 Excel 报告" button.

```typescript
it("renders export button when reviewId is provided", () => {
  render(
    <WorkbenchShell
      header={{ title: "审计底稿审阅", subtitle: "测试", statusLabel: "已完成" }}
      summaryMetrics={[]}
      analysisSections={[]}
      evidenceItems={[]}
      progressSteps={[]}
      toolTraces={[]}
      reviewId="r123"
      isEmpty={false}
    />,
  );
  expect(screen.getByText("导出 Excel 报告")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run`
Expected: FAIL with `Unable to find an element with the text: 导出 Excel 报告`

- [ ] **Step 3: Write minimal implementation**

In `frontend/components/workbench/AnalysisResultPanel.tsx`, update the component signature and header:

```typescript
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";

export function AnalysisResultPanel({
  sections,
  runningMessage,
  errorMessage,
  reviewId,
}: {
  sections: AnalysisSection[];
  runningMessage?: string;
  errorMessage?: string;
  reviewId?: string;
}) {
  const [exporting, setExporting] = useState(false);

  const handleExport = () => {
    if (!reviewId) return;
    setExporting(true);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000";
      const url = `${backendUrl}/findings/${reviewId}/export?format=xlsx`;
      const a = document.createElement("a");
      a.href = url;
      a.download = `findings_${reviewId}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="rounded-2xl border bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">分析结果</h2>
        {reviewId ? (
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={exporting}
          >
            <Download className="mr-1 size-4" />
            导出 Excel 报告
          </Button>
        ) : null}
      </div>
      {/* rest unchanged */}
    </section>
  );
}
```

Add `useState` import from React if not present.

In `frontend/components/workbench/WorkbenchShell.tsx`, add `reviewId?: string` to props and pass to `AnalysisResultPanel`:

```typescript
export function WorkbenchShell(props: {
  // ... existing props ...
  reviewId?: string;
}) {
  // ...
  <AnalysisResultPanel
    sections={props.analysisSections}
    runningMessage={props.runningMessage}
    errorMessage={props.errorMessage}
    reviewId={props.reviewId}
  />
  // ...
}
```

In `frontend/components/thread/index.tsx`, pass `reviewId={model.reviewId}` to `WorkbenchShell`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --run`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/workbench/AnalysisResultPanel.tsx frontend/components/workbench/WorkbenchShell.tsx frontend/components/thread/index.tsx frontend/components/workbench/__tests__/WorkbenchShell.test.tsx
git commit -m "feat(frontend): add findings export button in analysis panel

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Integration smoke test and final verification

**Files:**
- None new; verify whole flow.

- [ ] **Step 1: Start backend and frontend**

Backend:
```bash
bash scripts/http_run.sh -p 5000
```

Frontend:
```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Run a review and click export**

Open http://localhost:3000, upload a workbook, run review. Once results appear, click「导出 Excel 报告」，确认浏览器下载的 `.xlsx` 文件内容正确。

- [ ] **Step 3: Run full test suites**

Backend:
```bash
.venv/Scripts/python.exe -m pytest tests/review/ -v
```

Frontend:
```bash
cd frontend && npm run test -- --run
```

- [ ] **Step 4: Commit any final fixes**

If smoke test reveals issues, fix and commit separately.

---

## Self-Review

**Spec coverage:**
- Excel format export → Task 1 + Task 2.
- All findings complete fields → Task 1 column list.
- Export button in analysis result panel top-right → Task 4.
- 404 for missing/empty findings → Task 2 test.
- Backend/frontend tests → Tasks 1-4.

**Placeholder scan:** No TBD/TODO; all code snippets concrete.

**Type consistency:** `reviewId` is `string | undefined` throughout; `generate_findings_xlsx` returns `bytes`; endpoint returns `StreamingResponse`.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-findings-export-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
