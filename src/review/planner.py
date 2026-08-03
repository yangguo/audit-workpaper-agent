"""Compile a bounded Evidence Graph and policy pack into a deterministic plan."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from review.contracts import EvidenceGraph, SheetEvidence
from review.evidence import build_evidence_graph
from review.excel_utils import _detect_layout, _get_cell_value, _normalize_sheet_id
from review.policy import PolicyPack, PolicyRule


_MAX_SHEET_TEXT = 24000
_MAX_FACTS_PER_SHEET = 5000


def _stable_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _requested_sheets(sheets: str | Sequence[str] | None) -> list[str]:
    if sheets is None:
        return []
    if isinstance(sheets, str):
        values = sheets.split(",")
    else:
        values = list(sheets)
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _resolve_scope(workbook, sheets: str | Sequence[str] | None) -> dict[str, object]:
    requested = _requested_sheets(sheets)
    if not requested:
        return {
            "requested_sheets": [],
            "target_sheets": list(workbook.sheetnames),
            "status": "ok",
            "unmatched": [],
        }

    by_normalized = {
        _normalize_sheet_id(name): name for name in workbook.sheetnames
    }
    target: list[str] = []
    unmatched: list[str] = []
    for requested_name in requested:
        resolved = by_normalized.get(_normalize_sheet_id(requested_name))
        if resolved is None:
            unmatched.append(requested_name)
        elif resolved not in target:
            target.append(resolved)
    status = "scope_validation_failed" if not target else ("partial" if unmatched else "ok")
    return {
        "requested_sheets": requested,
        "target_sheets": target,
        "status": status,
        "unmatched": unmatched,
    }


def _cell_payload(cell) -> dict[str, object]:
    return {
        "evidence_id": cell.evidence_id,
        "sheet": cell.sheet_name,
        "cell_or_range": cell.coordinate,
        "value": str(cell.value or ""),
        "content_hash": cell.content_hash,
    }


def _evidence_index(sheet: SheetEvidence) -> dict[str, dict[str, object]]:
    return {cell.coordinate: _cell_payload(cell) for cell in sheet.cells}


def _unique_evidence(values: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in values:
        evidence_id = str(value.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        result.append(value)
    return result


def _control_facts(ws, sheet_evidence: SheetEvidence) -> list[dict[str, object]]:
    header_row, standard_col, execution_cols = _detect_layout(ws)
    if header_row is None or standard_col <= 0 or not execution_cols:
        return []
    evidence_by_cell = _evidence_index(sheet_evidence)
    facts: list[dict[str, object]] = []
    empty_streak = 0
    for row in range(max(5, header_row + 2), (ws.max_row or 0) + 1):
        standard_cell = f"{ws.cell(row=1, column=standard_col).column_letter}{row}"
        standard_text = _get_cell_value(ws, standard_cell)
        executions: list[dict[str, object]] = []
        for column in execution_cols:
            cell = ws.cell(row=row, column=column)
            text = _get_cell_value(ws, cell.coordinate)
            if text:
                executions.append(
                    {
                        "cell": cell.coordinate,
                        "text": text,
                        "evidence": (
                            [evidence_by_cell[cell.coordinate]]
                            if cell.coordinate in evidence_by_cell
                            else []
                        ),
                    }
                )
        if standard_text is None and not executions:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue
        empty_streak = 0
        if standard_text is None or not executions:
            continue

        standard_evidence = evidence_by_cell.get(standard_cell)
        all_evidence = _unique_evidence(
            ([standard_evidence] if standard_evidence else [])
            + [evidence for execution in executions for evidence in execution["evidence"]]
        )
        fact_material = {
            "sheet": ws.title,
            "row": row,
            "standard_cell": standard_cell,
            "standard_text": standard_text,
            "executions": executions,
            "evidence_ids": [item["evidence_id"] for item in all_evidence],
        }
        facts.append(
            {
                "fact_type": "ControlFact",
                "control_id": f"control:{_stable_hash(fact_material)[:32]}",
                "sheet": ws.title,
                "sheet_id": _normalize_sheet_id(ws.title),
                "row": row,
                "standard_cell": standard_cell,
                "standard_text": standard_text,
                "executions": executions,
                "evidence": all_evidence,
                "layout_confidence": "known",
            }
        )
        if len(facts) >= _MAX_FACTS_PER_SHEET:
            break
    return facts


def _sheet_fact(ws, sheet_evidence: SheetEvidence) -> dict[str, object]:
    evidence = [_cell_payload(cell) for cell in sheet_evidence.cells]
    text = "\n".join(
        f"{item['cell_or_range']}: {item['value']}" for item in evidence
    )[:_MAX_SHEET_TEXT]
    return {
        "fact_type": "SheetFact",
        "sheet": ws.title,
        "sheet_id": _normalize_sheet_id(ws.title),
        "sheet_hash": sheet_evidence.sheet_hash,
        "text": text,
        "evidence": evidence,
        "layout_confidence": (
            "known" if sheet_evidence.layout_header_row is not None else "unknown"
        ),
    }


def _applies(rule: PolicyRule, fact: dict[str, object]) -> bool:
    applies_to = rule.applies_to or {}
    if applies_to.get("fact_type") != fact.get("fact_type"):
        return False
    sheet_ids = applies_to.get("sheet_ids")
    if isinstance(sheet_ids, list) and sheet_ids:
        normalized_ids = {_normalize_sheet_id(str(value)) for value in sheet_ids}
        if str(fact.get("sheet_id", "")) not in normalized_ids:
            return False
    return True


@dataclass(frozen=True)
class ReviewPlan:
    payload: dict[str, object]

    @property
    def items(self) -> list[dict[str, object]]:
        return list(self.payload.get("items", []))

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy(self.payload)


def build_review_plan(
    workbook,
    evidence_graph: EvidenceGraph,
    policy_pack: PolicyPack,
    *,
    sheets: str | Sequence[str] | None = None,
    engine_version: str = "stage-b-policy",
) -> ReviewPlan:
    """Create a stable, JSON-serializable plan from one workbook snapshot."""
    scope = _resolve_scope(workbook, sheets)
    items: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    graph_by_name = {sheet.name: sheet for sheet in evidence_graph.sheets}

    for sheet_name in scope["target_sheets"]:
        sheet_evidence = graph_by_name.get(sheet_name)
        if sheet_evidence is None:
            skipped.append({"sheet": sheet_name, "reason": "missing_evidence_sheet"})
            continue
        ws = workbook[sheet_name]
        facts = [_sheet_fact(ws, sheet_evidence)]
        control_facts = _control_facts(ws, sheet_evidence)
        if not control_facts:
            skipped.append({"sheet": sheet_name, "reason": "layout_unavailable"})
        facts.extend(control_facts)
        for fact in facts:
            applicable = [
                rule for rule in policy_pack.rules
                if rule.enabled and _applies(rule, fact)
            ]
            for rule in applicable:
                material = {
                    "source_sha256": evidence_graph.source_sha256,
                    "policy_pack": {"id": policy_pack.id, "version": policy_pack.version},
                    "engine_version": engine_version,
                    "rule_id": rule.rule_id,
                    "rule_version": rule.version,
                    "fact_type": fact["fact_type"],
                    "fact_id": fact.get("control_id") or fact.get("sheet_hash"),
                }
                items.append(
                    {
                        "plan_item_id": f"plan-item:{_stable_hash(material)[:32]}",
                        "rule_id": rule.rule_id,
                        "rule_version": rule.version,
                        "evaluator_id": rule.evaluator_id,
                        "fact": fact,
                    }
                )

    items.sort(key=lambda item: str(item["plan_item_id"]))
    payload: dict[str, object] = {
        "schema_version": "stage-b-plan/1",
        "engine_version": engine_version,
        "source_sha256": evidence_graph.source_sha256,
        "policy_pack": {"id": policy_pack.id, "version": policy_pack.version},
        "scope": scope,
        "items": items,
        "skipped": skipped,
    }
    payload["plan_id"] = f"plan:{_stable_hash(payload)[:32]}"
    return ReviewPlan(payload)
