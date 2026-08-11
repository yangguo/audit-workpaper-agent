import pytest

from review.result_quality import (
    FindingQuality,
    build_quality_envelope,
    canonicalize_evidence_refs,
    derive_primary_location,
    stable_legacy_finding_id,
)


def test_canonicalize_evidence_refs_is_stable_and_deduplicates_refs():
    refs = [
        {
            "sheet": "SA-1",
            "cell_or_range": "C5",
            "excerpt": "原文",
            "evidence_id": "cell:1",
            "content_hash": "hash-1",
        },
        {
            "content_hash": "hash-1",
            "evidence_id": "cell:1",
            "excerpt": "原文",
            "cell_or_range": "C5",
            "sheet": "SA-1",
        },
        {
            "attachment": "SA-1/evidence.pdf",
            "excerpt": "附件原文",
            "evidence_id": "attachment:1",
            "content_hash": "hash-2",
        },
    ]

    canonical = canonicalize_evidence_refs(refs)

    assert len(canonical) == 2
    assert canonical[0]["evidence_id"] == "cell:1"
    assert canonical[1]["source_kind"] == "attachment"
    assert canonical == canonicalize_evidence_refs(list(reversed(refs)))


def test_derive_primary_location_prefers_finding_cell_then_verified_refs():
    refs = [
        {
            "sheet": "SA-1",
            "cell_or_range": "C8",
            "excerpt": "cell evidence",
            "evidence_id": "cell:8",
            "content_hash": "hash-8",
        },
        {
            "attachment": "SA-1/evidence.pdf",
            "excerpt": "attachment evidence",
            "evidence_id": "attachment:1",
            "content_hash": "hash-9",
        },
    ]

    finding_location = derive_primary_location({"sheet": "SA-1", "cell": "C5"}, refs)
    assert finding_location["source_kind"] == "cell"
    assert finding_location["sheet"] == "SA-1"
    assert finding_location["cell_or_range"] == "C5"
    assert finding_location["source_ref"] == "workpaper:SA-1!C5"
    assert finding_location["evidence_id"] is None

    ref_location = derive_primary_location({"sheet": "", "cell": None}, refs)
    assert ref_location["source_kind"] == "cell"
    assert ref_location["sheet"] == "SA-1"
    assert ref_location["cell_or_range"] == "C8"
    assert ref_location["source_ref"] == "workpaper:SA-1!C8"
    assert ref_location["evidence_id"] == "cell:8"


def test_stable_legacy_finding_id_changes_when_provenance_changes():
    refs = [{"evidence_id": "cell:1", "content_hash": "hash-1"}]

    first = stable_legacy_finding_id(
        input_sha256="sha-1",
        issue_type="覆盖性",
        sheet="SA-1",
        cell="C5",
        status="fail",
        evidence_refs=refs,
        origin="checkpoint",
    )
    same = stable_legacy_finding_id(
        input_sha256="sha-1",
        issue_type="覆盖性",
        sheet="SA-1",
        cell="C5",
        status="fail",
        evidence_refs=list(refs),
        origin="checkpoint",
    )
    changed = stable_legacy_finding_id(
        input_sha256="sha-2",
        issue_type="覆盖性",
        sheet="SA-1",
        cell="C5",
        status="fail",
        evidence_refs=refs,
        origin="checkpoint",
    )

    assert first == same
    assert first.startswith("legacy:")
    assert first != changed


def test_build_quality_envelope_is_additive_and_explicit_about_gate_states():
    finding = {
        "issue_type": "覆盖性",
        "severity": "P1",
        "status": "fail",
        "sheet": "SA-1",
        "cell": None,
        "evidence_refs": [
            {
                "sheet": "SA-1",
                "cell_or_range": "C5",
                "excerpt": "原文",
                "evidence_id": "cell:1",
                "content_hash": "hash-1",
            }
        ],
        "origin": "checkpoint",
    }

    quality = build_quality_envelope(
        finding,
        input_sha256="sha-1",
        engine_version="engine-1",
        gates={
            "deterministic_cross_check": {
                "status": "passed",
                "issues": [],
            },
            "model_re_review": {
                "status": "not_run",
                "reason": "same-model finding",
            },
        },
        verified_refs=finding["evidence_refs"],
    )

    assert quality["schema_version"] == "review-quality/1"
    assert quality["finding_id"].startswith("legacy:")
    assert quality["primary_location"]["cell_or_range"] == "C5"
    assert quality["citation_validation"]["status"] == "verified"
    assert quality["citation_validation"]["verified_count"] == 1
    assert quality["citation_validation"]["rejected_count"] == 0
    assert quality["citation_validation"]["rejection_codes"] == []
    assert quality["citation_validation"]["evidence_ids"] == ["cell:1"]
    assert quality["citation_validation"]["verified_refs"][0]["evidence_id"] == "cell:1"
    assert quality["gates"]["model_re_review"]["status"] == "not_run"


def test_finding_quality_rejects_unknown_gate_status():
    with pytest.raises(ValueError):
        FindingQuality(
            finding_id="legacy:test",
            gates={"deterministic_cross_check": {"status": "maybe"}},
        )
