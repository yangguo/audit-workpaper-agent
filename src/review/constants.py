"""Shared keyword constants for the review engine (ported from analyze_excel.py)."""

# Evidence-type keywords appearing in execution text
EVIDENCE_KEYWORDS = (
    "截图", "导出", "清单", "日志", "台账", "审批", "邮件", "报告", "附件", "协议", "工单", "记录",
)

# Keywords indicating interview-only evidence
INTERVIEW_ONLY_KEYWORDS = ("访谈", "询问", "口头", "沟通")

# OS / DB scope keywords (used by sheet-scope checks)
OS_DB_KEYWORDS = ("操作系统", "OS", "数据库", "DB", "DBA", "sa", "root")

# Vocabulary expected to appear in execution as evidence
CHECKPOINT_VOCAB = (
    "系统导出",
    "用户清单",
    "角色清单",
    "权限明细",
    "参数界面",
    "配置截图",
    "变更日志",
    "变更台账",
    "任务清单",
    "批处理",
    "定时任务",
    "作业调度",
    "运行日志",
    "告警",
    "工单",
    "审批",
    "授权",
    "协议",
    "合同",
    "操作系统",
    "数据库",
    "全量",
    "跨期比对",
    "账号创建时间",
    "变更时间",
    "末级权限",
    "权限矩阵",
)
