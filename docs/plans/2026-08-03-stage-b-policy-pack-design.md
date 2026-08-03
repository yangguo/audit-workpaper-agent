# 阶段 B 设计：itgc-core 三条规则策略包

## 目标与边界

阶段 B 将三条高价值、低歧义的确定性规则从 `procedure_pairs.py` 的硬编码条件迁移到受控 JSON 策略包，并在阶段 A 已有的 shadow artifact 中执行。V1 审阅仍是用户当前看到的权威结果；阶段 B 只生成可比较的 Review Plan 和 policy findings，不接管现有 findings API，也不引入新的 LLM 判断、反馈 API、数据库或队列。

首个策略包为 `policy_packs/itgc-core/1.0.0`，规则为：仅访谈且缺少实质证据、标准要求证据类型但执行未体现、SA-4c 特权账号范围未覆盖 OS/DB 管理员。JSON 只声明规则元数据和可信 `evaluator_id`，不允许 Python、表达式或自由提示词。

## 数据流

Runner 在阶段 A 的已固定 workpaper 上构建 `EvidenceGraph`。Stage-B planner 使用同一 workbook、graph、请求范围和 policy pack 生成稳定的 Review Plan：先解析 Sheet 布局，再把每个控制程序行映射为带 `evidence_id` 的 `ControlFact`，把 Sheet 汇总为 `SheetFact`，最后记录适用规则、输入事实、跳过原因和 scope 状态。显式范围不匹配只记录 `scope_validation_failed`，不会扩展到全部 Sheet。

Executor 只从仓库注册表调用可信 evaluator。Evaluator 产出带 `rule_id`、`rule_version`、`identity_key`、`finding_id`、严重度、风险类型和精确证据引用的确定性候选；引用必须来自 plan 白名单，并保存 quote、offset、content_hash。相同输入、策略包和 engine version 下，candidate identity_key 保持稳定；同一运行内按 identity_key 去重。

## 存储与兼容

Artifact manifest 增加可选 policy-pack 标识；shadow capture 继续原子写入 `review-plan.json` 和 `policy-findings.json`。策略包非法、planner/evaluator 出错时，artifact 标记 error，但已完成的 V1 review 不回滚、不改状态。阶段 B 结果先保持独立 JSON，未来阶段 C 再引入 V2 Finding/Verifier 和 V1 projection。

## 验收

策略包 schema、路径安全、三条 evaluator、事实到 evidence_id 映射、identity_key 稳定性、规则去重、非法包失败隔离和 artifact 写入均有单元/集成测试。完整 Python 测试必须保持通过；阶段 A 的 `/findings/{review_id}` 输出和前端不发生 schema 变化。
