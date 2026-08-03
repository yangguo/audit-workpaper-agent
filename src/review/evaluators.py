"""Trusted deterministic evaluators for the Stage-B policy pilot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from review.constants import EVIDENCE_KEYWORDS, OS_DB_KEYWORDS
from review.policy import PolicyPack, PolicyRule, load_policy_pack
from review.procedure_pairs import _likely_interview_only, _requires_evidence_by_standard


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _refs_from_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        for evidence in entry.get("evidence", []):
            evidence_id = str(evidence.get("evidence_id", ""))
            quote = str(evidence.get("value", "") or "")
            if not evidence_id or not quote or evidence_id in seen:
                continue
            seen.add(evidence_id)
            refs.append(
                {
                    "evidence_id": evidence_id,
                    "sheet": evidence.get("sheet", ""),
                    "cell_or_range": evidence.get("cell_or_range", ""),
                    "quote": quote,
                    "start_offset": 0,
                    "end_offset": len(quote),
                    "content_hash": evidence.get("content_hash", ""),
                    "role": "supporting",
                }
            )
    return refs


def _control_interview_only(fact: dict[str, object], rule: PolicyRule):
    standard_text = str(fact.get("standard_text", "") or "")
    for execution in fact.get("executions", []):
        text = str(execution.get("text", "") or "")
        if len(standard_text) < 20 or len(text) < 20:
            continue
        if not _likely_interview_only(text):
            continue
        refs = _refs_from_entries([execution])
        if not refs:
            continue
        return {
            "conclusion_code": "interview_only",
            "issue_type": "程序执行不到位/仅依赖访谈",
            "basis": "执行描述出现访谈/询问等，但未体现可复核的实质性证据。",
            "suggestion": rule.remediation_template,
            "evidence_refs_v2": refs,
        }
    return None


def _control_required_evidence(fact: dict[str, object], rule: PolicyRule):
    standard_text = str(fact.get("standard_text", "") or "")
    required = list(_requires_evidence_by_standard(standard_text))
    if not required:
        return None
    for execution in fact.get("executions", []):
        text = str(execution.get("text", "") or "")
        if len(standard_text) < 20 or len(text) < 20:
            continue
        execution_like = (
            "我们" in text
            or _likely_interview_only(text)
            or any(keyword in text for keyword in EVIDENCE_KEYWORDS)
        )
        if not execution_like or any(keyword in text for keyword in EVIDENCE_KEYWORDS):
            continue
        refs = _refs_from_entries([execution])
        if not refs:
            continue
        return {
            "conclusion_code": "required_evidence_missing",
            "issue_type": "证据类型缺失",
            "basis": f"标准审计程序要求获取/检查证据（{', '.join(required)}），但执行描述未体现对应证据。",
            "suggestion": rule.remediation_template,
            "evidence_refs_v2": refs,
        }
    return None


def _sheet_scope_os_db_admin(fact: dict[str, object], rule: PolicyRule):
    text = str(fact.get("text", "") or "")
    if not ("管理员" in text or "特权" in text):
        return None
    if any(keyword in text for keyword in OS_DB_KEYWORDS):
        return None
    evidence = [
        item for item in fact.get("evidence", [])
        if "管理员" in str(item.get("value", "")) or "特权" in str(item.get("value", ""))
    ]
    refs = _refs_from_entries([{"evidence": evidence}])
    if not refs:
        return None
    return {
        "conclusion_code": "os_db_admin_scope_missing",
        "issue_type": "特权账号识别范围可能不完整",
        "basis": "检查范围包含管理员/特权账号，但未体现操作系统或数据库层面的管理员覆盖。",
        "suggestion": rule.remediation_template,
        "evidence_refs_v2": refs,
    }


EVALUATOR_REGISTRY: dict[str, Callable[[dict[str, object], PolicyRule], dict[str, object] | None]] = {
    "procedure.interview_only": _control_interview_only,
    "procedure.required_evidence": _control_required_evidence,
    "scope.os_db_admin": _sheet_scope_os_db_admin,
}


@dataclass(frozen=True)
class PolicyFinding:
    finding_id: str
    identity_key: str
    rule_id: str
    rule_version: str
    issue_type: str
    severity: str
    risk_type: str
    sheet: str
    cell: str | None
    basis: str
    suggestion: str
    evidence_refs_v2: list[dict[str, object]]
    verification_status: str
    status: str
    provenance: dict[str, object]
    review_scope: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "identity_key": self.identity_key,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "risk_type": self.risk_type,
            "sheet": self.sheet,
            "cell": self.cell,
            "basis": self.basis,
            "suggestion": self.suggestion,
            "evidence_refs_v2": self.evidence_refs_v2,
            "verification_status": self.verification_status,
            "status": self.status,
            "provenance": self.provenance,
            "review_scope": self.review_scope,
        }


def execute_policy_plan(plan, policy_pack: PolicyPack | None = None) -> dict[str, object]:
    """Execute a plan using only the trusted evaluator registry."""
    payload = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan)
    pack_info = payload.get("policy_pack") or {}
    pack = policy_pack or load_policy_pack(
        pack_id=str(pack_info.get("id", "itgc-core")),
        version=str(pack_info.get("version", "1.0.0")),
    )
    findings: list[dict[str, object]] = []
    seen_identity: set[str] = set()
    deduplicated = 0
    for item in payload.get("items", []):
        rule = pack.rule(str(item.get("rule_id", "")))
        evaluator_id = str(item.get("evaluator_id", ""))
        evaluator = EVALUATOR_REGISTRY.get(evaluator_id)
        if evaluator is None or evaluator_id != rule.evaluator_id:
            raise ValueError(f"untrusted evaluator: {evaluator_id}")
        result = evaluator(dict(item.get("fact") or {}), rule)
        if not result:
            continue
        refs = list(result.get("evidence_refs_v2") or [])
        if not refs:
            continue
        evidence_ids = sorted(str(ref.get("evidence_id", "")) for ref in refs)
        identity_material = {
            "rule_id": rule.rule_id,
            "rule_version": rule.version,
            "evidence_ids": evidence_ids,
            "conclusion_code": result.get("conclusion_code", rule.rule_id),
        }
        identity_key = f"policy:{_stable_hash(identity_material)[:32]}"
        if identity_key in seen_identity:
            deduplicated += 1
            continue
        seen_identity.add(identity_key)
        fact = dict(item.get("fact") or {})
        finding = PolicyFinding(
            finding_id=f"finding:{_stable_hash({'plan': payload.get('plan_id'), 'identity': identity_key})[:32]}",
            identity_key=identity_key,
            rule_id=rule.rule_id,
            rule_version=rule.version,
            issue_type=str(result.get("issue_type", rule.title)),
            severity=rule.severity,
            risk_type=rule.risk_type,
            sheet=str(fact.get("sheet", "")),
            cell=(str(refs[0].get("cell_or_range", "")) or None),
            basis=str(result.get("basis", "")),
            suggestion=str(result.get("suggestion", rule.remediation_template)),
            evidence_refs_v2=refs,
            verification_status="supported",
            status="fail",
            provenance={
                "engine_version": payload.get("engine_version", "stage-b-policy"),
                "policy_pack": pack_info,
                "stage": "stage-b-policy-shadow",
            },
            review_scope=dict(payload.get("scope") or {}),
        )
        findings.append(finding.to_dict())
    findings.sort(key=lambda item: str(item["identity_key"]))
    return {
        "schema_version": "stage-b-policy-findings/1",
        "policy_pack": {"id": pack.id, "version": pack.version},
        "plan_id": payload.get("plan_id", ""),
        "findings": findings,
        "stats": {
            "items": len(payload.get("items", [])),
            "candidates": len(findings),
            "deduplicated": deduplicated,
            "skipped": len(payload.get("skipped", [])),
        },
    }
