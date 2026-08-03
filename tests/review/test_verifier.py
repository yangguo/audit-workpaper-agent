import pytest

from review.judgement import EvidenceSnippet, JudgementRequest, JudgementResponse
from review.verifier import verify_judgement_response


def _request():
    evidence = EvidenceSnippet(
        evidence_id="ev:1",
        source_kind="workbook",
        source_ref="SA-4c!B5",
        sheet="SA-4c",
        cell_or_range="B5",
        quote="获取用户清单截图并核对管理员权限。",
        content_hash="hash-1",
    )
    return JudgementRequest(
        request_id="request:1",
        source_sha256="a" * 64,
        rule_id="itgc.judgement.procedure_correspondence",
        rule_version="1.0.0",
        evaluator_id="judgement.procedure_correspondence",
        question="执行程序是否满足标准程序？",
        allowed_decisions=["supported", "contradicted", "insufficient"],
        fact={"fact_type": "ControlFact", "sheet": "SA-4c"},
        evidence=[evidence],
        expected_evidence_types=["执行程序"],
    )


def test_verifier_accepts_exact_quote_offset_and_hash():
    request = _request()
    response = JudgementResponse(
        decision="contradicted",
        conclusion="执行程序未覆盖标准要求。",
        evidence_refs=[
            {
                "evidence_id": "ev:1",
                "quote": "获取用户清单截图",
                "start_offset": 0,
                "end_offset": 8,
                "content_hash": "hash-1",
                "role": "supporting",
            }
        ],
        reasoning_summary=["证据支持该判断"],
    )

    result = verify_judgement_response(request, response)

    assert result.verification_status == "contradicted"
    assert result.errors == []
    assert result.evidence_refs_v2[0]["evidence_id"] == "ev:1"


@pytest.mark.parametrize(
    "override, expected_error",
    [
        ({"evidence_id": "ev:missing"}, "evidence_id_not_allowed"),
        ({"quote": "编造内容"}, "quote_mismatch"),
        ({"start_offset": 2, "end_offset": 8}, "quote_mismatch"),
        ({"content_hash": "wrong"}, "content_hash_mismatch"),
    ],
)
def test_verifier_rejects_untrusted_or_inexact_references(override, expected_error):
    request = _request()
    reference = {
        "evidence_id": "ev:1",
        "quote": "获取用户清单截图",
        "start_offset": 0,
        "end_offset": 8,
        "content_hash": "hash-1",
        "role": "supporting",
    }
    reference.update(override)
    response = JudgementResponse(
        decision="contradicted",
        conclusion="执行程序未覆盖标准要求。",
        evidence_refs=[reference],
    )

    result = verify_judgement_response(request, response)

    assert result.verification_status == "invalid"
    assert expected_error in result.errors


def test_verifier_accepts_insufficient_with_reason_without_evidence():
    request = _request()
    response = JudgementResponse(
        decision="insufficient",
        conclusion="现有资料不足以判断。",
        evidence_refs=[],
        unknown_reason="缺少可检索的原始执行证据，无法完成核验。",
    )

    result = verify_judgement_response(request, response)

    assert result.verification_status == "insufficient"
    assert result.errors == []


def test_judgement_response_rejects_insufficient_without_reason():
    with pytest.raises(ValueError, match="unknown_reason"):
        JudgementResponse(
            decision="insufficient",
            conclusion="现有资料不足以判断。",
            evidence_refs=[],
        )
