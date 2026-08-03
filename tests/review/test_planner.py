import json

import openpyxl

from review.evidence import build_evidence_graph
from review.planner import build_review_plan
from review.policy import load_policy_pack


def _workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SA-4c"
    sheet["A1"] = "标准审计程序"
    sheet["B1"] = "执行审计程序"
    sheet["A5"] = "审计期间获取系统用户清单并检查管理员权限。"
    sheet["B5"] = "我们通过访谈了解权限管理流程，未获取其他证据。"
    sheet["A6"] = "获取密码策略参数截图并检查锁定设置。"
    sheet["B6"] = "我们获取参数截图并核对锁定设置。"
    sheet["A8"] = "管理员账号识别情况"
    return workbook


def test_build_review_plan_maps_control_and_sheet_facts_to_evidence_ids():
    workbook = _workbook()
    graph = build_evidence_graph(workbook, source_sha256="a" * 64)
    pack = load_policy_pack()

    plan = build_review_plan(
        workbook,
        graph,
        pack,
        sheets="SA-4c",
        engine_version="test-engine",
    )
    payload = plan.to_dict()

    assert payload["scope"]["status"] == "ok"
    assert payload["scope"]["target_sheets"] == ["SA-4c"]
    assert any(item["fact"]["fact_type"] == "ControlFact" for item in payload["items"])
    assert any(item["fact"]["fact_type"] == "SheetFact" for item in payload["items"])
    assert all(
        evidence["evidence_id"].startswith("ev:")
        for item in payload["items"]
        for evidence in item["fact"].get("evidence", [])
    )
    json.dumps(payload, ensure_ascii=False)


def test_build_review_plan_rejects_unmatched_explicit_scope_without_fallback():
    workbook = _workbook()
    graph = build_evidence_graph(workbook, source_sha256="b" * 64)
    plan = build_review_plan(workbook, graph, load_policy_pack(), sheets="PE-6")

    assert plan.to_dict()["scope"] == {
        "requested_sheets": ["PE-6"],
        "target_sheets": [],
        "status": "scope_validation_failed",
        "unmatched": ["PE-6"],
    }
    assert plan.to_dict()["items"] == []


def test_build_review_plan_identity_is_stable_for_same_inputs():
    workbook = _workbook()
    pack = load_policy_pack()
    first = build_review_plan(
        workbook,
        build_evidence_graph(workbook, source_sha256="c" * 64),
        pack,
        sheets="SA-4c",
        engine_version="test-engine",
    ).to_dict()
    second = build_review_plan(
        workbook,
        build_evidence_graph(workbook, source_sha256="c" * 64),
        pack,
        sheets="SA-4c",
        engine_version="test-engine",
    ).to_dict()

    assert first["plan_id"] == second["plan_id"]
    assert [item["plan_item_id"] for item in first["items"]] == [
        item["plan_item_id"] for item in second["items"]
    ]
