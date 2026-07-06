"""Rule-based procedure-pair and sheet-scope checks (ported from analyze_excel.py)."""
from typing import List, Sequence

from openpyxl.utils import get_column_letter

from review.constants import EVIDENCE_KEYWORDS, INTERVIEW_ONLY_KEYWORDS, OS_DB_KEYWORDS
from review.excel_utils import _detect_layout, _extract_sheet_text_cells, _get_cell_value, _truncate
from review.models import Finding


def _likely_interview_only(execution_text: str) -> bool:
    t = execution_text or ""
    if not t:
        return False
    has_interview = any(k in t for k in INTERVIEW_ONLY_KEYWORDS)
    has_evidence = any(k in t for k in EVIDENCE_KEYWORDS)
    return has_interview and not has_evidence


def _requires_evidence_by_standard(standard_text: str) -> Sequence[str]:
    required: List[str] = []
    t = standard_text or ""
    if any(k in t for k in ("截图", "参数", "配置")):
        required.append("截图/参数界面")
    if any(k in t for k in ("导出", "清单", "用户清单", "权限清单")):
        required.append("导出清单")
    if any(k in t for k in ("日志", "台账", "变更日志", "变更台账", "任务清单")):
        required.append("日志/台账/清单")
    if any(k in t for k in ("审批", "授权", "批准")):
        required.append("审批/授权证据")
    if any(k in t for k in ("协议", "合同", "供应商")):
        required.append("协议/合同条款")
    return required


