# 受限证据调查 Agent 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有确定性附件索引和审阅规则之上增加一个受限证据调查 Agent，用于处理附件引用模糊、内容未解析和跨文件核对场景，并把经校验的证据重新提供给现有审阅 LLM。

**Architecture:** 审阅输入先由 `ReviewArtifactStore` 快照，目录索引只暴露快照内的相对路径、文件元数据和已提取文本。只有触发 fallback 条件的 Sheet 才启动一次无记忆 Agent；Agent 只能调用列目录、全文检索和读取已索引附件三个工具，不能执行 shell、写文件或访问快照外路径。Agent 不直接产出 P0/P1/P2 结论，而是返回候选证据和未解决事项；服务端验证路径和摘录后，将候选证据加入现有 checkpoint/evidence-step LLM 上下文，最终仍由原有 Finding 校验和规则链输出结果。

**Tech Stack:** Python 3.12, LangChain `create_agent`, LangGraph-compatible async pipeline, pytest/pytest-asyncio, existing `openpyxl`/attachment index.

### Task 1: 定义 Agent 数据契约和安全边界

**Files:**
- Create: `src/review/evidence_agent.py`
- Test: `tests/review/test_evidence_agent.py`

**Step 1: Write the failing tests**

- 目录工具只返回索引中的相对路径、类型、大小和解析状态。
- `search_attachment_text` 返回真实提取文本的精确片段。
- `read_attachment` 拒绝绝对路径、`..` 路径和未被索引的文件。
- Agent 返回的证据路径必须能唯一映射到索引项，摘录必须是源文本子串；伪造路径或摘录被丢弃并记录 unresolved。

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/review/test_evidence_agent.py -q`

Expected: FAIL because `review.evidence_agent` and its contracts do not exist.

**Step 3: Write minimal implementation**

- 建立 `EvidenceAgentResult`/plain-dict 契约。
- 为每次调查创建闭包工具，工具数据源只能是传入的 attachment index。
- 使用 `create_agent` 构建无 checkpointer 的短会话 Agent，设置递归步数上限。
- 解析 Agent 最后一条 JSON 输出，验证 source path、excerpt、状态和数量上限。

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/review/test_evidence_agent.py -q`

Expected: PASS.

### Task 2: 定义 fallback 触发条件和 Sheet 调查输入

**Files:**
- Modify: `src/review/evidence_agent.py`
- Test: `tests/review/test_evidence_agent.py`

**Step 1: Write the failing tests**

- 目录来源为 `directory` 且存在未解析/不支持文件时，带证据关键词的 Sheet 触发调查。
- 显式附件引用未匹配时触发调查。
- 已经明确匹配且全部解析成功的普通 Sheet 在 `fallback` 模式下不触发。
- `REVIEW_EVIDENCE_AGENT_MODE=off` 始终禁用；`always` 对有证据内容的目录 Sheet 启用。

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/review/test_evidence_agent.py -q`

Expected: FAIL because trigger evaluation and investigation request construction do not exist.

**Step 3: Write minimal implementation**

- 支持 `off`/`fallback`/`always` 三种模式，默认 `fallback`。
- 调查请求只包含当前 Sheet 的标准/执行文本和有限元数据，不把整个工作簿一次性塞进 Agent。
- 对每个 Sheet 最多执行一次调查，设置文件、结果、字符和工具调用上限。

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/review/test_evidence_agent.py -q`

Expected: PASS.

### Task 3: 将经验证的 Agent 证据接入现有审阅上下文

**Files:**
- Modify: `src/review/pipeline.py`
- Modify: `src/review/attachments.py`
- Modify: `src/review/evidence_steps.py`
- Test: `tests/review/test_pipeline.py`
- Test: `tests/review/test_evidence_steps.py`

**Step 1: Write the failing tests**

- Pipeline 在触发条件满足时调用调查 Agent，并将校验后的证据按 Sheet 保存。
- 证据上下文包含 Agent 返回的相对路径和精确摘录。
- Agent 失败或返回非法证据时，主审阅仍完成，并在统计信息中记录错误。
- evidence-vs-step LLM 输入包含 Agent 证据，但最终 Finding 仍经过现有 evidence_refs 校验。

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/review/test_pipeline.py tests/review/test_evidence_steps.py -q`

Expected: FAIL because the pipeline does not invoke or merge Agent evidence.

**Step 3: Write minimal implementation**

- 在每个 Sheet 的确定性检查后、LLM 检查前运行一次调查。
- 将结果写入 `agent_evidence_by_sheet`，不改变原始 `items` 和匹配规则。
- 把 Agent 证据追加到 checkpoint context 和 evidence-step payload。
- 统计 `runs`, `tool_calls`, `accepted_evidence`, `unresolved`, `errors`，且异常只降级为 unknown/原有结果，不阻断审阅。

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/review/test_pipeline.py tests/review/test_evidence_steps.py -q`

Expected: PASS.

### Task 4: 接入配置、审计轨迹和使用文档

**Files:**
- Modify: `src/review/attachments.py`
- Modify: `src/review/runner.py`
- Modify: `src/storage/review_artifact_store.py`
- Modify: `config/agent_llm_config.json`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/review/test_runner.py`
- Test: `tests/test_review_artifact_store.py`

**Step 1: Write the failing tests**

- 目录索引标记 `source_type=directory`，旧预览表标记 `source_type=preview`，避免 Agent 读取没有真实文件的旧输入。
- Agent 统计信息随审阅结果保存，快照目录仍是唯一来源根目录。
- 默认配置为 fallback，能够通过环境变量关闭或切换 always。

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/review/test_runner.py tests/test_review_artifact_store.py -q`

Expected: FAIL because source type, stats and configuration behavior are not present.

**Step 3: Write minimal implementation**

- runner 继续先快照，再建立目录索引；不把用户上传目录直接交给 Agent。
- artifact manifest 记录附件目录摘要，Agent 结果只引用相对路径和校验摘录。
- 更新 `.env`/README 说明 `REVIEW_EVIDENCE_AGENT_MODE`、步数和结果上限。

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/review/test_runner.py tests/test_review_artifact_store.py -q`

Expected: PASS.

### Task 5: 全量验证和差异复核

**Files:**
- No new production files.

**Step 1: Run backend tests**

Run: `uv run pytest -q`

Expected: all tests pass.

**Step 2: Run static checks**

Run: `uv run python -m compileall -q src tests`, `git diff --check`, and JSON validation for `config/agent_llm_config.json`.

Expected: exit code 0.

**Step 3: Review the diff**

Confirm no public tool argument was removed, no direct filesystem escape is possible through Agent tools, and no existing deterministic finding path depends on the Agent being available.
