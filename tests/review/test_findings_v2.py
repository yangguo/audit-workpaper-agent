from review.findings import build_v2_findings, project_v2_finding_to_v1
from review.judgement import (
    EvidenceSnippet,
    JudgementExecution,
    JudgementRequest,
)
from review.policy import load_policy_pack


def _request():
    return JudgementRequest(
        request_id="request:1",
        source_sha256="a" * 64,
        rule_id="itgc.judgement.procedure_correspondence",
        rule_version="1.0.0",
        evaluator_id="judgement.procedure_correspondence",
        question="执行程序是否满足标准程序？",
        allowed_decisions=["supported", "contradicted", "insufficient"],
        fact={
            "fact_type": "ControlFact",
            "sheet": "SA-4c",
            "execution_cell": "B5",
            "standard_text": "标准程序",
            "execution_text": "执行程序",
        },
        evidence=[
            EvidenceSnippet(
                evidence_id="ev:1",
                source_kind="workbook",
                source_ref="SA-4c!B5",
                sheet="SA-4c",
                cell_or_range="B5",
                quote="执行程序",
                content_hash="hash-1",
            )
        ],
        expected_evidence_types=["执行程序"],
        review_scope={"target_sheets": ["SA-4c"]},
    )


def _execution(decision, verification_status):
    return JudgementExecution(
        request_id="request:1",
        rule_id="itgc.judgement.procedure_correspondence",
        rule_version="1.0.0",
        decision=decision,
        conclusion="结论文本",
        evidence_refs_v2=[
            {
                "evidence_id": "ev:1",
                "sheet": "SA-4c",
                "cell_or_range": "B5",
                "quote": "执行程序",
                "start_offset": 0,
                "end_offset": 4,
                "content_hash": "hash-1",
                "role": "supporting",
            }
        ],
        verification_status=verification_status,
        unknown_reason="缺少可验证信息" if decision == "insufficient" else "",
        reasoning_summary=["理由"],
        errors=["quote_mismatch"] if verification_status == "invalid" else [],
    )


def test_build_v2_findings_maps_decisions_and_has_stable_identity():
    request = _request()
    execution = _execution("contradicted", "contradicted")
    pack = load_policy_pack(pack_id="itgc-judgement", version="1.0.0")

    first = build_v2_findings(
        requests=[request],
        executions=[execution],
        policy_pack=pack,
        engine_version="test-engine",
    )
    second = build_v2_findings(
        requests=[request],
        executions=[execution],
        policy_pack=pack,
        engine_version="test-engine",
    )

    assert first[0]["status"] == "fail"
    assert first[0]["verification_status"] == "contradicted"
    assert first[0]["identity_key"] == second[0]["identity_key"]
    assert first[0]["rule_id"] == request.rule_id


def test_invalid_or_insufficient_judgement_projects_to_unknown():
    request = _request()
    execution = _execution("insufficient", "invalid")
    execution = execution.model_copy(
        update={"evidence_refs_v2": [], "unknown_reason": "引用无法通过精确验证。"}
    )
    pack = load_policy_pack(pack_id="itgc-judgement", version="1.0.0")

    finding = build_v2_findings(
        requests=[request],
        executions=[execution],
        policy_pack=pack,
        engine_version="test-engine",
    )[0]

    assert finding["status"] == "unknown"
    projected = project_v2_finding_to_v1(finding)
    assert projected["status"] == "unknown"
    assert projected["sheet"] == "SA-4c"
    assert projected["evidence_refs"] == []