def _check_procedure_pairs(ws_title: str, ws) -> List[Finding]:
    findings: List[Finding] = []
    header_row, standard_col, execution_cols = _detect_layout(ws)
    if header_row is None or standard_col <= 0 or not execution_cols:
        return findings
    start_row = max(5, (header_row or 1) + 2)

    skip_a_exact = {"n/a", "na", "不适用", "有效", "无"}
    skip_a_symbol = {"√", "×", "✓", "✗"}
    skip_c_exact = {"n/a", "na", "不适用"}
    keywords_like_procedure = (
        "询问", "访谈", "检查", "获取", "抽取", "观察", "复核", "比对", "重新执行", "分析", "确认", "审查",
    )
    is_design_section = False
    if header_row and standard_col > 0:
        header_text = _get_cell_value(ws, f"{get_column_letter(standard_col)}{header_row}") or ""
        is_design_section = "设计有效性" in header_text

    empty_streak = 0
    for row in range(start_row, (ws.max_row or 0) + 1):
        row_marker = _get_cell_value(ws, f"A{row}")
        if row_marker:
            m = row_marker.strip()
            if (m.startswith("*") and m[1:].isdigit()) or (m.startswith("#") and m[1:].isdigit()):
                continue
        a_text = _get_cell_value(ws, f"{get_column_letter(standard_col)}{row}")
        has_exec = any(_get_cell_value(ws, f"{get_column_letter(c)}{row}") for c in execution_cols)
        if a_text is None and not has_exec:
            empty_streak += 1
            if empty_streak >= 30:
                break
            continue
        empty_streak = 0

        if a_text is None:
            continue

        a_compact = a_text.replace(" ", "").replace("\n", "").strip()
        if a_compact in skip_a_symbol or a_compact.lower() in skip_a_exact:
            continue
        if len(a_compact) <= 10 and all(ch.isalnum() or ch in "-_./" for ch in a_compact):
            continue
        if not any(k in a_text for k in keywords_like_procedure) and "。" not in a_text and "•" not in a_text:
            continue

        required_evidence = _requires_evidence_by_standard(a_text)
        for exec_col in execution_cols:
            c_cell = f"{get_column_letter(exec_col)}{row}"
            c_text = _get_cell_value(ws, c_cell)
            if c_text is None:
                continue

            row_marker = _get_cell_value(ws, f"A{row}")
            if row_marker:
                m = row_marker.strip()
                if (m.startswith("*") and m[1:].isdigit()) or (m.startswith("#") and m[1:].isdigit()):
                    continue

            c_compact = c_text.replace(" ", "").replace("\n", "").strip()
            if c_compact.lower() in skip_c_exact:
                continue
            if len(c_compact) <= 12 and all(ch.isalnum() or ch in "-_./" for ch in c_compact):
                continue
            if len(a_text) < 20 or len(c_text) < 20:
                continue

            execution_like = (
                ("我们" in c_text)
                or any(k in c_text for k in INTERVIEW_ONLY_KEYWORDS)
                or any(k in c_text for k in EVIDENCE_KEYWORDS)
            )
            if not execution_like:
                template_like = (
                    "•" in c_text
                    or "被认为" in c_text
                    or c_text.strip().startswith(("如果", "以下", "在以下", "根据", "用户参与", "文档包括"))
                )
                if template_like:
                    findings.append(
                        Finding(
                            issue_type="执行列疑似未替换模板/未按要求填列",
                            severity="P0",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="执行列内容更像标准模板/判定口径（如「如果/以下/被认为」及大量条款），缺少「我们获取/检查/抽样/复核」等实际执行描述。",
                            suggestion="将该单元格补充为实际执行步骤与获取证据描述（含样本框定方法、样本来源/编号、证据链接/截图/导出）。",
                        )
                    )
                continue

            if _likely_interview_only(c_text):
                findings.append(
                    Finding(
                        issue_type="程序执行不到位/仅依赖访谈",
                        severity="P1",
                        sheet=ws_title,
                        cell=c_cell,
                        snippet=_truncate(c_text, 220),
                        basis="执行描述出现“访谈/询问/了解”等，但未体现截图、导出清单、日志、台账、审批等实质性证据。",
                        suggestion="补充系统截图/导出清单/日志台账/审批记录等，并在执行程序中明确证据来源与核查步骤。",
                    )
                )

            if required_evidence and not any(k in c_text for k in EVIDENCE_KEYWORDS):
                findings.append(
                    Finding(
                        issue_type="证据类型缺失",
                        severity="P1",
                        sheet=ws_title,
                        cell=c_cell,
                        snippet=_truncate(c_text, 220),
                        basis=f"标准审计程序要求获取/检查证据（{', '.join(required_evidence)}），但执行描述未体现对应证据。",
                        suggestion="对照标准程序逐条补齐证据（截图/清单/日志/审批/协议等），并在底稿中保留可复核的原始文件或路径。",
                    )
                )

            if any(k in a_text for k in ("账号新增", "新增账号", "开通")):
                if "入职" in c_text and not any(k in c_text for k in ("账号创建", "创建时间", "创建日期", "用户清单", "跨期比对")):
                    findings.append(
                        Finding(
                            issue_type="账号新增样本总量基准可能有误",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：样本总量应优先以用户清单“账号创建时间”为基准；仅以入职名单抽样可能遗漏外包/延期开户等。",
                            suggestion="优先获取系统用户清单含账号创建时间字段进行抽样；无该字段时，采用用户清单跨期比对+入职名单交叉验证组合确定样本总量。",
                        )
                    )

            if any(k in a_text for k in ("离职", "禁用", "删除")):
                if "已禁用" in c_text and ("抽样" in c_text or "样本" in c_text) and not any(k in c_text for k in ("离职名单", "全量", "关联", "匹配", "用户清单")):
                    findings.append(
                        Finding(
                            issue_type="离职账号禁用检查方法可能有误",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：不应从“已禁用账户”反向抽样，应将离职名单与用户清单全量关联核查账号状态与禁用时间。",
                            suggestion="获取审计期间离职名单，与系统用户清单关联，全量核查账号状态/禁用时间，必要时补充禁用工单或审批证据。",
                        )
                    )

            if "调岗" in a_text or "岗位变动" in a_text:
                if not any(k in c_text for k in ("权限变更", "权限调整", "角色调整", "禁用", "撤销", "变更")):
                    findings.append(
                        Finding(
                            issue_type="未覆盖调岗权限变更/禁用测试",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：调岗应纳入权限变更/禁用控制测试，仅看账号状态不足以覆盖权限调整实质性测试。",
                            suggestion="获取调岗人员名单与用户清单关联，框定调岗且持有账号人员范围，按调岗前后岗位权限差异抽样核查权限变更/禁用证据。",
                        )
                    )

            if any(k in a_text for k in ("密码策略", "密码", "复杂度", "锁定", "时效")):
                if is_design_section:
                    if not any(k in c_text for k in ("制度", "规程", "政策", "流程", "规定", "办法", "指引", "《", "<")):
                        findings.append(
                            Finding(
                                issue_type="设计有效性证据不足（密码策略）",
                                severity="P2",
                                sheet=ws_title,
                                cell=c_cell,
                                snippet=_truncate(c_text, 220),
                                basis="设计有效性测试通常以制度/流程/政策文件作为证据；当前执行描述未体现已获取/引用相关文件。",
                                suggestion="补充引用密码策略相关制度/规程/政策文件（文件名、条款、编号/链接），并在底稿中说明其适用系统与覆盖范围。",
                            )
                        )
                elif not any(k in c_text for k in ("截图", "参数", "配置", "界面")):
                    findings.append(
                        Finding(
                            issue_type="密码策略证据有效性不足",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：仅文字说明不足以支撑密码策略；应留存参数界面/配置截图等实质性证据。",
                            suggestion="补充密码策略参数界面截图（复杂度/锁定/有效期/历史密码等），并核对底稿描述与系统配置一致。",
                        )
                    )

            if any(k in a_text for k in ("批处理", "定时任务", "任务计划", "job", "Job")):
                if _likely_interview_only(c_text) or not any(k in c_text for k in ("任务", "日志", "清单", "导出")):
                    findings.append(
                        Finding(
                            issue_type="批处理作业证据不足/范围可能未覆盖",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：仅访谈了解批处理设置不充分；应获取任务清单/日志，并覆盖应用层、操作系统、数据库层面。",
                            suggestion="补充应用/OS/DB层面任务清单与执行日志导出，并明确是否覆盖全部相关批处理作业。",
                        )
                    )

            if any(k in a_text for k in ("变更", "发布", "上线", "迁移")):
                if _likely_interview_only(c_text) or not any(k in c_text for k in ("变更台账", "变更日志", "台账", "日志", "工单")):
                    findings.append(
                        Finding(
                            issue_type="系统变更证据不足/样本框定可能有误",
                            severity="P1",
                            sheet=ws_title,
                            cell=c_cell,
                            snippet=_truncate(c_text, 220),
                            basis="常见问题：应以变更日志/变更台账为样本总量基准抽样审批；仅依赖访谈或从审批流程反向框定无法验证“变更均经审批”。",
                            suggestion="获取变更日志/台账作为总体，按期间抽样追溯审批与测试/上线证据；补充工单、发布记录、回滚记录等。",
                        )
                    )

    return findings


