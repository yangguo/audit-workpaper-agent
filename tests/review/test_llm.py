import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from review.llm import (
    LLM_CALL_STATS,
    _classify_llm_error,
    _to_langchain_messages,
    _try_parse_json,
    _llm_chat,
    _llm_stat,
)


class _FakeRunnable:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        outcome = self.outcomes[(self.calls - 1) % len(self.outcomes)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeLLM:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.bound = None

    def bind(self, **kwargs):
        self.bound = _FakeRunnable(self.outcomes)
        return self.bound


def test_classify_llm_error():
    assert _classify_llm_error(RuntimeError("Connection timed out")) == "timeout"
    assert _classify_llm_error(RuntimeError("rate limit hit 429")) == "rate_limit"
    assert _classify_llm_error(RuntimeError("context length exceeded")) == "context"
    assert _classify_llm_error(RuntimeError("502 bad gateway")) == "server"
    assert _classify_llm_error(RuntimeError("something else")) == "other"
    assert _classify_llm_error(RuntimeError("")) == "other"


def test_try_parse_json():
    assert _try_parse_json('{"results": [1, 2]}') == {"results": [1, 2]}
    # leading noise is tolerated (slices from the first { )
    assert _try_parse_json('noise {"a": 1}') == {"a": 1}
    # trailing garbage after the JSON object is NOT tolerated (matches reference)
    assert _try_parse_json('noise {"a": 1} tail') is None
    assert _try_parse_json("no json here") is None
    assert _try_parse_json("") is None


def test_to_langchain_messages():
    msgs = _to_langchain_messages([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ])
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert isinstance(msgs[2], AIMessage)


def test_llm_stat_tracks_counts():
    LLM_CALL_STATS.clear()
    _llm_stat("stage1", "calls", 1)
    _llm_stat("stage1", "calls", 1)
    assert LLM_CALL_STATS["stage1"]["calls"] == 2


@pytest.mark.asyncio
async def test_llm_chat_returns_content_on_success(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([AIMessage(content="hello")])
    out = await _llm_chat(
        llm=llm, messages=[{"role": "user", "content": "hi"}],
        stage="t", max_attempts=1, max_tokens=64,
    )
    assert out == "hello"


@pytest.mark.asyncio
async def test_llm_chat_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([
        RuntimeError("timed out"),
        RuntimeError("timed out"),
        AIMessage(content="ok"),
    ])
    out = await _llm_chat(
        llm=llm, messages=[{"role": "user", "content": "hi"}],
        stage="t", max_attempts=3, max_tokens=64,
    )
    assert out == "ok"
    assert llm.bound.calls == 3


@pytest.mark.asyncio
async def test_llm_chat_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    llm = _FakeLLM([RuntimeError("timed out")])
    with pytest.raises(RuntimeError):
        await _llm_chat(
            llm=llm, messages=[{"role": "user", "content": "hi"}],
            stage="t", max_attempts=2, max_tokens=64,
        )
    assert LLM_CALL_STATS["t"]["error_timeout"] >= 1
