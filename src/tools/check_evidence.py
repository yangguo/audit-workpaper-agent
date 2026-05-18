"""
证据检查工具 - 使用 LLM 检查审计程序中的证据充分性
"""
import json
import re
from typing import List, Dict, Any
from dataclasses import dataclass

import os
from typing import Optional

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

_EVIDENCE_LLM: Optional[ChatOpenAI] = None


def _get_evidence_llm() -> ChatOpenAI:
    global _EVIDENCE_LLM
    if _EVIDENCE_LLM is None:
        api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        _EVIDENCE_LLM = ChatOpenAI(
            model="doubao-seed-1-6-251015",
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )
    return _EVIDENCE_LLM


@dataclass(frozen=True)
class EvidenceCheckResult:
    """证据检查结果"""
    standard: str
    execution: str
    has_evidence: bool
    evidence_type: str
    issues: List[str]
    suggestions: List[str]
    severity: str  # high, medium, low


# 证据类型关键词
EVIDENCE_KEYWORDS = {
    "截图/界面": ["截图", "界面", "配置", "参数", "画面", "屏幕"],
    "导出清单": ["导出", "清单", "列表", "用户清单", "角色清单", "权限明细"],
    "日志/台账": ["日志", "台账", "变更日志", "变更台账", "操作记录", "任务清单"],
    "审批/授权": ["审批", "授权", "批准", "签批", "审批单", "授权书"],
    "协议/合同": ["协议", "合同", "条款", "供应商", "服务协议"],
    "邮件/通知": ["邮件", "通知", "函件", "公文", "备忘录"],
    "报告/文件": ["报告", "文件", "文档", "说明", "附件"],
    "访谈记录": ["访谈", "询问", "口头", "沟通", "会议记录"]
}

# 只需要访谈的关键词
INTERVIEW_ONLY_KEYWORDS = ["访谈", "询问", "口头", "沟通"]

# 检查点词汇（期望在执行中出现的证据）
CHECKPOINT_VOCAB = [
    "系统导出", "用户清单", "角色清单", "权限明细", "参数界面",
    "配置截图", "变更日志", "变更台账", "任务清单", "批处理",
    "定时任务", "作业调度", "运行日志", "告警", "工单",
    "审批", "授权", "协议", "合同", "操作系统", "数据库",
    "全量", "跨期比对", "账号创建时间", "变更时间", "末级权限",
    "权限矩阵"
]


def _extract_evidence_type(text: str) -> List[str]:
    """从文本中提取证据类型"""
    found_types = []
    text_lower = text.lower()
    for ev_type, keywords in EVIDENCE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found_types.append(ev_type)
    return found_types if found_types else ["未明确"]


def _likely_interview_only(standard_text: str, execution_text: str) -> bool:
    """判断是否仅访谈即可"""
    combined = (standard_text + " " + execution_text).lower()
    return any(kw in combined for kw in INTERVIEW_ONLY_KEYWORDS)


def _requires_evidence_by_standard(standard_text: str) -> List[str]:
    """根据标准审计程序判断需要什么类型的证据"""
    required = []
    t = standard_text.lower()
    if any(k in t for k in ["截图", "界面", "参数", "配置"]):
        required.append("截图/界面")
    if any(k in t for k in ["导出", "清单", "用户清单", "权限清单"]):
        required.append("导出清单")
    if any(k in t for k in ["日志", "台账", "变更日志", "变更台账", "任务清单"]):
        required.append("日志/台账")
    if any(k in t for k in ["审批", "授权", "批准"]):
        required.append("审批/授权")
    if any(k in t for k in ["协议", "合同", "供应商"]):
        required.append("协议/合同")
    return required if required else ["其他审计证据"]


