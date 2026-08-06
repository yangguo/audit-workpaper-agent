import io
import json
import pytest
import openpyxl
from fastapi.testclient import TestClient

from main import app
from review.export import generate_findings_xlsx


@pytest.fixture
def client():
    return TestClient(app)


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


def test_export_findings_returns_xlsx(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
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
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert wb.active.title == "审阅发现汇总"


def test_export_findings_missing_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    res = client.get("/findings/notexist/export?format=xlsx")
    assert res.status_code == 404


EXPECTED_HEADERS = [
    "序号", "Sheet", "单元格", "问题类型", "严重级别", "风险类型",
    "状态", "结论", "判定依据", "整改建议", "证据引用",
    "交叉校验问题", "LLM 复核状态", "LLM 复核说明", "不确定原因",
]


def test_generate_findings_xlsx_uses_exact_15_headers():
    findings = [{
        "issue_type": "占位",
        "evidence_refs": [],
    }]
    data = generate_findings_xlsx(findings)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    headers = [ws.cell(row=1, column=c).value for c in range(1, 16)]
    assert headers == EXPECTED_HEADERS


def test_generate_findings_xlsx_preserves_attachment_in_evidence_refs():
    findings = [{
        "issue_type": "附件支撑缺失",
        "evidence_refs": [{
            "sheet": "",
            "cell_or_range": "",
            "attachment": "attachments/contracts/contract-001.pdf",
            "excerpt": "合同条款摘录：付款周期…",
        }, {
            "sheet": "SA-2",
            "cell_or_range": "B7",
            "excerpt": "底稿单元格摘录",
        }],
    }]
    data = generate_findings_xlsx(findings)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    evidence_cell = ws.cell(row=2, column=11).value
    # Must preserve both refs as JSON text, including the attachment path.
    parsed = [json.loads(line) for line in evidence_cell.splitlines() if line]
    assert any(
        r.get("attachment") == "attachments/contracts/contract-001.pdf" for r in parsed
    )
    assert any(r.get("sheet") == "SA-2" and r.get("cell_or_range") == "B7" for r in parsed)
    # Chinese characters must NOT be escaped to \uXXXX.
    assert "\\u" not in evidence_cell
    assert "付款周期" in evidence_cell


def test_export_findings_empty_list_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    results_dir = tmp_path / "assets" / "results"
    results_dir.mkdir(parents=True)
    payload = {
        "review_id": "r-empty",
        "created_at": "2026-08-06T00:00:00",
        "source": "test.xlsx",
        "stats": {"total_findings": 0, "by_severity": {}},
        "findings": [],
    }
    (results_dir / "r-empty_findings.json").write_text(json.dumps(payload), encoding="utf-8")

    res = client.get("/findings/r-empty/export?format=xlsx")
    assert res.status_code == 404
