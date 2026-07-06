"""Async LLM-call infrastructure for the review engine.

Adapted from analyze_excel.py: replaces the sync OpenAI SDK + ThreadPoolExecutor
with async calls over langchain_openai.ChatOpenAI so it fits the project's
async LangGraph agent. No jsonschema dependency.
"""
import asyncio
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from review.validation import _validate_finding_result, _validate_llm_results

LLM_CALL_STATS: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

_ROLE_TO_MSG = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


def _llm_stat(stage: str, key: str, n: int = 1) -> None:
    if not stage or not key:
        return
    try:
        LLM_CALL_STATS[str(stage)][str(key)] += int(n)
    except Exception:
        return


def _classify_llm_error(err: Exception) -> str:
    s = str(err or "").strip().lower()
    if not s:
        return "other"
    if "timed out" in s or "timeout" in s:
        return "timeout"
    if "rate limit" in s or "429" in s:
        return "rate_limit"
    if "context length" in s or "maximum context" in s or "max tokens" in s:
        return "context"
    if "json" in s and ("parse" in s or "nonjson" in s or "非json" in s):
        return "parse"
    if "502" in s or "503" in s or "504" in s or "bad gateway" in s or "gateway" in s:
        return "server"
    return "other"


def _backoff_scale() -> float:
    try:
        return max(0.0, float(os.getenv("REVIEW_LLM_BACKOFF_SCALE", "1.0")))
    except Exception:
        return 1.0


async def _llm_backoff_sleep(attempt: int, err_type: str) -> None:
    base = 1.2 * max(1, int(attempt))
    if err_type == "rate_limit":
        base = max(base, 6.0) * max(1, int(attempt))
    elif err_type in {"server", "timeout"}:
        base = max(base, 3.0) * max(1, int(attempt))
    await asyncio.sleep(min(30.0, base) * _backoff_scale())


def _to_langchain_messages(messages: List[Dict[str, str]]) -> List[Any]:
    out = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        cls = _ROLE_TO_MSG.get(role, HumanMessage)
        out.append(cls(content=content))
    return out


async def _llm_chat(
    *,
    llm,
    messages: List[Dict[str, str]],
    stage: str,
    max_attempts: int = 3,
    max_tokens: int = 2048,
) -> str:
    """Call the LLM with retry/backoff. Returns the response content string."""
    lc_messages = _to_langchain_messages(messages)
    bound = llm.bind(max_tokens=max_tokens)
    last_error: Optional[str] = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            _llm_stat(stage, "calls", 1)
            resp = await bound.ainvoke(lc_messages)
            content = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            elif not isinstance(content, str):
                content = str(content)
            _llm_stat(stage, "ok", 1)
            return content or ""
        except Exception as e:
            last_error = str(e)
            err_type = _classify_llm_error(e)
            _llm_stat(stage, f"error_{err_type}", 1)
            if attempt < max_attempts:
                await _llm_backoff_sleep(attempt, err_type)
            continue
    raise RuntimeError(last_error or "LLM调用失败")


def _try_parse_json(text: str):
    if not text:
        return None
    s = str(text).strip()
    start = None
    for i, ch in enumerate(s):
        if ch in "[{":
            start = i
            break
    if start is None:
        return None
    try:
        return json.loads(s[start:])
    except Exception:
        return None


async def _llm_request_json_list(
    *,
    llm,
    system_prompt: str,
    user_prompt: str,
    stage: str,
    max_attempts: int = 3,
) -> Tuple[Optional[List[Any]], Optional[str]]:
    """Call the LLM expecting a JSON list response ({results: [...]}).

    Retries on JSON parse / schema validation failures. Each item is validated
    and repaired via review.validation. Returns (parsed_list_or_None, error).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Optional[str] = None
    last_validation_errors: List[str] = []
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            current_messages = messages
            if last_validation_errors and attempt > 1:
                err_text = "；".join(last_validation_errors[:3])
                retry_note = (
                    f"\n\n[Retry hint] 上一次输出未通过结构化校验，问题：{err_text}。"
                    f"请严格按 system 字段定义重新输出，"
                    f"确保 status=pass/fail/unknown、severity=P0/P1/P2、"
                    f"fail 时 evidence_refs 必填且 excerpt 逐字来自原文。"
                )
                current_messages = [
                    messages[0],
                    {"role": "user", "content": user_prompt + retry_note},
                ]
            content = await _llm_chat(
                llm=llm, messages=current_messages, stage=stage,
                max_attempts=3, max_tokens=2048,
            )
            parsed = _try_parse_json(content)
            if isinstance(parsed, dict):
                parsed = parsed.get("results") or parsed.get("data") or parsed.get("items")
            if not isinstance(parsed, list):
                raise RuntimeError("LLM返回非JSON results 数组")
            valid_items, needs_retry = _validate_llm_results(parsed)
            if needs_retry:
                last_validation_errors = []
                for obj in parsed:
                    if isinstance(obj, dict):
                        ok, errs = _validate_finding_result(obj)
                        if not ok:
                            last_validation_errors.extend(errs)
                if not last_validation_errors:
                    last_validation_errors = ["部分结果无法通过结构化校验"]
                if attempt < max_attempts:
                    _llm_stat(stage, "error_schema", 1)
                    await asyncio.sleep(min(8.0, 1.5 * attempt) * _backoff_scale())
                    continue
                parsed = valid_items
            return parsed, None
        except Exception as e:
            last_error = str(e)
            is_parse_error = "json" in str(e).lower() or "parse" in str(e).lower() or "非json" in str(e)
            if is_parse_error and attempt < max_attempts:
                _llm_stat(stage, "error_parse", 1)
                await asyncio.sleep(min(8.0, 1.5 * attempt) * _backoff_scale())
                continue
            if not is_parse_error:
                break
    return None, last_error or "LLM调用失败"


def get_review_llm() -> ChatOpenAI:
    """Build the ChatOpenAI used by the review engine, from project env."""
    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("REVIEW_LLM_MODEL", "doubao-seed-1-6-251015")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        max_retries=0,
        streaming=False,
    )