@tool
def check_evidence(standard_program: str, execution_text: str) -> str:
    """
    检查执行程序中审计证据的充分性

    使用大语言模型分析标准审计程序和执行内容，评估证据是否充分。

    Args:
        standard_program: 标准审计程序内容
        execution_text: 执行程序的实际内容

    Returns:
        JSON 字符串，包含证据检查结果（是否充分、证据类型、问题、建议）
    """
    # 基础规则检查
    evidence_types = _extract_evidence_type(execution_text)
    required_types = _requires_evidence_by_standard(standard_program)

    is_interview_only = _likely_interview_only(standard_program, execution_text)

    if is_interview_only:
        # 仅访谈的情况
        return json.dumps({
            "standard": standard_program[:200],
            "execution": execution_text[:200],
            "has_evidence": True,
            "evidence_type": "访谈记录",
            "severity": "low",
            "issues": [],
            "suggestions": ["建议记录访谈对象、时间、地点、主要结论"],
            "reason": "该程序主要为访谈类，无需其他形式证据"
        }, ensure_ascii=False, indent=2)

    # 使用 LLM 进行深度分析
    try:
        llm = _get_evidence_llm()

        system_prompt = """你是一名专业的审计底稿审阅专家，擅长评估审计证据的充分性和适当性。

请根据标准审计程序和实际执行内容，评估证据是否充分。

评估维度：
1. 证据充分性：执行内容是否提供了足够的审计证据来支持标准程序
2. 证据适当性：证据类型是否符合审计要求
3. 证据完整性：是否有遗漏的重要证据

请严格按照以下 JSON 格式返回：
{
  "has_evidence": true/false,
  "evidence_type": "证据类型（如：截图/界面、导出清单、日志/台账等）",
  "severity": "high/medium/low",
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"],
  "reason": "判断理由"
}"""

        user_prompt = f"""标准审计程序：
{standard_program}

执行内容：
{execution_text}

请评估上述执行内容中的证据是否充分，并按照要求返回 JSON 结果。"""

        response = llm.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )

        # 解析 LLM 返回的 JSON
        content = response.content
        if isinstance(content, list):
            content = " ".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
        elif not isinstance(content, str):
            content = str(content)

        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            llm_result = json.loads(json_match.group())

            result = {
                "standard": standard_program[:200],
                "execution": execution_text[:200],
                "has_evidence": llm_result.get("has_evidence", False),
                "evidence_type": llm_result.get("evidence_type", evidence_types[0] if evidence_types else "未明确"),
                "severity": llm_result.get("severity", "medium"),
                "issues": llm_result.get("issues", []),
                "suggestions": llm_result.get("suggestions", []),
                "reason": llm_result.get("reason", ""),
                "rule_based_evidence_types": evidence_types,
                "required_types": required_types
            }

            return json.dumps(result, ensure_ascii=False, indent=2)
        else:
            # LLM 未返回有效 JSON，使用规则引擎
            has_evidence = len(evidence_types) > 0 and evidence_types[0] != "未明确"
            severity = "low" if has_evidence else "high"

            result = {
                "standard": standard_program[:200],
                "execution": execution_text[:200],
                "has_evidence": has_evidence,
                "evidence_type": evidence_types[0] if evidence_types else "未明确",
                "severity": severity,
                "issues": [] if has_evidence else ["未发现明确的审计证据"],
                "suggestions": [] if has_evidence else ["建议补充相关证据，如截图、导出清单、日志等"],
                "reason": "基于规则引擎判断",
                "rule_based_evidence_types": evidence_types,
                "required_types": required_types
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        # LLM 调用失败，使用规则引擎
        has_evidence = len(evidence_types) > 0 and evidence_types[0] != "未明确"
        severity = "low" if has_evidence else "high"

        result = {
            "standard": standard_program[:200],
            "execution": execution_text[:200],
            "has_evidence": has_evidence,
            "evidence_type": evidence_types[0] if evidence_types else "未明确",
            "severity": severity,
            "issues": [] if has_evidence else ["未发现明确的审计证据"],
            "suggestions": [] if has_evidence else ["建议补充相关证据"],
            "reason": f"LLM 调用失败: {str(e)}，使用规则引擎判断",
            "error": str(e)
        }

        return json.dumps(result, ensure_ascii=False, indent=2)
