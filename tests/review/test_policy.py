import json
from pathlib import Path

import pytest

from review.policy import PolicyPackError, load_policy_pack


_RULES = [
    {
        "rule_id": "itgc.procedure.required_evidence",
        "version": "1.0.0",
        "title": "标准要求证据但执行未体现",
        "evaluator_id": "procedure.required_evidence",
        "applies_to": {"fact_type": "ControlFact"},
        "severity": "P1",
        "risk_type": "证据不足",
        "required_evidence_types": ["截图", "导出清单"],
        "remediation_template": "补充可复核的原始证据。",
        "enabled": True,
    },
    {
        "rule_id": "itgc.procedure.interview_only",
        "version": "1.0.0",
        "title": "仅访谈且缺少实质性证据",
        "evaluator_id": "procedure.interview_only",
        "applies_to": {"fact_type": "ControlFact"},
        "severity": "P1",
        "risk_type": "证据不足",
        "required_evidence_types": ["截图", "导出清单"],
        "remediation_template": "补充可复核的原始证据。",
        "enabled": True,
    },
]


def _write_pack(root: Path, *, rules=None, manifest_overrides=None):
    pack_root = root / "itgc-core" / "1.0.0"
    rules_root = pack_root / "rules"
    rules_root.mkdir(parents=True)
    rule_paths = []
    for index, rule in enumerate(rules or _RULES):
        path = rules_root / f"rule-{index}.json"
        path.write_text(json.dumps(rule, ensure_ascii=False), encoding="utf-8")
        rule_paths.append(f"rules/{path.name}")
    manifest = {
        "id": "itgc-core",
        "version": "1.0.0",
        "title": "ITGC Core",
        "domain": "itgc",
        "engine_compatibility": "stage-b",
        "rules": rule_paths,
    }
    manifest.update(manifest_overrides or {})
    (pack_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_load_policy_pack_validates_and_orders_rules(tmp_path):
    pack = load_policy_pack(root=_write_pack(tmp_path))

    assert pack.manifest.id == "itgc-core"
    assert pack.manifest.version == "1.0.0"
    assert [rule.rule_id for rule in pack.rules] == [
        "itgc.procedure.interview_only",
        "itgc.procedure.required_evidence",
    ]
    assert pack.rule("itgc.procedure.interview_only").severity == "P1"


def test_load_policy_pack_rejects_unknown_evaluator(tmp_path):
    rules = [dict(_RULES[0], evaluator_id="procedure.not_trusted")]

    with pytest.raises(PolicyPackError, match="evaluator_id"):
        load_policy_pack(root=_write_pack(tmp_path, rules=rules))


def test_load_policy_pack_rejects_duplicate_rule_ids(tmp_path):
    rules = [_RULES[0], dict(_RULES[0], title="duplicate")]

    with pytest.raises(PolicyPackError, match="duplicate"):
        load_policy_pack(root=_write_pack(tmp_path, rules=rules))


def test_load_policy_pack_rejects_missing_rule_file(tmp_path):
    _write_pack(tmp_path, manifest_overrides={"rules": ["rules/missing.json"]})

    with pytest.raises(PolicyPackError, match="missing"):
        load_policy_pack(root=tmp_path)


def test_load_policy_pack_rejects_path_traversal(tmp_path):
    with pytest.raises(PolicyPackError, match="path"):
        load_policy_pack(root=tmp_path, pack_id="../itgc-core")
