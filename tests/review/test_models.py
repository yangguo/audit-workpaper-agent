from review.models import (
    Finding,
    AttachmentPreviewItem,
    _SEVERITY_DISPLAY,
    _SEVERITY_FROM_CHINESE,
    _EXCERPT_MAX_LEN,
    _EXCERPT_CONSTRUCTED_MARKER,
    _FINDING_RESULT_SCHEMA,
)


def test_severity_display_maps_p_codes_to_chinese():
    assert _SEVERITY_DISPLAY["P0"] == "高"
    assert _SEVERITY_DISPLAY["P1"] == "中"
    assert _SEVERITY_DISPLAY["P2"] == "低"


def test_severity_from_chinese_round_trips():
    assert _SEVERITY_FROM_CHINESE["高"] == "P0"
    assert _SEVERITY_FROM_CHINESE["中"] == "P1"
    assert _SEVERITY_FROM_CHINESE["低"] == "P2"


def test_excerpt_constants():
    assert _EXCERPT_MAX_LEN == 2000
    assert _EXCERPT_CONSTRUCTED_MARKER == "[非逐字原文]"


def test_finding_defaults_are_backward_compatible():
    f = Finding(
        issue_type="t",
        severity="P1",
        sheet="SA-1",
        cell=None,
        snippet="s",
        basis="b",
        suggestion="sug",
    )
    assert f.status == "fail"
    assert f.risk_type == ""
    assert f.evidence_refs == "[]"
    assert f.conclusion == ""
    assert f.reasons == "[]"
    assert f.fix_suggestion_detail == "{}"
    assert f.unknown_reason == ""
    assert f.needs_review is False
    assert f.assertion_id == ""
    assert f.claim_type == ""
    assert f.claim_subject == ""
    assert f.claim_value == ""


def test_finding_is_frozen():
    import pytest
    f = Finding(issue_type="t", severity="P1", sheet="SA-1", cell=None,
                snippet="s", basis="b", suggestion="sug")
    with pytest.raises(Exception):
        f.status = "pass"  # type: ignore[misc]


def test_finding_result_schema_required_fields():
    required = _FINDING_RESULT_SCHEMA["required"]
    assert required == ["status", "conclusion", "evidence_refs"]
    assert _FINDING_RESULT_SCHEMA["properties"]["assertion_id"]["type"] == "string"
    assert _FINDING_RESULT_SCHEMA["properties"]["claim_type"]["type"] == "string"


def test_attachment_preview_item_fields():
    item = AttachmentPreviewItem(
        index="1", rel_dir="d", filename="f.png", rel_path="d/f.png",
        file_type="png", description="desc", status="OK",
    )
    assert item.filename == "f.png"
    assert item.status == "OK"
