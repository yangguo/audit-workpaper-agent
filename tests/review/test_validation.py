from review.validation import (
    _excerpt_matches,
    _validate_finding_result,
    _repair_finding_result,
    _validate_llm_results,
    _verify_evidence_refs,
)


_EXCERPT_MARKER = "[非逐字原文]"


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
        "evidence_refs": [{"cell_or_range": "A1", "excerpt": "摘录"}],
    })
    # with evidence_refs present, fail is not downgraded
    assert repaired["status"] == "fail"
    assert repaired["severity"] == "P0"


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
