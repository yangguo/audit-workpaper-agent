"""
附件验证工具 - 验证底稿中的附件引用是否匹配
"""
import os
import json
import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

from langchain.tools import tool
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context


# 附件文件名正则
ATTACHMENT_FILE_RE = re.compile(
    r"([0-9A-Za-z_\-\.\u4e00-\u9fff]+?\.(?:png|jpg|jpeg|pdf|xlsx|xls|docx|doc))",
    re.IGNORECASE,
)

# 附件路径正则
ATTACHMENT_PATH_RE = re.compile(
    r"([0-9A-Za-z_\-\.\u4e00-\u9fff]+(?:[\\/][0-9A-Za-z_\-\.\u4e00-\u9fff]+)+\.(?:png|jpg|jpeg|pdf|xlsx|xls|docx|doc))",
    re.IGNORECASE,
)

# 附件索引正则
ATTACHMENT_INDEX_RE = re.compile(r"(?:附件|证据|图片|截图|索引|目录索引)\s*([0-9]{1,3})")


@dataclass(frozen=True)
class AttachmentRef:
    """附件引用"""
    ref_type: str  # filename, path, index
    value: str
    context: str
    position: int


@dataclass(frozen=True)
class VerificationResult:
    """验证结果"""
    ref_type: str
    ref_value: str
    is_found: bool
    matched_files: List[str]
    suggestions: List[str]


def _extract_attachment_refs(text: str) -> Tuple[List[str], List[str], List[str]]:
    """从文本中提取附件引用"""
    s = (text or "").strip()
    if not s:
        return [], [], []

    rel_paths = [m.group(1) for m in ATTACHMENT_PATH_RE.finditer(s)]
    filenames = [m.group(1) for m in ATTACHMENT_FILE_RE.finditer(s)]
    indices = [m.group(1) for m in ATTACHMENT_INDEX_RE.finditer(s)]

    return filenames, rel_paths, indices


def _normalize_filename(filename: str) -> str:
    """规范化文件名"""
    return filename.lower().replace(" ", "").replace("_", "").replace("-", "")


def _find_matching_files(
    target_filename: str,
    search_paths: List[str],
    workspace_path: str
) -> List[str]:
    """在指定路径中查找匹配的文件"""
    matches = []
    target_normalized = _normalize_filename(target_filename)

    for search_path in search_paths:
        if not os.path.isabs(search_path):
            full_path = os.path.join(workspace_path, search_path)
        else:
            full_path = search_path

        if not os.path.exists(full_path):
            continue

        if os.path.isfile(full_path):
            # 单个文件
            if _normalize_filename(os.path.basename(full_path)) == target_normalized:
                matches.append(full_path)
        elif os.path.isdir(full_path):
            # 目录
            for root, dirs, files in os.walk(full_path):
                for file in files:
                    if _normalize_filename(file) == target_normalized:
                        matches.append(os.path.join(root, file))

    return matches


@tool
def verify_attachments(
    execution_text: str,
    search_paths: str = "assets",
    filename_list: str = ""
) -> str:
    """
    验证底稿执行内容中的附件引用是否存在

    Args:
        execution_text: 执行程序的文本内容
        search_paths: 搜索路径（多个路径用逗号分隔，相对于项目根目录）
        filename_list: 已知附件文件名列表（JSON 数组格式）

    Returns:
        JSON 字符串，包含附件验证结果（引用的附件、是否找到、匹配文件、建议）
    """
    ctx = request_context.get() or new_context(method="verify_attachments")

    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")

    # 解析搜索路径
    if search_paths:
        paths = [p.strip() for p in search_paths.split(",")]
    else:
        paths = ["assets"]

    # 解析已知文件名列表
    known_filenames = []
    if filename_list:
        try:
            known_filenames = json.loads(filename_list)
            if not isinstance(known_filenames, list):
                known_filenames = []
        except json.JSONDecodeError:
            pass

    # 提取附件引用
    filenames, rel_paths, indices = _extract_attachment_refs(execution_text)

    results = []

    # 验证文件名引用
    for filename in filenames:
        if not filename:
            continue

        # 在搜索路径中查找
        matched = _find_matching_files(filename, paths, workspace_path)

        # 在已知文件名列表中查找
        if not matched and known_filenames:
            for known_file in known_filenames:
                if _normalize_filename(known_file) == _normalize_filename(filename):
                    matched.append(known_file)

        result = VerificationResult(
            ref_type="filename",
            ref_value=filename,
            is_found=len(matched) > 0,
            matched_files=matched,
            suggestions=[] if matched else [f"未找到文件: {filename}，请检查文件名是否正确或文件是否已上传"]
        )
        results.append({
            "ref_type": result.ref_type,
            "ref_value": result.ref_value,
            "is_found": result.is_found,
            "matched_files": result.matched_files,
            "suggestions": result.suggestions
        })

    # 验证路径引用
    for path in rel_paths:
        if not path:
            continue

        full_path = os.path.join(workspace_path, path)
        is_found = os.path.exists(full_path)

        result = VerificationResult(
            ref_type="path",
            ref_value=path,
            is_found=is_found,
            matched_files=[full_path] if is_found else [],
            suggestions=[] if is_found else [f"路径不存在: {path}"]
        )
        results.append({
            "ref_type": result.ref_type,
            "ref_value": result.ref_value,
            "is_found": result.is_found,
            "matched_files": result.matched_files,
            "suggestions": result.suggestions
        })

    # 验证索引引用（如果有已知文件列表）
    if indices and known_filenames:
        for idx in indices:
            try:
                index_num = int(idx)
                if 1 <= index_num <= len(known_filenames):
                    matched_file = known_filenames[index_num - 1]
                    full_path = os.path.join(workspace_path, matched_file)
                    is_found = os.path.exists(full_path) if not os.path.isabs(matched_file) else os.path.exists(matched_file)

                    result = VerificationResult(
                        ref_type="index",
                        ref_value=f"索引{idx}",
                        is_found=is_found,
                        matched_files=[matched_file],
                        suggestions=[] if is_found else [f"索引{idx}对应的文件不存在"]
                    )
                    results.append({
                        "ref_type": result.ref_type,
                        "ref_value": result.ref_value,
                        "is_found": result.is_found,
                        "matched_files": result.matched_files,
                        "suggestions": result.suggestions
                    })
            except (ValueError, IndexError):
                pass

    # 统计信息
    total_refs = len(results)
    found_count = sum(1 for r in results if r["is_found"])
    not_found_count = total_refs - found_count

    return json.dumps({
        "execution_text": execution_text[:200],
        "total_references": total_refs,
        "found_count": found_count,
        "not_found_count": not_found_count,
        "search_paths": paths,
        "verification_results": results,
        "summary": f"共发现{total_refs}个附件引用，其中{found_count}个找到，{not_found_count}个未找到"
    }, ensure_ascii=False, indent=2)
