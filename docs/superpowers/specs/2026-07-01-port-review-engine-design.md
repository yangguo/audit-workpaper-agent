# 设计：将 `analyze_excel.py` 审阅逻辑移植到本项目 Agent 工具

- 日期：2026-07-01
- 主题：移植 `wpreview/analyze_excel.py` 的确定性审阅管线到本项目 LangGraph agent
- 参考文件：`D:\User Data\yangfan15\Desktop\projects\wpreview\analyze_excel.py`（4345 行，确定性批处理管线）

## 1. 背景与目标

参考脚本 `analyze_excel.py` 是一个确定性批处理管线，对审计底稿 Excel 做多阶段审阅并产出结构化 findings。本项目当前是一个 LangGraph agent，通过 3 个简单工具（`analyze_worksheet` / `check_evidence` / `verify_attachments`）审阅底稿，最终输出 Markdown，前端从 Markdown 中正则解析「异常数」等指标。

参考脚本相比本项目工具，能力更丰富且带反幻觉机制：

- 结构化 `Finding`（`status`/`severity(P0–P2)`/`risk_type`/`evidence_refs`/`conclusion`/`reasons`/`fix_suggestion`/`unknown_reason`）
- JSON Schema 校验 + 自动修复（`_validate_finding_result` / `_repair_finding_result`）
- 摘录必须逐字匹配单元格（`_verify_evidence_refs` / `_excerpt_matches`），降低幻觉
- 检查点复核（`_llm_check_sheet_by_checkpoints`，依赖检查要点表）
- 附件预览清单匹配（`_check_attachment_references`，依赖附件预览表）
- 证据↔步骤一致性（`_llm_check_evidence_vs_steps`）
- 程序对规则检查（`_check_procedure_pairs`，覆盖模板未替换/仅访谈/证据类型缺失/账号-离职-调岗-密码-批处理-变更等常见问题）
- 表范围检查（`_check_sheet_scope`）
- A–C 对应性 LLM 判定（`_llm_check_procedure_pairs` / `_llm_judge_procedure_pair`）
- 规则 findings 的 LLM 复核（`_llm_review_findings`）
- 交叉校验 + 对抗式质疑（`_cross_validate_finding` / `_challenge_finding_with_llm`）
- LLM 调用基础设施（重试/退避/统计：`_llm_chat` / `_llm_request_json_list`）

**目标**：保留 LangGraph agent 作为调度者与叙述者，把参考脚本的审阅逻辑移植为**单一全量工具** `review_workpaper`；产出结构化 findings 写入侧端存储，agent 只收到摘要并生成 Markdown，前端直接读取结构化 findings 渲染既有 workbench 面板。

## 2. 已确认的决策

| 决策点 | 选择 |
|---|---|
| 集成方式 | 移植到 agent 工具里（保留 LangGraph agent） |
| 输入文件 | 运行时可获取「检查要点」表与「附件预览」表 |
| 结果输出 | 结构化 findings + 侧端存储；agent 收摘要、出 Markdown；前端直接读结构化 findings |
| 工具划分 | 单一全量工具 `review_workpaper`（取代 `check_evidence` / `verify_attachments`） |

## 3. 架构与模块划分

保留 LangGraph agent。新增 `review_workpaper` 工具与 `src/review/` 包。参考脚本是单文件 4345 行，难以可靠推理与编辑，故按职责拆分为多个聚焦、可独立测试的模块。

