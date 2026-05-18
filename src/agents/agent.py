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
from tools.check_evidence import check_evidence
from tools.verify_attachments import verify_attachments


LLM_CONFIG = "config/agent_llm_config.json"

MAX_MESSAGES = 40


def _windowed_messages(old, new):
    """滑动窗口: 只保留最近 MAX_MESSAGES 条消息"""
    return add_messages(old, new)[-MAX_MESSAGES:]  # type: ignore


class AgentState(MessagesState):
    messages: Annotated[list[AnyMessage], _windowed_messages]


def build_agent():
    """构建底稿审阅智能体"""
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", os.getcwd())
    config_path = os.path.join(workspace_path, LLM_CONFIG)

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL")

    llm = ChatOpenAI(
        model=cfg['config'].get("model"),
        api_key=api_key,
        base_url=base_url,
        temperature=cfg['config'].get('temperature', 0.7),
        streaming=True,
        timeout=cfg['config'].get('timeout', 600),
    )

    tools_list = [
        analyze_worksheet,
        check_evidence,
        verify_attachments,
    ]

    return create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools_list,
        checkpointer=get_memory_saver(),
        state_schema=AgentState,
    )
