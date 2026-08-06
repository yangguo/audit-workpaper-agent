"""Export review findings to structured report formats."""
import io
import json
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def generate_findings_xlsx(findings: List[Dict[str, Any]]) -> bytes:
    """Render a list of findings into an .xlsx workbook and return its bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "审阅发现汇总"

    headers = [
        "序号", "Sheet", "单元格", "问题类型", "严重级别", "风险类型",
        "状态", "结论", "判定依据", "整改建议", "证据引用",
        "交叉校验问题", "LLM 复核状态", "LLM 复核说明", "不确定原因",
    ]

    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    header_font = Font(bold=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    widths = [6, 12, 12, 35, 12, 12, 10, 35, 45, 45, 45, 30, 15, 30, 30]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    for idx, finding in enumerate(findings, start=1):
        row = idx + 1
        severity = finding.get("severity", "")
        severity_display = finding.get("severity_display", "")
        severity_str = f"{severity} / {severity_display}" if severity_display else severity

        conclusion = finding.get("llm_conclusion") or finding.get("conclusion") or ""

        evidence_refs = finding.get("evidence_refs", [])
        if isinstance(evidence_refs, list):
            # Preserve the full reference objects (including the `attachment`
            # field used by attachment-backed findings) as JSON text so the
            # report round-trips the original evidence payload.
            evidence_str = "\n".join(
                json.dumps(ref, ensure_ascii=False) for ref in evidence_refs
            )
        else:
            evidence_str = str(evidence_refs)

        cross_issues = finding.get("cross_validate_issues", [])
        if isinstance(cross_issues, list):
            cross_str = "；".join(cross_issues)
        else:
            cross_str = str(cross_issues)

        values = [
            idx,
            finding.get("sheet", ""),
            finding.get("cell", ""),
            finding.get("issue_type", ""),
            severity_str,
            finding.get("risk_type", ""),
            finding.get("status", ""),
            conclusion,
            finding.get("basis", ""),
            finding.get("suggestion", ""),
            evidence_str,
            cross_str,
            finding.get("llm_status", ""),
            finding.get("llm_comment", ""),
            finding.get("unknown_reason", ""),
        ]

        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = "A2"

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()