def _check_sheet_scope(ws_title: str, ws) -> List[Finding]:
    findings: List[Finding] = []
    sheet_text = " ".join(text for _, text in _extract_sheet_text_cells(ws))

    if ws_title in {"SA-4c"}:
        if ("管理员" in sheet_text or "特权" in sheet_text) and not any(k in sheet_text for k in OS_DB_KEYWORDS):
            findings.append(
                Finding(
                    issue_type="特权账号识别范围可能不完整",
                    severity="P1",
                    sheet=ws_title,
                    cell=None,
                    snippet=_truncate(sheet_text, 220),
                    basis="常见问题：项目检查范围未覆盖操作系统与数据库层面的管理员账号设置情况，可能导致特权账号识别不完整。",
                    suggestion="补充获取并核对OS/DB层面管理员账号清单（或截图/导出），并评估与应用层管理员职责冲突与共享风险。",
                )
            )

    if ws_title in {"PM-5", "PM-6", "PM-4b", "PM-4c", "PM-4e", "PM-3"}:
        if "供应商" in sheet_text and not any(k in sheet_text for k in ("协议", "合同", "SaaS", "托管", "权利义务")):
            findings.append(
                Finding(
                    issue_type="供应商托管场景证据可能不足",
                    severity="P1",
                    sheet=ws_title,
                    cell=None,
                    snippet=_truncate(sheet_text, 220),
                    basis="常见问题：供应商维护/托管时需获取相关协议文件检查双方权利义务与实际履行情况。",
                    suggestion="补充协议/合同/运维报告/工单等证据，明确管理员账号归属（租户级权限）与监控复核责任。",
                )
            )

    return findings
