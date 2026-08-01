import asyncio
import contextlib
import threading

import openpyxl
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

import review.runner as runner
from review.runner import start_review, get_status, cancel_all_running, list_running, _REGISTRY
from storage.findings_store import load_findings
from storage.review_artifact_store import ReviewArtifactStore


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


@pytest_asyncio.fixture(autouse=True)
async def _isolate(monkeypatch, tmp_path):
    """Each test gets a clean registry + fake LLM + temp workspace."""
    _REGISTRY.clear()
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    monkeypatch.setattr(runner, "get_review_llm", lambda: _FakeLLM(_pass_payload()))
    yield

    review_tasks = [
        entry["task"]
        for entry in _REGISTRY.values()
        if isinstance(entry.get("task"), asyncio.Task) and not entry["task"].done()
    ]
    for task in review_tasks:
        task.cancel()
    if review_tasks:
        await asyncio.gather(*review_tasks, return_exceptions=True)

    shadow_tasks = [
        entry["shadow_task"]
        for entry in _REGISTRY.values()
        if isinstance(entry.get("shadow_task"), asyncio.Task)
        and not entry["shadow_task"].done()
    ]
    if shadow_tasks:
        await asyncio.gather(*shadow_tasks, return_exceptions=True)


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
async def test_completed_review_starts_shadow_artifact_without_changing_v1_result(tmp_path):
    review_id = await start_review(file_path=_make_workbook(tmp_path), source="wp.xlsx")

    await _REGISTRY[review_id]["task"]
    await _REGISTRY[review_id]["shadow_task"]

    assert get_status(review_id)["status"] == "completed"
    assert get_status(review_id)["artifact_status"] == "completed"
    assert load_findings(review_id)["review_id"] == review_id
    assert ReviewArtifactStore().load_manifest(review_id)["artifact_status"] == "completed"


@pytest.mark.asyncio
async def test_shadow_failure_does_not_fail_existing_review(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner,
        "build_evidence_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    review_id = await start_review(file_path=_make_workbook(tmp_path), source="wp.xlsx")

    await _REGISTRY[review_id]["task"]
    await _REGISTRY[review_id]["shadow_task"]

    assert get_status(review_id)["status"] == "completed"
    assert get_status(review_id)["artifact_status"] == "error"
    assert load_findings(review_id) is not None


@pytest.mark.asyncio
async def test_shadow_artifact_capture_keeps_event_loop_responsive(monkeypatch, tmp_path):
    release_capture = threading.Event()
    original_build_input_files = runner.build_input_files

    def _blocked_build_input_files(*args, **kwargs):
        release_capture.wait(timeout=0.2)
        return original_build_input_files(*args, **kwargs)

    monkeypatch.setattr(runner, "build_input_files", _blocked_build_input_files)
    review_id = "shadow-responsive"
    _REGISTRY[review_id] = {"status": "completed"}
    shadow_task = asyncio.create_task(
        runner._capture_shadow_artifact(
            review_id=review_id,
            file_path=_make_workbook(tmp_path),
            checkpoints_path="",
            attachments_preview_path="",
            sheets=None,
            source="wp.xlsx",
            findings=[],
            stats={},
        )
    )

    timer = threading.Timer(0.2, release_capture.set)
    timer.start()
    try:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await asyncio.sleep(0.01)
        assert loop.time() - started_at < 0.1
    finally:
        release_capture.set()
        timer.cancel()
        await shadow_task


@pytest.mark.asyncio
async def test_cancelled_shadow_capture_retains_its_original_workspace(monkeypatch, tmp_path):
    capture_started = threading.Event()
    release_capture = threading.Event()
    capture_finished = threading.Event()
    observed = {}
    original_build_input_files = runner.build_input_files

    class _RecordingArtifactStore:
        def __init__(self, *, workspace_path=None):
            self.workspace_path = workspace_path

        def begin(self, manifest):
            observed["workspace_path"] = self.workspace_path or runner.os.getenv(
                "WORKSPACE_PATH"
            )

        def write_evidence(self, review_id, graph):
            return None

        def write_v1_findings(self, review_id, findings, stats):
            return None

        def complete(self, review_id):
            capture_finished.set()
            return None

        def fail(self, review_id, error):
            capture_finished.set()
            return None

    def _blocked_build_input_files(*args, **kwargs):
        capture_started.set()
        release_capture.wait(timeout=0.5)
        return original_build_input_files(*args, **kwargs)

    monkeypatch.setattr(runner, "ReviewArtifactStore", _RecordingArtifactStore)
    monkeypatch.setattr(runner, "build_input_files", _blocked_build_input_files)
    review_id = "shadow-cleanup"
    _REGISTRY[review_id] = {"status": "completed"}
    shadow_task = asyncio.create_task(
        runner._capture_shadow_artifact(
            review_id=review_id,
            file_path=_make_workbook(tmp_path),
            checkpoints_path="",
            attachments_preview_path="",
            sheets=None,
            source="wp.xlsx",
            findings=[],
            stats={},
        )
    )

    await asyncio.to_thread(capture_started.wait, 0.5)
    shadow_task.cancel()
    await asyncio.gather(shadow_task, return_exceptions=True)
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "restored-workspace"))
    release_capture.set()
    try:
        await asyncio.wait_for(asyncio.to_thread(capture_finished.wait, 0.5), 0.6)
        assert observed["workspace_path"] == str(tmp_path)
    finally:
        release_capture.set()
        await asyncio.to_thread(capture_finished.wait, 0.5)


@pytest.mark.asyncio
async def test_start_review_cancels_prior_running(tmp_path):
    wp = _make_workbook(tmp_path)
    first = await start_review(file_path=wp, source="first")
    # start a second while the first is still running
    second = await start_review(file_path=wp, source="second")

    # let tasks settle (the cancelled first task raises CancelledError on await)
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
    return contextlib.suppress(asyncio.CancelledError)


@pytest.mark.asyncio
async def test_get_status_unknown_returns_none():
    assert get_status("does-not-exist") is None