```
src/
  tools/
    analyze_worksheet.py      # 保留，轻量结构预览（基本不变）
    review_workpaper.py       # 新增：@tool 包装 -> 调用 review.pipeline.run_review
                              #       保存 findings 到侧端存储，返回摘要 JSON
    check_evidence.py         # 移除（被管线取代）
    verify_attachments.py     # 移除（被管线取代）
  review/                     # 新增：移植的审阅引擎
    models.py                 # Finding, AttachmentPreviewItem, 严重度映射, _FINDING_RESULT_SCHEMA
    excel_utils.py            # _detect_layout, _get_cell_value, _extract_sheet_text_cells,
                              #   _build_sheet_text_for_llm, _truncate, _normalize_sheet_id, _is_empty
    validation.py             # _validate_finding_result, _repair_finding_result, _validate_llm_results,
                              #   _verify_evidence_refs, _excerpt_matches, _get_cell_text
    llm.py                    # 异步 LLM 调用（重试/退避/统计）、_llm_request_json_list、_try_parse_json
                              #   基于 langchain_openai.ChatOpenAI，env+model 取自 config
    hallucination.py          # _cross_validate_finding, _build_minimal_context, _challenge_finding_with_llm
    checkpoints.py            # load_checkpoints_xlsx, _split_checkpoints, _extract_checkpoint_keywords,
                              #   _llm_check_sheet_by_checkpoints
    attachments.py            # load_attachments_preview_xlsx, _extract_attachment_refs,
                              #   _match_preview_items, _check_attachment_references, _attachments_context_for_sheet,
                              #   _compact_keywords, _evidence_matches_step
    evidence_steps.py         # _llm_check_evidence_vs_steps
    procedure_pairs.py        # _check_procedure_pairs（规则）, _check_sheet_scope,
                              #   _llm_judge_procedure_pair, _llm_check_procedure_pairs, _classify_mismatch 及其辅助函数
    findings_review.py        # _llm_review_findings（对规则 findings 的 LLM 复核）
    pipeline.py               # run_review(wb, checkpoints, preview, sheets, llm_cfg) -> (findings, stats)
  storage/
    findings_store.py         # 新增：save_findings / load_findings -> JSON 侧端存储（+ 可选 DB）
  agents/agent.py             # 工具列表改为 [analyze_worksheet, review_workpaper]
config/agent_llm_config.json  # sp 与 tools 更新，描述 review_workpaper
```

`analyze_worksheet` 保留，供 agent 在决定审阅范围前预览结构/Sheet。`check_evidence` 与 `verify_attachments` 移除，其能力被管线完全覆盖。

## 4. `review_workpaper` 工具与管线

### 4.1 工具签名

```python
@tool
async def review_workpaper(
    file_path: str,
    checkpoints_path: str = "",
    attachments_preview_path: str = "",
    sheets: str = "",
) -> str:  # JSON 字符串
```

- `file_path`：底稿 Excel 路径（相对 `assets` 或绝对）。
- `checkpoints_path`：检查要点 Excel 路径（可选，留空则跳过检查点复核）。
- `attachments_preview_path`：附件预览 Excel 路径（可选，留空则跳过附件匹配与证据-步骤一致性）。
- `sheets`：逗号分隔的 Sheet 名筛选（可选，留空=全部）。

### 4.2 管线 `pipeline.run_review`

移植自参考脚本 `generate_report` 的**审阅核心**，不移植其 xlsx/txt 渲染部分：

1. 加载工作簿（`openpyxl`，`data_only=True`）；按需加载检查要点（`load_checkpoints_xlsx`）与附件预览（`load_attachments_preview_xlsx`）。
2. 对每个 Sheet（按 `sheets` 过滤）依次执行：
   - 检查点复核（`_llm_check_sheet_by_checkpoints`，需检查要点）
   - 附件引用匹配（`_check_attachment_references`，需附件预览）
   - 证据↔步骤一致性（`_llm_check_evidence_vs_steps`，需附件预览）
   - 程序对规则检查（`_check_procedure_pairs`）
   - 表范围检查（`_check_sheet_scope`）
   - A–C 对应性 LLM 判定（`_llm_check_procedure_pairs`）
3. 合并全部 findings；对规则 findings 做 LLM 复核（`_llm_review_findings`）。
4. 对 P0 / `needs_review` findings 做交叉校验 + 对抗式质疑（`_cross_validate_finding` / `_challenge_finding_with_llm`）。
5. 按严重度（P0→P2）再按 sheet/cell 排序；收集 `LLM_CALL_STATS`。
6. 返回 `(findings, stats)`。

