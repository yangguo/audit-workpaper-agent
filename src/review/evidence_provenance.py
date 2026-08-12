"""Evidence identity and fail-closed verification for V1 finding citations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from review.attachments import (
    _extract_attachment_refs,
    _match_attachment_items,
    _normalize_rel_path,
)
from review.evidence import sha256_file
from review.excel_utils import _extract_sheet_text_cells, _normalize_sheet_id
from review.contracts import EvidenceGraph


def _field(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class EvidenceVerificationResult:
    accepted_refs: list[dict[str, Any]]
    rejected_count: int = 0
    rejection_codes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.rejection_codes is None:
            self.rejection_codes = []

    @property
    def status(self) -> str:
        if self.accepted_refs and self.rejected_count:
            return "partial"
        if self.accepted_refs:
            return "verified"
        if self.rejected_count:
            return "invalid"
        return "not_available"


@dataclass
class _AttachmentCandidate:
    logical_path: str
    text: str
    content_hash: str
    source_sha256: str
    physical_path: Path | None
    extraction_status: str
    source_type: str


class EvidenceProvenanceIndex:
    """Index a pinned workbook and attachment snapshot for citation checks.

    The index records the snapshot hashes at construction time. A later file
    replacement is therefore detected before an attachment citation is
    accepted, instead of silently trusting the mutable upload directory.
    """

    def __init__(
        self,
        evidence_graph: EvidenceGraph | Mapping[str, Any],
        *,
        attachments: Mapping[str, Any] | None = None,
        workbook: Any = None,
    ) -> None:
        self.graph = (
            evidence_graph
            if isinstance(evidence_graph, EvidenceGraph)
            else EvidenceGraph.model_validate(evidence_graph)
        )
        self.attachments = dict(attachments or {})
        self._cells: dict[tuple[str, str], Any] = {}
        for sheet in self.graph.sheets:
            sheet_key = _normalize_sheet_id(sheet.name)
            for cell in sheet.cells:
                self._cells[(sheet_key, cell.coordinate.upper())] = cell
        self._attachments_by_path: dict[str, list[_AttachmentCandidate]] = {}
        self._attachments_by_filename: dict[str, list[_AttachmentCandidate]] = {}
        self._allowed_by_sheet = self._build_allowed_scope(workbook)
        self._index_attachments()

    def _build_allowed_scope(self, workbook: Any) -> dict[str, set[str]]:
        allowed: dict[str, set[str]] = {}

        def add(sheet_name: str, rel_path: str) -> None:
            key = _normalize_rel_path(rel_path)
            sheet_key = _normalize_sheet_id(sheet_name)
            if key and sheet_key:
                allowed.setdefault(sheet_key, set()).add(key)

        items = self.attachments.get("items") or []
        if workbook is not None:
            for worksheet in getattr(workbook, "worksheets", []):
                sheet_name = str(getattr(worksheet, "title", "") or "")
                for _, text in _extract_sheet_text_cells(worksheet):
                    filenames, rel_paths, indices = _extract_attachment_refs(text)
                    if not filenames and not rel_paths and not indices:
                        continue
                    matched, _ = _match_attachment_items(
                        self.attachments,
                        filenames=filenames,
                        rel_paths=rel_paths,
                        indices=indices,
                    )
                    for item in matched:
                        add(sheet_name, _field(item, "rel_path"))

        by_sheet = self.attachments.get("by_sheet_norm") or {}
        if isinstance(by_sheet, Mapping):
            for sheet_name, sheet_items in by_sheet.items():
                for item in sheet_items if isinstance(sheet_items, list) else []:
                    add(str(sheet_name), _field(item, "rel_path"))

        agent_by_sheet = self.attachments.get("agent_evidence_by_sheet") or {}
        if isinstance(agent_by_sheet, Mapping):
            for sheet_name, evidence_items in agent_by_sheet.items():
                for item in evidence_items if isinstance(evidence_items, list) else []:
                    add(str(sheet_name), _field(item, "path"))

        return allowed

    def _physical_path(self, logical_path: str) -> Path | None:
        root_value = self.attachments.get("path")
        if not root_value or self.attachments.get("source_type") != "directory":
            return None
        root = Path(str(root_value)).expanduser().resolve()
        logical_key = _normalize_rel_path(logical_path)
        mapping = self.attachments.get("source_rel_path_by_logical_path") or {}
        candidates: list[str] = []
        if isinstance(mapping, Mapping):
            mapped = mapping.get(logical_key)
            if isinstance(mapped, str) and _normalize_rel_path(mapped):
                candidates.append(mapped)
        candidates.append(logical_path)
        if "::" in logical_path:
            candidates.append(logical_path.replace("::", "__"))
        for candidate in candidates:
            try:
                physical = (root / Path(candidate)).resolve()
                if physical.is_file() and physical.is_relative_to(root):
                    return physical
            except (OSError, ValueError):
                continue
        return None

    def _index_attachments(self) -> None:
        ocr_cache = self.attachments.get("ocr_by_path") or {}
        for item in self.attachments.get("items") or []:
            logical_path = _text(_field(item, "rel_path"))
            normalized = _normalize_rel_path(logical_path)
            if not normalized:
                continue
            text = _text(_field(item, "extracted_text"))
            cached = ocr_cache.get(normalized) if isinstance(ocr_cache, Mapping) else None
            if not text and isinstance(cached, Mapping) and _text(cached.get("status")).lower() == "ok":
                text = _text(cached.get("content"))
            physical = self._physical_path(logical_path)
            source_sha256 = ""
            if physical is not None:
                try:
                    source_sha256 = sha256_file(physical)
                except OSError:
                    physical = None
            candidate = _AttachmentCandidate(
                logical_path=logical_path,
                text=text,
                content_hash=_digest(text),
                source_sha256=source_sha256,
                physical_path=physical,
                extraction_status=(
                    _text(_field(item, "extraction_status"))
                    or _text(_field(item, "status"))
                    or "unknown"
                ),
                source_type=_text(self.attachments.get("source_type")) or "unknown",
            )
            self._attachments_by_path.setdefault(normalized, []).append(candidate)
            parts = normalized.split("/")
            for start in range(1, len(parts)):
                suffix = "/".join(parts[start:])
                self._attachments_by_path.setdefault(suffix, []).append(candidate)
            self._attachments_by_filename.setdefault(Path(normalized).name, []).append(candidate)

    @staticmethod
    def _attachment_evidence_id(candidate: _AttachmentCandidate) -> str:
        return "attachment:" + _digest(
            candidate.logical_path + ":" + candidate.content_hash
        )[:32]

    def snapshot_records(self) -> list[dict[str, Any]]:
        """Return precomputed source identities without rereading mutable inputs.

        Consumers use these records to derive evidence facts.  No file-system
        walk or re-hash happens here: construction already pinned the cell and
        attachment identity used by citation verification.
        """

        records: list[dict[str, Any]] = []
        sheet_names = {
            _normalize_sheet_id(sheet.name): sheet.name for sheet in self.graph.sheets
        }
        for (sheet_key, coordinate), cell in sorted(self._cells.items()):
            sheet_name = sheet_names.get(sheet_key, sheet_key)
            records.append(
                {
                    "fact_id": cell.evidence_id,
                    "fact_type": "cell",
                    "source_ref": f"workpaper:{sheet_name}!{coordinate}",
                    "source_sha256": self.graph.source_sha256,
                    "content_hash": cell.content_hash,
                    "sheet_scope": [sheet_name] if sheet_name else [],
                    "extraction_status": "ok",
                    "source_type": "workpaper",
                }
            )

        attachment_candidates: dict[str, _AttachmentCandidate] = {}
        for candidates in self._attachments_by_path.values():
            for candidate in candidates:
                attachment_candidates.setdefault(
                    _normalize_rel_path(candidate.logical_path), candidate
                )
        for key, candidate in sorted(attachment_candidates.items()):
            scope = sorted(
                sheet_names.get(sheet_key, sheet_key)
                for sheet_key, paths in self._allowed_by_sheet.items()
                if key in paths
            )
            records.append(
                {
                    "fact_id": self._attachment_evidence_id(candidate),
                    "fact_type": "attachment",
                    "source_ref": candidate.logical_path,
                    "source_sha256": candidate.source_sha256,
                    "content_hash": candidate.content_hash,
                    "sheet_scope": scope,
                    "extraction_status": candidate.extraction_status,
                    "source_type": candidate.source_type,
                }
            )
        return records

    def _cell_ref(
        self,
        raw: Mapping[str, Any],
        *,
        default_sheet: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        sheet = _text(raw.get("sheet")) or default_sheet
        coordinate = _text(raw.get("cell_or_range")).upper()
        if not sheet or not coordinate:
            return None, "missing_locator"
        cell = self._cells.get((_normalize_sheet_id(sheet), coordinate))
        if cell is None:
            return None, "cell_not_indexed"
        actual = _text(cell.value)
        excerpt = _text(raw.get("excerpt") or raw.get("quote"))
        if excerpt and excerpt not in actual:
            return None, "excerpt_mismatch"
        start = actual.find(excerpt) if excerpt else 0
        end = start + len(excerpt) if excerpt else len(actual)
        accepted = dict(raw)
        accepted.pop("attachment", None)
        accepted.update(
            {
                "sheet": sheet,
                "cell_or_range": coordinate,
                "source_kind": "cell",
                "source_ref": f"workpaper:{sheet}!{coordinate}",
                "source_sha256": self.graph.source_sha256,
                "evidence_id": cell.evidence_id,
                "content_hash": cell.content_hash,
                "start_offset": start,
                "end_offset": end,
            }
        )
        return accepted, None

    def _attachment_ref(
        self,
        raw: Mapping[str, Any],
        *,
        default_sheet: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        attachment = _text(raw.get("attachment"))
        if not attachment:
            return None, "missing_locator"
        key = _normalize_rel_path(attachment)
        candidates = list(self._attachments_by_path.get(key, []))
        if not candidates and "/" not in key:
            candidates = list(self._attachments_by_filename.get(key, []))
        unique: dict[str, _AttachmentCandidate] = {
            _normalize_rel_path(item.logical_path): item for item in candidates
        }
        candidates = list(unique.values())
        if not candidates:
            return None, "source_not_indexed"
        if len(candidates) != 1:
            return None, "ambiguous_source"
        candidate = candidates[0]
        sheet = _text(raw.get("sheet")) or default_sheet
        allowed = self._allowed_by_sheet.get(_normalize_sheet_id(sheet), set())
        candidate_key = _normalize_rel_path(candidate.logical_path)
        if candidate_key not in allowed:
            return None, "out_of_scope_source"
        if candidate.physical_path is not None and candidate.source_sha256:
            try:
                if sha256_file(candidate.physical_path) != candidate.source_sha256:
                    return None, "content_mismatch"
            except OSError:
                return None, "content_mismatch"
        excerpt = _text(raw.get("excerpt") or raw.get("quote"))
        # A uniquely matched, in-scope frozen file can prove that the file
        # exists even when it has no extractable text. It deliberately carries
        # no offsets/quote, so claim support may use it only for presence; text,
        # date and configuration claims still require a verified excerpt below.
        if (
            candidate.source_type == "directory"
            and candidate.source_sha256
            and (not candidate.text or not excerpt)
        ):
            accepted = dict(raw)
            accepted.update(
                {
                    "sheet": sheet,
                    "source_kind": "attachment",
                    "source_ref": candidate.logical_path,
                    "attachment": candidate.logical_path,
                    "source_sha256": candidate.source_sha256,
                    "content_hash": candidate.content_hash,
                    "evidence_id": self._attachment_evidence_id(candidate),
                    "verification_scope": "presence_only",
                }
            )
            return accepted, None
        if not candidate.text:
            return None, "source_text_unavailable"
        occurrences = candidate.text.count(excerpt) if excerpt else 0
        if not excerpt or occurrences == 0:
            return None, "excerpt_not_found"
        if occurrences != 1:
            return None, "excerpt_ambiguous"
        start = candidate.text.find(excerpt)
        accepted = dict(raw)
        accepted.update(
            {
                "sheet": sheet,
                "source_kind": "attachment",
                "source_ref": candidate.logical_path,
                "attachment": candidate.logical_path,
                "source_sha256": candidate.source_sha256,
                "content_hash": candidate.content_hash,
                "evidence_id": self._attachment_evidence_id(candidate),
                "start_offset": start,
                "end_offset": start + len(excerpt),
            }
        )
        return accepted, None

    def verify_refs(
        self,
        refs: Iterable[Mapping[str, Any]] | None,
        *,
        default_sheet: str = "",
    ) -> EvidenceVerificationResult:
        accepted: list[dict[str, Any]] = []
        rejection_codes: list[str] = []
        for raw in refs or []:
            if not isinstance(raw, Mapping):
                rejection_codes.append("invalid_ref")
                continue
            has_attachment = bool(_text(raw.get("attachment")))
            if has_attachment:
                attachment_ref, error = self._attachment_ref(raw, default_sheet=default_sheet)
                if attachment_ref is not None:
                    accepted.append(attachment_ref)
                    continue
                # Preserve an independently valid cell citation if a model
                # added an invalid attachment hint to the same ref.
                if _text(raw.get("cell_or_range")):
                    cell_ref, cell_error = self._cell_ref(raw, default_sheet=default_sheet)
                    if cell_ref is not None:
                        accepted.append(cell_ref)
                        continue
                    error = cell_error or error
                rejection_codes.append(error or "invalid_attachment_ref")
                continue
            cell_ref, error = self._cell_ref(raw, default_sheet=default_sheet)
            if cell_ref is not None:
                accepted.append(cell_ref)
            else:
                rejection_codes.append(error or "invalid_cell_ref")
        return EvidenceVerificationResult(
            accepted_refs=accepted,
            rejected_count=len(rejection_codes),
            rejection_codes=rejection_codes,
        )


def verify_finding_evidence(
    finding: Mapping[str, Any],
    index: EvidenceProvenanceIndex,
) -> tuple[dict[str, Any], EvidenceVerificationResult]:
    """Verify a V1 finding and downgrade unsupported failures to unknown."""

    updated = dict(finding)
    raw_refs = updated.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError:
            raw_refs = []
    refs = raw_refs if isinstance(raw_refs, list) else []
    result = index.verify_refs(refs, default_sheet=_text(updated.get("sheet")))
    updated["evidence_refs"] = result.accepted_refs
    if updated.get("status") == "fail" and not result.accepted_refs:
        proposed_severity = _text(updated.get("severity"))
        if proposed_severity:
            updated.setdefault("proposed_severity", proposed_severity)
        updated["status"] = "unknown"
        updated["severity"] = "P2"
        updated["risk_type"] = _text(updated.get("risk_type")) or "证据不足"
        updated["unknown_reason"] = (
            "无法引用原始证据（冻结快照）佐证该判定，已降级为不确定；"
            + "、".join(result.rejection_codes[:3])
        )
    return updated, result
