import openpyxl

from review.evaluators import execute_policy_plan
from review.evidence import build_evidence_graph
from review.planner import build_review_plan
from review.policy import load_policy_pack


def _plan(execution_text="我们通过访谈了解权限管理流程，未获取其他证据。"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SA-4c"
    sheet["A1"] = "标准审计程序"
    sheet["B1"] = "执行审计程序"
    sheet["A5"] = "审计期间获取系统用户清单并检查管理员权限。"
    sheet["B5"] = execution_text
    sheet["A8"] = "管理员账号识别情况"
    graph = build_evidence_graph(workbook, source_sha256="d" * 64)
    return build_review_plan(workbook, graph, load_policy_pack(), sheets="SA-4c")


def test_execute_policy_plan_emits_three_rule_candidates_with_verified_refs():
    result = execute_policy_plan(_plan())

    assert result["stats"]["candidates"] >= 3
    rule_ids = {finding["rule_id"] for finding in result["findings"]}
    assert "itgc.procedure.interview_only" in rule_ids
    assert "itgc.procedure.required_evidence" in rule_ids
    assert "itgc.scope.os_db_admin" in rule_ids
    for finding in result["findings"]:
        assert finding["verification_status"] == "supported"
        assert finding["evidence_refs_v2"]
        ref = finding["evidence_refs_v2"][0]
        assert ref["evidence_id"].startswith("ev:")
        assert ref["quote"]
        assert ref["end_offset"] == len(ref["quote"])
        assert ref["content_hash"]


def test_execute_policy_plan_does_not_flag_supported_execution():
    result = execute_policy_plan(
        _plan("我们导出用户清单并获取参数截图，核对管理员权限。")
    )

    assert {
        finding["rule_id"] for finding in result["findings"]
    } == {"itgc.scope.os_db_admin"}


def test_execute_policy_plan_deduplicates_same_identity_key():
    plan = _plan()
    payload = plan.to_dict()
    payload["items"].append(payload["items"][0])

    result = execute_policy_plan(payload)
    identity_keys = [finding["identity_key"] for finding in result["findings"]]

    assert len(identity_keys) == len(set(identity_keys))
    assert result["stats"]["deduplicated"] >= 1