### 4.3 工具体

1. 相对 `COZE_WORKSPACE_PATH` 解析路径；文件缺失则返回错误摘要（不抛异常）。
2. 调用 `pipeline.run_review(...)`。
3. 生成 `review_id`（uuid4）。
4. `findings_store.save_findings(review_id, findings, stats)`。
5. 返回**摘要** JSON：按 severity / risk_type 的计数、top-N 问题、`review_id`、`findings_url`（`/findings/{review_id}`）。

agent 据此摘要生成 Markdown 叙述（总体评价、按严重度分组的问题、改进建议、风险提示），并在叙述中体现 `review_id`。

## 5. 侧端存储、接口与前端联动

### 5.1 侧端存储

- 路径：`${COZE_WORKSPACE_PATH}/assets/results/<review_id>_findings.json`（始终可用）。
- 当 `PGDATABASE_URL` 可用时，额外写一条 DB 行（可选；不可用则降级为仅文件）。
- 结构：`{review_id, created_at, stats, findings: [...]}`。

### 5.2 新增接口

- `GET /findings/{review_id}` → 返回上述 JSON；不存在则 404。
- （可选后续）`GET /findings/{review_id}/summary` → 仅返回 stats，供轻量轮询。

### 5.3 `review_id` 与前端联动

前端当前走 `/v1/chat/completions`（非流式）+ 轮询 `/v1/chat/completions/result/{task_id}`，**目前只读取 `choices[0].message.content`**，看不到 tool 消息/结果（`ToolTracePanel` 实际未被使用）。

联动改造：

- `main.py` 的 `run_agent_background`：run 完成后扫描 graph messages，找到 `review_workpaper` 的**工具结果**消息，解析其摘要 JSON，把 `review_id`（与 stats）写入 `task_results[task_id]`。
- `get_chat_result`（`GET /v1/chat/completions/result/{task_id}`）：在返回体中追加 `review_id`（与 stats）。
- 前端 `Stream.tsx`：`pollData.status === "completed"` 时读取 `pollData.review_id`，随后 `GET /findings/{review_id}` 取结构化 findings。
- `view-model.ts`：由结构化 findings 构建面板数据，**不再从 Markdown 正则解析**：
  - `ResultSummaryCards` ← severity / risk_type 计数
  - `AnalysisResultPanel` ← findings 按 sheet/严重度分组（agent 的 Markdown 叙述作为其中一段总结）
  - `EvidenceListPanel` ← `evidence_refs`
  - `ToolTracePanel` ← 管线阶段 + `LLM_CALL_STATS`
- `/run` 同步路径：在返回的 result dict 中同样附加 `review_id`，保持一致。

## 6. LLM 客户端、异步、延迟与上限

- **LLM 客户端**：复用既有 env（`COZE_WORKLOAD_IDENTITY_API_KEY` / `COZE_INTEGRATION_MODEL_BASE_URL`）与 `config/agent_llm_config.json` 中的 model；审阅/检查类调用使用可配置 model（默认 `doubao-seed-1-6-251015`，与现有 `check_evidence` 一致）。使用 `langchain_openai.ChatOpenAI`（已是依赖），**不新增 `openai` / `jsonschema` 依赖**；用一个轻量内联 schema 校验器替代 `jsonschema`（schema 固定且简单）。
- **异步**：agent 经 `ainvoke` 运行，故 `review_workpaper` 为**异步 `@tool`**，管线用 `asyncio.gather` 做批量并发（替代参考脚本的 `ThreadPoolExecutor`）；LLM 调用走 `ChatOpenAI.ainvoke`。
- **延迟与上限**（现实约束：前端轮询上限 3 分钟）：移植参考脚本的上限（`batch_size`、`max_cells`、`max_chars`、`LLM_EVIDENCE_STEPS_MAX_ITEMS`）为可配置 env 变量；Sheet/检查点批次并发执行。超大底稿仍可能超过 3 分钟——适度提高前端 `maxPolls`，并预留「复核仍在运行」的提示路径，作为后续项，不在核心范围。

