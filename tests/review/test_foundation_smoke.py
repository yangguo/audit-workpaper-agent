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
