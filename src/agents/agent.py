"""
底稿审阅智能体 - 用于审计底稿的自动化审阅和质量检查
"""
import os
import json
from typing import Annotated
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from storage.memory.memory_saver import get_memory_saver

from tools.analyze_worksheet import analyze_worksheet
from tools.review_workpaper import review_workpaper


LLM_CONFIG = "config/agent_llm_config.json"

MAX_MESSAGES = 40


def _windowed_messages(old, new):
    """滑动窗口: 只保留最近 MAX_MESSAGES 条消息"""
    return add_messages(old, new)[-MAX_MESSAGES:]  # type: ignore


class AgentState(MessagesState):
    messages: Annotated[list[AnyMessage], _windowed_messages]


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def build_agent():
    """构建底稿审阅智能体"""
    workspace_path = os.getenv("WORKSPACE_PATH", os.getcwd())
    config_path = os.path.join(workspace_path, LLM_CONFIG)

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")

    llm = ChatOpenAI(
        model=os.getenv("AGENT_LLM_MODEL", "doubao-seed-2-0-pro-260215"),
        api_key=api_key,
        base_url=base_url,
        temperature=_env_float("AGENT_LLM_TEMPERATURE", 0.7),
        max_tokens=_env_int("AGENT_LLM_MAX_TOKENS", 10000),
        streaming=True,
        timeout=_env_int("AGENT_LLM_TIMEOUT", 600),
    )

    tools_list = [
        analyze_worksheet,
        review_workpaper,
    ]

    return create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools_list,
        checkpointer=get_memory_saver(),
        state_schema=AgentState,
    )
