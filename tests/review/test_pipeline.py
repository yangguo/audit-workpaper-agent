import json

import openpyxl
import pytest
from langchain_core.messages import AIMessage

from review.pipeline import run_review, _parse_sheet_filter, _finding_to_dict
from review.models import Finding


class _FakeRunnable:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self.content)


class _FakeLLM:
    """Returns a canned review result for any LLM call (used by _llm_review_findings)."""
    def __init__(self, content):
        self.content = content

    def bind(self, **kwargs):
        return _FakeRunnable(self.content)


def _pass_review_payload():
    return json.dumps({
        "results": [{
            "id": 1,
            "status": "pass",
            "conclusion": "该发现经复核不成立结论",
            "evidence_refs": [],
            "llm_validity": "不成立",
            "llm_severity": "低",
            "severity": "P2",
            "reasons": ["理由"],
            "risk_type": "证据不足",
        }]
    }, ensure_ascii=False)


def test_parse_sheet_filter():
    assert _parse_sheet_filter(None) is None
    assert _parse_sheet_filter("all") is None
    assert _parse_sheet_filter("SA-4c,SA-5") == ["SA-4c", "SA-5"]
    assert _parse_sheet_filter("SA-4c，SA-5") == ["SA-4c", "SA-5"]


def test_finding_to_dict_parses_json_fields():
    f = Finding(
        issue_type="t", severity="P0", sheet="SA-1", cell="A1",
        snippet="s", basis="b", suggestion="sug",
        evidence_refs='[{"cell_or_range":"A1"}]', reasons='["理由"]',
        fix_suggestion_detail='{"supplement_explanation":"补充"}',
    )
    d = _finding_to_dict(f)
    assert d["evidence_refs"] == [{"cell_or_range": "A1"}]
    assert d["reasons"] == ["理由"]
    assert d["fix_suggestion_detail"] == {"supplement_explanation": "补充"}
    assert d["severity_display"] == "高"


@pytest.mark.asyncio
async def test_run_review_scope_finding_only(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA-4c"
    ws["A1"] = "管理员账号识别情况"
    # no layout, no checkpoints, no preview -> only _check_sheet_scope fires
    llm = _FakeLLM(_pass_review_payload())

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
    )

    assert len(findings) == 1
    f0 = findings[0]
    assert f0["issue_type"] == "特权账号识别范围可能不完整"
    assert f0["severity"] == "P1"
    assert f0["severity_display"] == "中"
    assert f0["llm_status"] == "pass"
    assert f0["cross_validate_issues"] == []
    assert f0["challenge_verdict"] is None
    assert stats["total_findings"] == 1
    assert stats["by_severity"]["P1"] == 1


@pytest.mark.asyncio
async def test_run_review_empty_workbook(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')
    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
    )
    assert findings == []
    assert stats["total_findings"] == 0


@pytest.mark.asyncio
async def test_run_review_falls_back_when_specified_sheet_not_reviewable(monkeypatch):
    """If `sheets` selects a sheet with no layout/checkpoints, fall back to all sheets."""
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    import openpyxl as _ox
    wb = _ox.Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover["A1"] = "封面内容，无审计程序布局"
    ws = wb.create_sheet("SA-4c")
    ws["A1"] = "标准审计程序"
    ws["B1"] = "执行审计程序"
    ws["A5"] = "审计期间获取系统用户清单并检查权限分配情况。"
    ws["B5"] = "我们导出了系统用户清单并进行了权限核查与记录。"
    llm = _FakeLLM('{"status":"pass","reason":"符合","evidence_refs":[]}')

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets="Cover", llm=llm,
    )
    # fell back to all sheets -> SA-4c was reviewed -> procedure_pair LLM call attempted
    assert stats.get("warning"), "expected a fallback warning"
    assert stats["llm_call_stats"].get("procedure_pair", {}).get("calls", 0) >= 1
