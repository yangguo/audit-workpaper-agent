"""
底稿全量审阅工具 - 后台启动审阅管线，立即返回 review_id

审阅在后台异步运行（review.runner），前端轮询 GET /review/{review_id}/status
直至 completed，再拉取 GET /findings/{review_id} 渲染结构化结果。
"""
import json
import logging
import os

from langchain.tools import tool

from review.runner import start_review

_logger = logging.getLogger("review_workpaper")


def _resolve_path(workspace_path: str, file_path: str) -> str:
    if not file_path:
        return ""
    return file_path if os.path.isabs(file_path) else os.path.join(workspace_path, file_path)


@tool
async def review_workpaper(
    file_path: str,
    checkpoints_path: str = "",
    attachments_dir: str = "",
    sheets: str = "",
) -> str:
    """
    对 Excel 审计底稿启动全量审阅（后台运行）：检查要点复核、附件目录证据定位、
    证据文件与步骤一致性、程序对规则检查、A-C 对应性 LLM 判定、规则 findings 的 LLM 复核、
    交叉校验与对抗式质疑。

    本工具立即返回 review_id 与 status="running"，审阅在后台进行（大底稿可能耗时数十分钟）。
    前端通过 GET /review/{review_id}/status 轮询进度，status="completed" 后用
    GET /findings/{review_id} 获取完整结构化 findings。

    Args:
        file_path: 底稿 Excel 路径（相对于 assets 目录或绝对路径）
        checkpoints_path: 检查要点 Excel 路径（可选）
        attachments_dir: 附件目录路径（可选）。审阅会递归查找底稿引用的真实证据文件，
            读取可解析文本并将其提供给证据复核；图片/扫描件等不可提取格式会标记为未解析。
        sheets: 指定要审阅的 Sheet（即控制点，逗号分隔，可选，留空=全部）。用户指定控制点范围时必须传入对应 Sheet 名（底稿 Tab 名）；若用户用描述性说法而非 Sheet 名，应先调用 analyze_worksheet 映射到确切 Sheet 名后再传入

    Returns:
        JSON 字符串，含 review_id、status="running"、status_url、findings_url。
    """
    workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())
    full_path = _resolve_path(workspace_path, file_path)
    cp_full = _resolve_path(workspace_path, checkpoints_path) if checkpoints_path else ""
    ad_full = _resolve_path(workspace_path, attachments_dir) if attachments_dir else ""

    _logger.info(
        "review_workpaper called: file_path=%r checkpoints_path=%r "
        "attachments_dir=%r sheets=%r workspace=%r resolved=%r exists=%r",
        file_path, checkpoints_path, attachments_dir, sheets,
        workspace_path, full_path, bool(full_path and os.path.exists(full_path)),
    )

    if not full_path or not os.path.exists(full_path):
        return json.dumps({
            "success": False,
            "error": f"文件不存在: {full_path or file_path}",
        }, ensure_ascii=False)

    if ad_full and not os.path.isdir(ad_full):
        return json.dumps({
            "success": False,
            "error": f"附件目录不存在或不是目录: {ad_full}",
        }, ensure_ascii=False)

    try:
        review_id = await start_review(
            file_path=full_path,
            checkpoints_path=cp_full,
            attachments_dir=ad_full,
            sheets=sheets or None,
            source=os.path.basename(full_path),
        )
        return json.dumps({
            "success": True,
            "review_id": review_id,
            "status": "running",
            "status_url": f"/review/{review_id}/status",
            "findings_url": f"/findings/{review_id}",
            "message": "审阅已在后台启动。请轮询 status_url 直到 status=completed，再通过 findings_url 获取结构化结果。大底稿可能耗时数十分钟。",
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"启动审阅失败: {type(e).__name__}: {e}",
        }, ensure_ascii=False)
