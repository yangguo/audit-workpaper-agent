import json

import pytest

from review.finding_taxonomy import load_assertion_catalog
from review.remediation_catalog import (
    RemediationCatalogError,
    load_remediation_catalog,
    validate_remediation_bindings,
)
from review.remediation import build_remediation


def _assertion(
    assertion_id: str = "configuration.asset_coverage.support",
    *,
    template_id: str = "configuration_asset_coverage",
):
    return {
        "assertion_id": assertion_id,
        "version": "1.0.0",
        "claim_type": "configuration_value",
        "allowed_origins": ["configuration"],
        "requires_attachment_support": True,
        "exclusive_claim": False,
        "deterministic_gate_ids": [],
        "remediation_template_id": template_id,
        "root_family": "configuration_coverage",
    }


def _unclassified_assertion():
    return {
        "assertion_id": "finding.unclassified",
        "version": "1.0.0",
        "claim_type": "workpaper_text",
        "allowed_origins": ["legacy"],
        "requires_attachment_support": False,
        "exclusive_claim": False,
        "deterministic_gate_ids": [],
        "remediation_template_id": "human_refinement",
        "root_family": "",
    }


def _template(
    template_id: str = "configuration_asset_coverage",
    *,
    assertion_ids: list[str] | None = None,
):
    return {
        "template_id": template_id,
        "assertion_ids": assertion_ids
        or ["configuration.asset_coverage.support"],
        "action": "补充防病毒资产范围、策略配置与覆盖结果的核验记录，并处置未覆盖资产。",
        "required_evidence": ["受管资产范围清单", "防病毒策略配置导出"],
        "acceptance_criteria": ["资产范围、策略配置和覆盖结果已完成勾稽"],
    }


def _write_pack(tmp_path, assertions, templates):
    pack_root = tmp_path / "review-quality" / "1.0.0"
    pack_root.mkdir(parents=True, exist_ok=True)
    (pack_root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "review-quality",
                "version": "1.0.0",
                "title": "Review quality assertions",
                "assertions_file": "assertions.json",
                "remediation_templates_file": "remediation-templates.json",
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
    (pack_root / "remediation-templates.json").write_text(
        json.dumps(
            {
                "id": "review-quality",
                "version": "1.0.0",
                "templates": templates,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_loader_rejects_duplicate_template_ids(tmp_path):
    _write_pack(
        tmp_path,
        [_unclassified_assertion(), _assertion()],
        [_template(), _template()],
    )

    with pytest.raises(RemediationCatalogError, match="duplicate template_id"):
        load_remediation_catalog(root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", ""),
        ("required_evidence", []),
        ("acceptance_criteria", []),
    ],
)
def test_loader_rejects_incomplete_template_fields(tmp_path, field, value):
    template = _template()
    template[field] = value
    _write_pack(tmp_path, [_unclassified_assertion(), _assertion()], [template])

    with pytest.raises(RemediationCatalogError, match="invalid remediation catalog"):
        load_remediation_catalog(root=tmp_path)


def test_bindings_reject_unknown_assertion_and_multiple_template_claims(tmp_path):
    _write_pack(
        tmp_path,
        [_unclassified_assertion(), _assertion()],
        [
            _template(assertion_ids=["missing.assertion"]),
            _template(
                "duplicate_template",
                assertion_ids=["configuration.asset_coverage.support"],
            ),
        ],
    )

    assertions = load_assertion_catalog(root=tmp_path)
    remediation = load_remediation_catalog(root=tmp_path)

    with pytest.raises(RemediationCatalogError, match="unknown assertion"):
        validate_remediation_bindings(assertions, remediation)


def test_bindings_reject_same_assertion_in_multiple_templates(tmp_path):
    _write_pack(
        tmp_path,
        [_unclassified_assertion(), _assertion()],
        [
            _template(),
            _template(
                "duplicate_template",
                assertion_ids=["configuration.asset_coverage.support"],
            ),
        ],
    )

    assertions = load_assertion_catalog(root=tmp_path)
    remediation = load_remediation_catalog(root=tmp_path)

    with pytest.raises(RemediationCatalogError, match="multiple remediation templates"):
        validate_remediation_bindings(assertions, remediation)


def test_antivirus_assertion_cannot_use_access_reconciliation_template():
    remediation = build_remediation(
        {
            "assertion_id": "configuration.asset_coverage.support",
            "suggestion": "请补充权限清查和离职权限复核记录",
        },
        catalog=load_remediation_catalog(),
    )

    assert remediation["status"] == "actionable"
    assert "权限清查" not in remediation["action"]
    assert "账号权限" not in remediation["action"]
    assert "离职权限" not in remediation["action"]
    assert remediation["required_evidence"]
    assert remediation["acceptance_criteria"]


def test_unknown_assertion_requires_human_refinement_without_risk_fallback():
    remediation = build_remediation(
        {
            "assertion_id": "finding.unclassified",
            "risk_type": "覆盖性",
            "suggestion": "建议补充完整证据",
        },
        catalog=load_remediation_catalog(),
    )

    assert remediation["status"] == "needs_human_refinement"
    assert "trusted_template" in remediation["missing_fields"]
    assert remediation["required_evidence"] == []
    assert remediation["acceptance_criteria"] == []
