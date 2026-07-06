import json
import os

import openpyxl
import pytest
from langchain_core.messages import AIMessage

import tools.review_workpaper as rwp
from storage.findings_store import load_findings, save_findings


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


def _pass_review_payload():
    return json.dumps({
        "results": [{
            "id": 1,
            "status": "pass",
            "conclusion": "复核不成立结论",
            "evidence_refs": [],
            "llm_validity": "不成立",
            "llm_severity": "低",
            "severity": "P2",
            "reasons": ["理由"],
            "risk_type": "证据不足",
        }]
    }, ensure_ascii=False)


def test_findings_store_save_and_load_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("COZE_WORKSPACE_PATH", str(tmp_path))
    save_findings("rid123", [{"issue_type": "t", "severity": "P1"}], {"total_findings": 1})
    loaded = load_findings("rid123")
    assert loaded is not None
    assert loaded["review_id"] == "rid123"
    assert loaded["findings"][0]["severity"] == "P1"


def test_findings_store_load_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("COZE_WORKSPACE_PATH", str(tmp_path))
    assert load_findings("does-not-exist") is None


@pytest.mark.asyncio
async def test_review_workpaper_tool_writes_findings(monkeypatch, tmp_path):
    monkeypatch.setenv("COZE_WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    uploads = tmp_path / "assets" / "uploads"
    uploads.mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA-4c"
    ws["A1"] = "管理员账号识别情况"
    xlsx_path = uploads / "test.xlsx"
    wb.save(str(xlsx_path))

    monkeypatch.setattr(rwp, "get_review_llm", lambda: _FakeLLM(_pass_review_payload()))

    result_str = await rwp.review_workpaper.ainvoke({"file_path": "assets/uploads/test.xlsx"})
    result = json.loads(result_str)

    assert result["success"] is True
    assert result["review_id"]
    assert result["total_findings"] == 1
    assert result["findings_url"] == f"/findings/{result['review_id']}"
    assert result["counts_by_severity"]["P1"] == 1

    saved = load_findings(result["review_id"])
    assert saved is not None
    assert saved["stats"]["total_findings"] == 1
    assert saved["findings"][0]["issue_type"] == "特权账号识别范围可能不完整"
    assert saved["findings"][0]["severity_display"] == "中"


@pytest.mark.asyncio
async def test_review_workpaper_tool_missing_file_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("COZE_WORKSPACE_PATH", str(tmp_path))
    result_str = await rwp.review_workpaper.ainvoke({"file_path": "assets/uploads/missing.xlsx"})
    result = json.loads(result_str)
    assert result["success"] is False
    assert "不存在" in result["error"]
