# 阶段 C 设计：V2 判断与证据验证

- 日期：2026-08-03
- 状态：设计完成，待实施
- 基线：阶段 B 已合并到 `main`，V1 findings 仍是当前用户侧权威结果

## 1. 目标与边界

阶段 C 将现有两个 LLM 复核能力迁移到 Evidence-First 的最小事实包：

1. 证据与执行步骤一致性。
2. 标准审计程序与实际执行程序的 A-C 对应性。

本阶段新增 `JudgementRequest`、结构化 LLM 响应、引用 Verifier 和 V2 Finding，但不修改 V1 的 `run_review` 结果、不改变 `/findings/{review_id}` 响应、不新增数据库、队列、反馈 API 或规则维护界面。阶段 C 默认关闭 LLM shadow，可通过环境变量开启，避免未经评测就增加调用成本。

## 2. 方案选择

考虑过三种方案：

| 方案 | 做法 | 结论 |
|---|---|---|
| 直接替换 V1 | 把旧的两个 LLM 函数直接改成 V2 | 不采用，失败会影响当前审阅结果 |
| 独立 shadow adapter | 复用同一份 workbook/Evidence Graph，单独构造最小请求并写 V2 artifact | 采用，可比较、可回滚、V1 隔离 |
| 先做完整 V2/API/UI | 同时迁移全部规则并改工作台 | 延后，超出阶段 C 且缺少评测门禁 |

阶段 C 使用独立 `itgc-judgement/1.0.0` 策略包。策略 JSON 只保存规则身份、问题、允许决策、证据类型和风险元数据；LLM 不执行 JSON 中的代码或自由提示词。

## 3. 数据流

```text
workbook + EvidenceGraph + attachment index
        ↓
JudgementRequest（ControlFact、有限 evidence 白名单）
        ↓
LLM 结构化 JudgementResponse
        ↓ 一次受限重试
Verifier（契约、白名单、逐字 quote/offset/hash、结论关系）
        ↓
V2Finding（fail/unknown，带 verification_status）
        ↓
judgements.json + v2-findings.json
```

请求证据只来自本次 Evidence Graph 的单元格，或来自已索引附件的稳定 `att:` 证据 ID。模型不能发明单元格、路径或引用；引用不通过时不替换来源，重试仍失败则生成 `verification_status=invalid`、`status=unknown` 的结果。

## 4. 兼容与失败语义

- `REVIEW_JUDGEMENT_MODE=off|shadow`，默认 `off`。
- Stage C 失败只把 shadow artifact 标记为 error；V1 已完成结果保持不变。
- `v2-findings.json` 保存 V2 Finding 和 V1 兼容投影；现有 `findings.json` 不被覆盖。
- `supported` 不生成问题 finding；`contradicted` 生成 `fail`；`insufficient` 或 invalid 引用生成 `unknown`。
- 找不到明确 Sheet、布局或证据时记录 skipped/unknown，不默认扩大范围或补造证据。

## 5. 验收标准

1. Pydantic 契约拒绝未知字段、非法决策、缺失 insufficient 原因。
2. Verifier 能接受精确引用，拒绝未知 evidence ID、错误 quote、错误 offset、错误 content hash。
3. LLM 引用错误经过一次重试仍失败时降级为 unknown，保留错误码和响应摘要。
4. 两类 judgement request 只包含目标事实与证据白名单，不包含整张 Sheet。
5. 同一输入、策略包和 engine 版本产生稳定 request/finding identity。
6. Stage C shadow artifact 成功/失败均不改变 V1 findings。
