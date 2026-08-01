"""Tests for the understood-requirement helpers and streamed-run wiring in main.py."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import main as main_mod
from main import (
    GraphService,
    _build_understood_requirement,
    _extract_review_summary,
    _extract_tool_call_info,
)
from utils.context import new_context


def _ai_with_tool_call(args: dict, tc_id: str = "call1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "review_workpaper", "args": args, "id": tc_id, "type": "tool_call"}],
    )


def _tool_result(payload: dict, tc_id: str = "call1") -> ToolMessage:
    return ToolMessage(
        name="review_workpaper",
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=tc_id,
    )


# ---- _extract_tool_call_info ----

def test_extract_returns_none_when_no_review_call():
    msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
    assert _extract_tool_call_info(msgs) is None


def test_extract_captures_args_from_ai_message_and_return_from_tool_message():
    msgs = [
        _ai_with_tool_call({
            "file_path": "assets/uploads/wp.xlsx",
            "checkpoints_path": "assets/uploads/cp.xlsx",
            "attachments_dir": "",
            "sheets": "PE-6",
        }),
        _tool_result({"review_id": "rid1", "status": "running"}),
    ]
    info = _extract_tool_call_info(msgs)
    assert info is not None
    assert info["args"]["sheets"] == "PE-6"
    assert info["return_value"]["review_id"] == "rid1"
    assert info["return_value"]["status"] == "running"


def test_extract_captures_args_even_before_tool_returns():
    """At stream time the AIMessage(tool_calls) arrives before the ToolMessage.
    The extractor should still return args with an empty return_value."""
    msgs = [_ai_with_tool_call({"file_path": "wp.xlsx", "sheets": "SA-4c"})]
    info = _extract_tool_call_info(msgs)
    assert info is not None
    assert info["args"]["sheets"] == "SA-4c"
    assert info["return_value"] == {}


def test_extract_ignores_other_tools():
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "analyze_worksheet", "args": {"file_path": "x.xlsx"}, "id": "c1", "type": "tool_call"}]),
        _ai_with_tool_call({"file_path": "wp.xlsx", "sheets": ""}),
    ]
    info = _extract_tool_call_info(msgs)
    assert info is not None
    assert info["args"]["file_path"] == "wp.xlsx"


# ---- _build_understood_requirement ----

def test_build_summary_single_sheet_with_checkpoints_and_attachment_directory():
    info = {
        "args": {
            "file_path": "assets/uploads/C22 IT一般控制测试2025v5.xlsx",
            "checkpoints_path": "assets/uploads/检查要点.xlsx",
            "attachments_dir": "assets/uploads/attachments/dir-1",
            "sheets": "PE-6",
        },
        "return_value": {"review_id": "rid1", "status": "running"},
    }
    out = _build_understood_requirement(info)
    assert out["scope"] == "PE-6"
    assert out["sheets_raw"] == "PE-6"
    assert out["workpaper"] == "C22 IT一般控制测试2025v5.xlsx"
    assert out["checkpoints"] == "检查要点.xlsx"
    assert out["attachments_dir"] == "dir-1"
    assert out["review_id"] == "rid1"
    assert out["status"] == "running"
    assert "PE-6" in out["summary"]
    assert "检查要点：检查要点.xlsx" in out["summary"]
    assert "附件目录：dir-1" in out["summary"]


def test_build_summary_empty_sheets_means_all_sheets():
    info = {"args": {"file_path": "wp.xlsx", "sheets": ""}, "return_value": {}}
    out = _build_understood_requirement(info)
    assert out["scope"] == "全部 Sheet"
    assert out["checkpoints"] is None
    assert out["attachments_dir"] is None
    assert "全部 Sheet" in out["summary"]
    # no extras -> no "含" clause
    assert "含" not in out["summary"]


def test_build_summary_multiple_sheets_preserved_as_raw():
    info = {"args": {"file_path": "wp.xlsx", "sheets": "pe6,sa-4c"}, "return_value": {}}
    out = _build_understood_requirement(info)
    assert out["scope"] == "pe6,sa-4c"
    assert out["sheets_raw"] == "pe6,sa-4c"


def test_build_summary_missing_file_path_shows_unspecified():
    info = {"args": {"sheets": "SA-4c"}, "return_value": {}}
    out = _build_understood_requirement(info)
    assert out["workpaper"] == "（未指定）"


# ---- _extract_review_summary backward compat ----

def test_extract_review_summary_returns_dict_with_review_id():
    msgs = [
        _ai_with_tool_call({"file_path": "wp.xlsx", "sheets": "PE-6"}),
        _tool_result({"review_id": "rid9", "status": "running"}),
    ]
    summary = _extract_review_summary(msgs)
    assert summary is not None
    assert summary["review_id"] == "rid9"
    assert summary["status"] == "running"
    assert summary["scope"] == "PE-6"


def test_extract_review_summary_none_when_absent():
    assert _extract_review_summary([AIMessage(content="hi")]) is None


# ---- GraphService.run_streamed ----

class _FakeGraph:
    """Yields canned astream chunks (stream_mode='updates' shape).

    Simplification: the real `CompiledStateGraph.astream` is an async method
    returning an async iterator and validates `stream_mode`; this fake is a
    plain method returning an async generator and ignores `stream_mode`. The
    chunk shape it yields — `{node_name: {"messages": [...]}}` — matches the
    real `stream_mode="updates"` output (verified against langgraph 1.0.2),
    which is all `run_streamed` consumes. If `run_streamed`'s streaming
    contract changes, re-validate against the real API.
    """

    def __init__(self, chunks):
        self._chunks = chunks

    def astream(self, payload, config=None, stream_mode=None):
        return self._aiter()

    async def _aiter(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_run_streamed_accumulates_messages_and_invokes_callback(monkeypatch):
    """run_streamed should accumulate messages from every node update and call
    on_messages after each, so the caller can extract tool info mid-flight.

    Also verifies the understood-requirement enriches across stages: after the
    AIMessage(tool_calls) the review_id is unknown; after the ToolMessage it
    becomes known. The caller's dedup signature must include review_id/status
    so this enrichment fires as a second update (not be silently dropped).
    """
    chunks = [
        {"agent": {"messages": [_ai_with_tool_call({"file_path": "wp.xlsx", "sheets": "PE-6"})]}},
        {"tools": {"messages": [_tool_result({"review_id": "rid1", "status": "running"})]}},
        {"agent": {"messages": [AIMessage(content="审阅已启动")]}},
    ]
    service = GraphService()
    monkeypatch.setattr(service, "_get_graph", lambda: _FakeGraph(chunks))

    stages: list = []

    def on_messages(msgs):
        understood = _extract_review_summary(msgs)
        stages.append(understood.get("review_id") if understood else None)

    ctx = new_context(method="http")
    result = await service.run_streamed({"messages": []}, ctx, on_messages=on_messages)

    msgs = result["messages"]
    assert len(msgs) == 3
    # callback fired once per node update (3 stages)
    assert len(stages) == 3
    # stage 1 (AIMessage only): review_id unknown; stage 2 (ToolMessage): enriched
    assert stages[0] is None, f"pre-return stage should have no review_id: {stages[0]!r}"
    assert stages[1] == "rid1", f"post-return stage should be enriched: {stages[1]!r}"
    assert stages[2] == "rid1"
    # final accumulation has the tool call + result + final AI text
    assert _extract_review_summary(msgs)["review_id"] == "rid1"
    assert any(getattr(m, "type", "") == "ai" and m.content == "审阅已启动" for m in msgs)


@pytest.mark.asyncio
async def test_run_streamed_handles_empty_chunks_gracefully(monkeypatch):
    service = GraphService()
    monkeypatch.setattr(service, "_get_graph", lambda: _FakeGraph([{}, {"agent": {}}]))
    ctx = new_context(method="http")
    result = await service.run_streamed({"messages": []}, ctx)
    assert result["messages"] == []
