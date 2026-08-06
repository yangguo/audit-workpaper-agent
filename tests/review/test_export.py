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
