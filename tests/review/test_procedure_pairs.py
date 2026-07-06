import openpyxl
import pytest
from langchain_core.messages import AIMessage

from review.procedure_pairs import (
    _requires_evidence_by_standard,
    _likely_interview_only,
    _check_procedure_pairs,
    _check_sheet_scope,
    _llm_judge_procedure_pair,
    _llm_check_procedure_pairs,
)


class _FakeRunnable:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self.content)


class _FakeLLM:
    def __init__(self, content):
        self.content = content

    def bind(self, **kwargs):
        return _FakeRunnable(self.content)


def test_requires_evidence_by_standard():
    assert "截图/参数界面" in _requires_evidence_by_standard("获取系统截图界面")
    assert "导出清单" in _requires_evidence_by_standard("导出用户清单")
    assert "审批/授权证据" in _requires_evidence_by_standard("检查审批记录")
    assert list(_requires_evidence_by_standard("无关键词的标准程序")) == []


def test_likely_interview_only():
    assert _likely_interview_only("通过访谈了解权限设置") is True
    assert _likely_interview_only("导出用户清单截图") is False
    assert _likely_interview_only("我们检查了配置") is False


def _build_procedure_ws(standard: str, execution: str, row: int = 5):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws.cell(row=row, column=1, value=standard)
    ws.cell(row=row, column=2, value=execution)
    return ws


def test_check_procedure_pairs_flags_unreplaced_template():
    ws = _build_procedure_ws(
        standard="审计期间获取系统用户清单并检查权限分配情况。",
        execution="如果系统存在以下情况，被认为需要复核方可执行。",
    )
    findings = _check_procedure_pairs("SA-1", ws)
    assert len(findings) == 1
    assert findings[0].issue_type == "执行列疑似未替换模板/未按要求填列"
    assert findings[0].severity == "P0"


def test_check_procedure_pairs_flags_interview_only():
    ws = _build_procedure_ws(
        standard="审计期间访谈了解权限管理流程并记录结果。",
        execution="我们通过访谈了解权限管理流程，未获取其他证据。",
    )
    findings = _check_procedure_pairs("SA-1", ws)
    assert any(f.issue_type == "程序执行不到位/仅依赖访谈" for f in findings)


def test_check_procedure_pairs_no_layout_returns_empty(blank_workbook):
    ws = blank_workbook.active
    ws["A1"] = "无关文本"
    assert _check_procedure_pairs("SA-1", ws) == []


def test_check_sheet_scope_flags_missing_os_db_admins():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "管理员账号识别情况"
    findings = _check_sheet_scope("SA-4c", ws)
    assert len(findings) == 1
    assert findings[0].issue_type == "特权账号识别范围可能不完整"


def test_check_sheet_scope_no_finding_when_os_db_covered():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "管理员账号与操作系统数据库账号核对"
    assert _check_sheet_scope("SA-4c", ws) == []


def test_check_sheet_scope_supplier_without_agreement():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "供应商维护系统管理员账号"
    findings = _check_sheet_scope("PM-5", ws)
    assert len(findings) == 1
    assert findings[0].issue_type == "供应商托管场景证据可能不足"


@pytest.mark.asyncio
async def test_llm_judge_procedure_pair_parses_json(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM('{"status":"fail","reason":"理由文字","evidence_refs":[]}')
    success, is_match, reason, raw = await _llm_judge_procedure_pair(
        llm=llm, standard_text="获取系统用户清单并检查权限。",
        execution_text="我们导出用户清单并核查权限。",
    )
    assert success is True
    assert is_match is False
    assert "理由文字" in reason


@pytest.mark.asyncio
async def test_llm_check_procedure_pairs_flags_mismatch(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A5"] = "审计期间获取系统用户清单并检查权限分配情况。"
    ws["B5"] = "我们导出了系统用户清单并进行了权限核查与记录。"
    llm = _FakeLLM('{"status":"fail","reason":"执行未覆盖关键条件","evidence_refs":[]}')

    report, findings = await _llm_check_procedure_pairs(
        llm=llm, wb=wb, target_sheets=[ws.title], start_row=5, sleep_seconds=0,
    )
    assert report["total"] >= 1
    assert any(f.issue_type.startswith("LLM判定：") for f in findings)