## 7. 错误处理与测试

### 7.1 错误处理（逐阶段韧性，移植自参考脚本）

- 可选输入缺失 → 跳过对应阶段、记日志、继续其余阶段。
- LLM 传输失败 → 差异化退避重试；最终失败降级为 `unknown` finding（带 `unknown_reason`），不使整个 run 崩溃。
- `fail` 但无 `evidence_refs` → 自动降级为 `unknown`。
- 摘录与单元格文本核验：不匹配则用实际单元格文本替换，或丢弃该 evidence_ref。
- 文件缺失/解析失败 → 返回错误摘要 JSON，不抛异常。

### 7.2 测试（CI 中 mock LLM 客户端，不调用真实 API）

- **单元测试**：`_validate_finding_result` / `_repair_finding_result`、`_verify_evidence_refs` / `_excerpt_matches`、`_detect_layout`、`_extract_attachment_refs` / `_match_preview_items`、`_classify_mismatch`、严重度映射、检查点切分。
- **集成测试**：小型 fixture 工作簿 + 检查要点 + 附件预览 → `run_review` → 断言不变量（每个 `fail` 有 `evidence_refs`；每个 `unknown` 有 `unknown_reason`；摘录逐字匹配单元格；findings 按严重度排序）。
- **存储/接口测试**：`save_findings` / `load_findings` 往返；`GET /findings/{review_id}` 200/404。

## 8. 范围 — 不移植的部分（YAGNI）

- 参考脚本的 **xlsx/txt 报告写入器**（`_write_report_txt` / `_write_report_xlsx` / `generate_report` 的渲染部分，以及 `_merge_cell_duplicates` / `_deterministic_merge_cell` / `_try_llm_merge_cell` 等报告渲染辅助）——由侧端存储 JSON + 前端面板取代。如后续需要可下载报告，可再加一个可选 xlsx 导出接口。
- 参考脚本的独立 CLI / `main()` / `.env` 解析（`resolve_llm_config`）——由本项目既有 env + config 取代。
- Approach 3 的「保留 `verify_attachments` 作为无预览表回退」——因两种输入均可用，故舍弃。

## 9. 构建顺序（实现阶段细化）

1. `review/models.py` + `review/excel_utils.py` + `review/validation.py`（纯函数，先行可测）。
2. `review/llm.py`（异步调用 + 内联 schema 校验，mock 友好）。
3. `review/checkpoints.py` / `attachments.py` / `evidence_steps.py` / `procedure_pairs.py` / `findings_review.py` / `hallucination.py`（各阶段，逐个移植 + 单测）。
4. `review/pipeline.py`（编排）+ 集成测试。
5. `storage/findings_store.py` + `GET /findings/{review_id}`。
6. `tools/review_workpaper.py` + `agents/agent.py` 工具列表与 config 更新。
7. `main.py` 的 `run_agent_background` / `get_chat_result` 联动 + `/run` 一致化。
8. 前端 `Stream.tsx` / `view-model.ts` / 面板取数改造。
9. 移除 `check_evidence.py` / `verify_attachments.py`，更新 CLAUDE.md 中工具说明。

## 10. 风险与备注

- **延迟**：全量管线 LLM 调用多，超大底稿可能超 3 分钟前端轮询上限；靠并发 + 上限 + 适度提高 `maxPolls` 缓解，必要时引入「仍在运行」提示。
- **依赖**：不新增运行时依赖（`openai` 经 `langchain-openai` 间接可用但不直接使用；`jsonschema` 用内联校验器替代）。
- **CLAUDE.md**：需同步更新工具说明（`check_evidence` / `verify_attachments` → `review_workpaper`；新增 `src/review/`）。
- **向后兼容**：移除两个工具会改变 agent 行为；现有会话（checkpointer）不保留新工具，仅新会话生效。
