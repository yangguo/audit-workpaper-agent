"""Stage-C V2 finding serialization and V1-compatible projection."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from review.judgement import JudgementExecution, JudgementRequest
from review.policy import PolicyPack


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


class V2Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "stage-c-v2-finding/1"
    finding_id: str
    identity_key: str
    rule_id: str
    rule_version: str
    issue_type: str
    severity: str
    risk_type: str
    sheet: str
    cell: str | None = None
    status: Literal["pass", "fail", "unknown"]
    decision: Literal["supported", "contradicted", "insufficient"]
    verification_status: Literal[
        "supported", "contradicted", "insufficient", "invalid"
    ]
    conclusion: str
    basis: str
    suggestion: str
    evidence_refs_v2: list[dict[str, object]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    unknown_reason: str = ""
    provenance: dict[str, object] = Field(default_factory=dict)
    review_scope: dict[str, object] = Field(default_factory=dict)
    resolution: str = "unreviewed"


def _status_for(execution: JudgementExecution) -> Literal["pass", "fail", "unknown"]:
    if execution.verification_status == "invalid":
        return "unknown"
    if execution.decision == "contradicted":
        return "fail"
    if execution.decision == "supported":
        return "pass"
    return "unknown"


def _basis(execution: JudgementExecution) -> str:
    parts = [execution.conclusion.strip()]
    parts.extend(reason.strip() for reason in execution.reasoning_summary if reason.strip())
    if execution.unknown_reason.strip():
        parts.append("不确定原因：" + execution.unknown_reason.strip())
    if execution.errors:
        parts.append("验证错误：" + "、".join(execution.errors[:5]))
    return "\n".join(part for part in parts if part)[:4000]


def _cell_from(request: JudgementRequest, execution: JudgementExecution) -> tuple[str, str | None]:
    fact = request.fact
    sheet = str(fact.get("sheet", "") or "")
    cell = str(fact.get("execution_cell", "") or "") or None
    if not cell and execution.evidence_refs_v2:
        cell = str(execution.evidence_refs_v2[0].get("cell_or_range", "") or "") or None
    return sheet, cell


def build_v2_findings(
    *,
    requests: Sequence[JudgementRequest],
    executions: Sequence[JudgementExecution],
    policy_pack: PolicyPack,
    engine_version: str,
) -> list[dict[str, object]]:
    """Map verified judgement outcomes to stable V2 findings."""
    request_by_id = {request.request_id: request for request in requests}
    findings_by_identity: dict[str, V2Finding] = {}
    for raw_execution in executions:
        execution = (
            raw_execution
            if isinstance(raw_execution, JudgementExecution)
            else JudgementExecution.model_validate(raw_execution)
        )
        request = request_by_id.get(execution.request_id)
        if request is None:
            continue
        rule = policy_pack.rule(execution.rule_id)
        status = _status_for(execution)
        sheet, cell = _cell_from(request, execution)
        evidence_ids = sorted(
            str(ref.get("evidence_id", ""))
            for ref in execution.evidence_refs_v2
            if ref.get("evidence_id")
        )
        identity_material = {
            "rule_id": rule.rule_id,
            "rule_version": rule.version,
            "sheet": sheet,
            "cell": cell,
            "evidence_ids": evidence_ids,
            "decision": execution.decision,
        }
        identity_key = f"judgement:{_stable_hash(identity_material)[:32]}"
        finding = V2Finding(
            finding_id=f"finding:{_stable_hash({'identity': identity_key, 'engine': engine_version})[:32]}",
            identity_key=identity_key,
            rule_id=rule.rule_id,
            rule_version=rule.version,
            issue_type=rule.title,
            severity=rule.severity,
            risk_type=rule.risk_type,
            sheet=sheet,
            cell=cell,
            status=status,
            decision=execution.decision,
            verification_status=execution.verification_status,
            conclusion=execution.conclusion,
            basis=_basis(execution),
            suggestion=rule.remediation_template,
            evidence_refs_v2=list(execution.evidence_refs_v2),
            reasons=list(execution.reasoning_summary),
            unknown_reason=execution.unknown_reason,
            provenance={
                "engine_version": engine_version,
                "stage": "stage-c-judgement-shadow",
                "policy_pack": {"id": policy_pack.id, "version": policy_pack.version},
            },
            review_scope=dict(request.review_scope),
        )
        existing = findings_by_identity.get(identity_key)
        if existing is None:
            findings_by_identity[identity_key] = finding
        else:
            merged_refs = list(existing.evidence_refs_v2)
            existing_ids = {str(ref.get("evidence_id", "")) for ref in merged_refs}
            merged_refs.extend(
                ref for ref in finding.evidence_refs_v2
                if str(ref.get("evidence_id", "")) not in existing_ids
            )
            findings_by_identity[identity_key] = existing.model_copy(
                update={"evidence_refs_v2": merged_refs}
            )
    return [
        finding.model_dump(mode="json")
        for finding in sorted(
            findings_by_identity.values(), key=lambda item: item.identity_key
        )
    ]


def project_v2_finding_to_v1(finding: dict[str, object] | V2Finding) -> dict[str, object]:
    """Create a non-mutating V1-compatible finding projection."""
    payload = (
        finding.model_dump(mode="json")
        if isinstance(finding, V2Finding)
        else dict(finding)
    )
    refs = []
    for ref in payload.get("evidence_refs_v2", []) or []:
        if not isinstance(ref, dict):
            continue
        refs.append(
            {
                "evidence_id": ref.get("evidence_id", ""),
                "sheet": ref.get("sheet", payload.get("sheet", "")),
                "cell_or_range": ref.get("cell_or_range", ""),
                "excerpt": ref.get("quote", ""),
                "start_offset": ref.get("start_offset", 0),
                "end_offset": ref.get("end_offset", 0),
                "content_hash": ref.get("content_hash", ""),
            }
        )
    snippet = str(refs[0].get("excerpt", "") if refs else "")
    return {
        "finding_id": payload.get("finding_id", ""),
        "issue_type": payload.get("issue_type", ""),
        "severity": payload.get("severity", "P2"),
        "sheet": payload.get("sheet", ""),
        "cell": payload.get("cell"),
        "snippet": snippet,
        "basis": payload.get("basis", ""),
        "suggestion": payload.get("suggestion", ""),
        "status": payload.get("status", "unknown"),
        "risk_type": payload.get("risk_type", "证据不足"),
        "evidence_refs": refs,
        "conclusion": payload.get("conclusion", ""),
        "reasons": payload.get("reasons", []),
        "unknown_reason": payload.get("unknown_reason", ""),
        "v2_finding_id": payload.get("finding_id", ""),
        "v2_identity_key": payload.get("identity_key", ""),
    }


def project_v2_findings_to_v1(findings: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    return [project_v2_finding_to_v1(finding) for finding in findings]
