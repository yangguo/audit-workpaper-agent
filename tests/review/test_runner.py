import asyncio

import openpyxl
import pytest
from langchain_core.messages import AIMessage

import review.runner as runner
from review.runner import start_review, get_status, cancel_all_running, list_running, _REGISTRY


class _FakeRunnable:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        await asyncio.sleep(0.05)  # simulate a slow review step
        return AIMessage(content=self.content)


class _FakeLLM:
    def __init__(self, content):
        self.content = content

    def bind(self, **kwargs):
        return _FakeRunnable(self.content)


def _pass_payload():
    import json
    return json.dumps({"results": [{
        "id": 1, "status": "pass", "conclusion": "复核不成立结论",
        "evidence_refs": [], "llm_validity": "不成立", "llm_severity": "低",
        "severity": "P2", "reasons": ["理由"], "risk_type": "证据不足",
    }]}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Each test gets a clean registry + fake LLM + temp workspace."""
    _REGISTRY.clear()
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    monkeypatch.setattr(runner, "get_review_llm", lambda: _FakeLLM(_pass_payload()))


def _make_workbook(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SA-4c"
    ws["A1"] = "管理员账号识别情况"
    path = tmp_path / "wp.xlsx"
    wb.save(str(path))
    return str(path)


@pytest.mark.asyncio
async def test_start_review_returns_running_status_immediately(tmp_path):
    wp = _make_workbook(tmp_path)
    review_id = await start_review(file_path=wp, source="wp.xlsx")

    assert isinstance(review_id, str) and len(review_id) == 32
    st = get_status(review_id)
    assert st["status"] in ("running", "completed")  # may have finished fast
    assert st["source"] == "wp.xlsx"


@pytest.mark.asyncio
async def test_review_completes_and_writes_findings(tmp_path):
    wp = _make_workbook(tmp_path)
    review_id = await start_review(file_path=wp, source="wp.xlsx")

    # wait for the background task to finish
    entry = _REGISTRY[review_id]
    await entry["task"]

    st = get_status(review_id)
    assert st["status"] == "completed"
    assert st["stats"]["total_findings"] >= 1

    from storage.findings_store import load_findings
    payload = load_findings(review_id)
    assert payload is not None
    assert payload["findings"][0]["issue_type"] == "特权账号识别范围可能不完整"


@pytest.mark.asyncio
async def test_start_review_cancels_prior_running(tmp_path):
    wp = _make_workbook(tmp_path)
    first = await start_review(file_path=wp, source="first")
    # start a second while the first is still running
    second = await start_review(file_path=wp, source="second")

    # let tasks settle (the cancelled first task raises CancelledError on await)
    import contextlib
    with contextlib.suppress(asyncio.CancelledError):
        await _REGISTRY[first]["task"]
    await _REGISTRY[second]["task"]

    assert _REGISTRY[first]["status"] == "cancelled"
    assert _REGISTRY[second]["status"] == "completed"
    assert list_running() == []


@pytest.mark.asyncio
async def test_cancel_all_running_cancels_in_flight(tmp_path):
    wp = _make_workbook(tmp_path)
    rid = await start_review(file_path=wp, source="wp")
    n = cancel_all_running()
    assert n == 1
    assert _REGISTRY[rid]["status"] == "cancelled"
    # draining the cancelled task does not raise to the caller
    entry = _REGISTRY[rid]
    with contextlib_suppress():
        await entry["task"]


def contextlib_suppress():
    import contextlib
    return contextlib.suppress(asyncio.CancelledError)


@pytest.mark.asyncio
async def test_get_status_unknown_returns_none():
    assert get_status("does-not-exist") is None
