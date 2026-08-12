# 审阅质量稳定性发布与回滚手册

本手册控制的是 `REVIEW_RESULT_QUALITY_MODE=on` 的小流量试点。它不会把 Stage C
候选直接变成权威结论，也不会授权删除任何审阅 artifact 或失败样本。

## 1. 建立可比较基线

1. 选择经脱敏、获批准的底稿样本；原始底稿、OCR 全文、绝对路径和未脱敏摘录不得进入仓库。
2. 对每份样本冻结输入集合，记录 `input_sha256`、`input_set_sha256`、目标 scope 和
   `execution_sha256`。后者必须包含实际模型/提示词、策略包、断言目录、整改目录和运行配置。
3. 在当前生产等价配置下收集 V1 结果；不要先打开 quality-on。把人工裁决的预期 assertion、
   claim subject、scope、允许 evidence IDs、重复/冲突预期和整改预期写入 `review-quality/2`
   manifest。
4. 两名审阅者完成 adjudication；争议保留为裁决记录，不用“多数意见”覆盖。

停止条件：任一 case 没有冻结 input/execution identity、证据来源不能合规保留，或人工裁决尚未
完成时，不得进入重复运行。

## 2. 五次重复运行与评估

1. 每个 case 在完全相同的 `input_set_sha256` 和 `execution_sha256` 下独立运行至少五次。不要
   混用输入快照、模型版本、提示词、策略包、断言/整改目录或 runtime config。
2. 将 V1、V2 和五次运行分别写入结果 JSON：

   ```json
   {
     "v1": {"case-id": []},
     "v2": {"case-id": []},
     "repeated_runs": {"case-id": [[], [], [], [], []]}
   }
   ```

   此处 V2 是带 `review-quality/2` 质量信封的 V1 兼容 finding 集（通常来自受控的
   quality-on 重跑），不是原始 `stage-c-v2-findings/1` 候选 artifact。Stage C 差异仍应
   作为 SME 审阅材料，不能直接被该 evaluator 当作质量-on 结果。

3. 运行：

   ```bash
   uv run python scripts/evaluate_review_quality.py \
     --manifest /controlled/path/manifest.json \
     --results /controlled/path/results.json \
     --output /controlled/path/promotion-report.json
   ```

4. 逐项审阅 `metric_details`，而非只看总分。每项均含分子、分母、阈值和失败 case ID。

技术门禁如下：

| 门禁 | 要求 |
| --- | --- |
| 可比较性 | 每 case 至少 5 次；所有 finding 的 input-set 与 execution SHA 均与 manifest 完全一致 |
| 语义稳定性 | 两两 semantic key Jaccard 平均值 ≥ 0.90 |
| 状态一致性 | 跨所有运行共同 key 的 status 一致率 ≥ 0.95 |
| 引用 | V1 和候选的 citation reproduction 均 = 1.0，且 repeated verified evidence ID 集合稳定 |
| 附件 claim | 准备发布为 fail 的附件型 claim 全部 `supported`；保守降为 `unknown` 单列追踪 |
| 内部一致性 | publishable finding 的 unresolved conflict rate = 0 |
| 去重 | false duplicate merge count = 0 |
| 整改 | publishable P0/P1 的 action、required evidence、acceptance criteria 全部完整 |
| 准确性样本 | 至少 6 份 adjudicated 底稿、60 条 adjudicated finding；V2 P0/P1 precision 不低于 V1 |

`non_comparable_runs`、`input_set_sha256_mismatch`、缺少人工裁决或任何 gate failure 都是停止条件；
不要通过修改阈值、删除结果或把 `not_run` 标成 `passed` 来绕过。

## 3. 发布审批与小流量

`promotion_ready=true` 只说明单批技术条件已满足。进入 canary 仍需：

1. 两个连续、相互独立的评估批次均满足全部技术门禁；
2. 审计 SME 审阅 V1/V2 差异、attachment unresolved 和 conflict/duplicate 明细并书面批准；
3. 发布负责人记录样本版本、评估报告路径、批准人、时间和 canary 范围；
4. 仅在明确范围内将 `REVIEW_RESULT_QUALITY_MODE=on`。默认导出仍保持 V1 / `source=legacy`；
   Stage C 若启用也只能作为 shadow 候选，不能替代权威 V1。

观察 canary 时，每日检查引用复现、被降级为 unknown 的附件 claim、冲突、误合并、P0/P1 整改
完整性及业务审阅者的误报/漏报反馈。任何严重 P0/P1 回归、execution identity 漂移或证据闭环
断裂都应立即回滚。

## 4. 回滚和保留

回滚无需删除数据，只需恢复保守配置：

```dotenv
REVIEW_RESULT_QUALITY_MODE=shadow
REVIEW_JUDGEMENT_MODE=off
```

`shadow` 继续记录 evidence support、conflict、gate 和 provenance，但不改写 V1 结论；`off`
不会发起 Stage C 候选 LLM 调用。继续使用默认 V1 导出，并保留
`assets/reviews/<review_id>/` 的 manifest、evidence、comparison、失败报告和输入快照供差异分析。
禁止删除失败样本或 artifact 来制造“干净”的下一批评估结果。

回滚后，先修复根因并重新冻结 execution identity，再从基线和五次重复运行开始进行新的独立批次。
