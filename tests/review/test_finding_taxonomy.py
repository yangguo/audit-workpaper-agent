import json

import pytest


def _write_catalog(root, assertions):
    pack_root = root / "review-quality" / "1.0.0"
    pack_root.mkdir(parents=True, exist_ok=True)
    (pack_root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "review-quality",
                "version": "1.0.0",
                "title": "Review quality assertions",
                "assertions_file": "assertions.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pack_root / "assertions.json").write_text(
        json.dumps(
            {
                "id": "review-quality",
                "version": "1.0.0",
                "assertions": assertions,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _assertion(assertion_id="attachment.reference.mapping"):
    return {
        "assertion_id": assertion_id,
        "version": "1.0.0",
        "claim_type": "attachment_presence",
        "allowed_origins": ["checkpoint"],
        "requires_attachment_support": True,
        "exclusive_claim": True,
        "deterministic_gate_ids": ["attachment_inventory_consistent"],
        "remediation_template_id": "attachment-reference-mapping",
    }


def test_default_catalog_is_versioned_and_exposes_controlled_assertions():
    from review.finding_taxonomy import load_assertion_catalog

    catalog = load_assertion_catalog()

    assert catalog.id == "review-quality"
    assert catalog.version == "1.0.0"
    assert catalog.assertion("attachment.reference.mapping").claim_type == "attachment_presence"
    assert catalog.assertion("record.period_date.consistency").exclusive_claim is True


def test_catalog_rejects_duplicate_assertion_ids_and_unknown_fields(tmp_path):
    from review.finding_taxonomy import AssertionCatalogError, load_assertion_catalog

    duplicate = [_assertion(), _assertion()]
    _write_catalog(tmp_path, duplicate)
    with pytest.raises(AssertionCatalogError, match="duplicate assertion_id"):
        load_assertion_catalog(root=tmp_path)

    invalid = [_assertion("record.period_date.consistency")]
    invalid[0]["unexpected"] = "value"
    _write_catalog(tmp_path, invalid)
    with pytest.raises(AssertionCatalogError, match="invalid assertion catalog"):
        load_assertion_catalog(root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim_type", "free_text_guess"),
        ("deterministic_gate_ids", ["not a controlled id"]),
        ("remediation_template_id", "not a controlled id"),
    ],
)
def test_catalog_rejects_unsafe_assertion_fields(tmp_path, field, value):
    from review.finding_taxonomy import AssertionCatalogError, load_assertion_catalog

    invalid = _assertion()
    invalid[field] = value
    _write_catalog(tmp_path, [invalid])

    with pytest.raises(AssertionCatalogError, match="invalid assertion catalog"):
        load_assertion_catalog(root=tmp_path)


def test_catalog_rejects_unsafe_version_and_directory_escape(tmp_path):
    from review.finding_taxonomy import AssertionCatalogError, load_assertion_catalog

    _write_catalog(tmp_path, [_assertion()])
    manifest = tmp_path / "review-quality" / "1.0.0" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "review-quality",
                "version": "invalid",
                "title": "Review quality assertions",
                "assertions_file": "assertions.json",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionCatalogError, match="invalid assertion catalog manifest"):
        load_assertion_catalog(root=tmp_path)
    with pytest.raises(AssertionCatalogError, match="unsafe assertion catalog"):
        load_assertion_catalog(pack_id="../escape", root=tmp_path)


def test_classification_uses_origin_rule_mapping_not_issue_text_similarity():
    from review.finding_taxonomy import classify_finding, load_assertion_catalog

    catalog = load_assertion_catalog()
    evidence_number = classify_finding(
        {
            "origin": "checkpoint",
            "rule_hint": "evidence_number_mismatch",
            "issue_type": "记录中存在不一致",
            "sheet": "SA-11",
            "cell": "C5",
            "status": "fail",
        },
        catalog,
    )
    record_date = classify_finding(
        {
            "origin": "checkpoint",
            "rule_hint": "record_date_mismatch",
            "issue_type": "记录中存在不一致",
            "sheet": "SA-11",
            "cell": "C5",
            "status": "fail",
        },
        catalog,
    )

    assert evidence_number["assertion_id"] == "attachment.reference.mapping"
    assert record_date["assertion_id"] == "record.period_date.consistency"
    assert evidence_number["assertion_id"] != record_date["assertion_id"]


def test_unknown_llm_assertion_becomes_explicitly_unclassified():
    from review.finding_taxonomy import classify_finding, load_assertion_catalog

    classified = classify_finding(
        {
            "origin": "llm",
            "assertion_id": "invented.from.free.text",
            "issue_type": "LLM判定：疑似问题",
            "sheet": "SA-11",
            "cell": "C5",
            "status": "fail",
        },
        load_assertion_catalog(),
    )

    assert classified["assertion_id"] == "finding.unclassified"
    assert classified["needs_review"] is True
    assert classified["claim_type"] == "workpaper_text"


def test_llm_response_fields_accept_only_the_catalog_whitelist():
    from review.finding_taxonomy import (
        allowed_assertion_ids,
        load_assertion_catalog,
        validated_llm_assertion_fields,
    )

    catalog = load_assertion_catalog()
    assert allowed_assertion_ids(catalog, origin="llm") == ["finding.unclassified"]
    fields = validated_llm_assertion_fields(
        sheet="SA-11",
        cell="C5",
        supplied_assertion_id="attachment.reference.mapping",
        catalog=catalog,
    )

    assert fields["origin"] == "llm"
    assert fields["assertion_id"] == "finding.unclassified"
    assert fields["needs_review"] is True
