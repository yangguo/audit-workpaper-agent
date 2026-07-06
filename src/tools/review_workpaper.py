"""
底稿全量审阅工具 - 运行移植自 analyze_excel.py 的完整审阅管线

产出结构化 findings 写入侧端存储，返回摘要给 agent；前端通过 GET /findings/{review_id} 读取结构化结果。
"""
import json
import os
import uuid

import openpyxl
from langchain.tools import tool

from review.attachments import load_attachments_preview_xlsx
from review.checkpoints import load_checkpoints_xlsx
from review.llm import get_review_llm
from review.pipeline import run_review
from storage.findings_store import save_findings


def _resolve_path(workspace_path: str, file_path: str) -> str:
    if not file_path:
        return ""
    return file_path if os.path.isabs(file_path) else os.path.join(workspace_path, file_path)


@tool
async def review_workpaper(
    file_path: str,
    checkpoints_path: str = "",
    attachments_preview_path: str = "",
    sheets: str = "",
) -> str:
    """
    对 Excel 审计底稿执行全量审阅（检查要点复核、附件引用匹配、证据-步骤一致性、
    程序对规则检查、A-C 对应性 LLM 判定、规则 findings 的 LLM 复核、交叉校验与对抗式质疑）。

    Args:
        file_path: 底稿 Excel 路径（相对于 assets 目录或绝对路径）
        checkpoints_path: 检查要点 Excel 路径（可选）
        attachments_preview_path: 附件预览 Excel 路径（可选）
        sheets: 指定检查的 Sheet，逗号分隔（可选，留空=全部）

    Returns:
        JSON 字符串，包含 review_id、findings_url、按严重度/状态/风险类型的计数、
        top 问题列表。完整结构化 findings 通过 GET /findings/{review_id} 获取。
    """
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", os.getcwd())
    full_path = _resolve_path(workspace_path, file_path)

    if not full_path or not os.path.exists(full_path):
        return json.dumps({
            "success": False,
            "error": f"文件不存在: {full_path or file_path}",
        }, ensure_ascii=False)

    try:
        wb = openpyxl.load_workbook(full_path, data_only=True)
        checkpoints = {}
        if checkpoints_path:
            cp_full = _resolve_path(workspace_path, checkpoints_path)
            if os.path.exists(cp_full):
                checkpoints = load_checkpoints_xlsx(cp_full)

        attachments_preview = {}
        if attachments_preview_path:
            ap_full = _resolve_path(workspace_path, attachments_preview_path)
            if os.path.exists(ap_full):
                attachments_preview = load_attachments_preview_xlsx(ap_full)

        llm = get_review_llm()
        findings, stats = await run_review(
            wb=wb,
            checkpoints=checkpoints,
            attachments_preview=attachments_preview,
            sheets=sheets or None,
            llm=llm,
        )

        review_id = uuid.uuid4().hex
        save_findings(review_id, findings, stats, source=os.path.basename(full_path))

        summary = {
            "success": True,
            "review_id": review_id,
            "findings_url": f"/findings/{review_id}",
            "total_findings": len(findings),
            "counts_by_severity": stats.get("by_severity", {}),
            "counts_by_status": stats.get("by_status", {}),
            "counts_by_risk_type": stats.get("by_risk_type", {}),
            "top_issues": [
                {
                    "issue_type": f.get("issue_type", ""),
                    "severity": f.get("severity", ""),
                    "severity_display": f.get("severity_display", ""),
                    "sheet": f.get("sheet", ""),
                    "cell": f.get("cell"),
                    "conclusion": f.get("conclusion", "") or f.get("llm_conclusion", ""),
                }
                for f in findings[:10]
            ],
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"审阅失败: {type(e).__name__}: {e}",
        }, ensure_ascii=False)
