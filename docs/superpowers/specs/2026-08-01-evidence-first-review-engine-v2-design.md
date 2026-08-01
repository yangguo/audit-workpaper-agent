# 设计：Evidence-First 审计底稿执行器 V2

- 日期：2026-08-01
- 状态：Draft，待确认后进入实施计划
- 主题：以证据事实、规则版本和可评测输出为核心，升级现有审计底稿审阅引擎

## 1. 背景

当前引擎已具备检查点复核、附件匹配、证据与步骤一致性、程序对规则、A-C 对应性、LLM 复核及高风险交叉质疑。其不足不在于缺少模型调用，而在于每个阶段仍各自从工作簿文本取数，finding 的证据、规则来源、模型判断与源文件版本之间没有统一的不可变关联。

这会带来四类问题：

1. 大 Sheet 需截断后交给 LLM，模型无法稳定知道自己依据的是哪一段事实。
2. 硬编码规则与审计方法论没有独立版本，难以按客户、行业或年度比较结果。
3. 当前摘录核验能证明文字来自单元格，却不能完整证明该文字支持对应结论。
4. 现有测试验证代码行为，但没有金标底稿集衡量误报、漏报和规则/模型版本回归。

V2 的定位不是另一个通用 Agent，而是一个可被 Codex、CLI、API 或工作台调用的标准化审阅执行器。

## 2. 目标与非目标

### 2.1 目标

1. 对同一文件、同一规则包、同一引擎版本产生可重跑、可解释的审阅输入与输出。
2. 每个 finding 都能追溯到规则版本、具体证据、判断过程和人工处理结果。
3. 规则可逐步从 Python 常量/条件判断迁移为受控、版本化的策略包。
4. LLM 只负责模糊语义判断和解释，不再充当事实提取或规则定义的唯一来源。
5. 用金标集与人工反馈量化准确性、成本和回归风险。
6. 保持现有聊天入口、review_id、findings 接口和工作台可用，允许分阶段迁移。

### 2.2 非目标

1. 本阶段不建设多租户、完整 RBAC、持久化队列、审批流或外部审计系统集成。
2. 本阶段只规范 Excel 底稿、检查要点和附件预览；不扩展为任意文档理解平台。
3. 不允许策略包包含可执行 Python、任意表达式或模型提示词注入内容。
4. 不自动以人工反馈直接修改规则或训练模型；反馈先进入可审计的改进流程。

## 3. 方案选择

考虑过三种路线：

| 路线 | 做法 | 结论 |
|---|---|---|
| Prompt-first | 继续扩充系统提示词、上下文和模型复核次数 | 不采用；无法解决来源、版本和可评测性问题 |
| Evidence-first | 先统一事实与证据，再执行规则和受限 LLM 判断 | 采用；适合审计场景的可验证性要求 |
| 先建设完整平台 | 先做用户、队列、审批、报表和权限 | 延后；在规则准确性尚未量化前，产品化投入回报低 |

V2 采用 Evidence-first。现有 LangGraph Agent 保留为入口和调度者；审阅核心从“多个模块直接读取工作簿”演进为“所有模块消费同一份证据快照”。

## 4. 总体架构

~~~mermaid
flowchart LR
    A[上传的底稿和辅助文件] --> B[输入指纹和工作簿快照]
    B --> C[证据事实层 Evidence Graph]
    D[版本化策略包] --> E[审阅计划编译器]
    C --> E
    E --> F[确定性规则执行]
    E --> G[受限 LLM 判断]
    F --> H[结论与证据验证器]
    G --> H
    H --> I[结构化 Review Artifact]
    I --> J[现有 findings API 和工作台]
    I --> K[金标评测和人工反馈]
~~~

### 4.1 新增或调整的模块

~~~text
src/review/
  contracts.py          # V2 Pydantic 数据契约和 schema_version
  snapshot.py           # 文件哈希、工作簿快照、原子写入
  evidence.py           # CellEvidence、AttachmentEvidence、ControlFact 构建
  planner.py            # 策略包 + Evidence Graph -> ReviewPlan
  policy.py             # 策略包加载、校验、规则注册表
  evaluators.py         # 受信任的复杂规则实现，按 evaluator_id 注册
  judgement.py          # 面向 LLM 的受限事实包与结构化判断
  verifier.py           # 证据引用、结论支持度、去重与升级规则
  findings.py           # V2 Finding -> 现有前端兼容投影
  evaluation.py         # 金标集运行、指标和回归门禁
  feedback.py           # 人工确认/驳回/修改事件的契约和存储
  pipeline.py           # 变为 V2 编排入口，保留 V1 适配路径

policy_packs/
  itgc-core/
    1.0.0/
      manifest.json
      rules/
        procedure-interview-only.json
        procedure-required-evidence.json
        scope-os-db-admin.json

tests/
  fixtures/evals/
    manifest.json
    cases/<case_id>/
      expected_findings.json
      expected_skips.json
      notes.md
~~~

Pydantic 已是项目依赖，V2 使用它定义稳定契约；策略包首版使用 JSON，避免新增 YAML 解析依赖和隐式类型差异。

## 5. 证据事实层

### 5.1 输入指纹与审阅清单

每个审阅在解析前生成 InputManifest：

~~~json
{
  "schema_version": "2.0",
  "review_id": "uuid",
  "engine_version": "git-sha-or-build-id",
  "created_at": "ISO-8601",
  "inputs": [
    {
      "role": "workpaper",
      "path": "assets/uploads/...",
      "sha256": "content-hash",
      "size": 123,
      "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
  ],
  "policy_pack": {"id": "itgc-core", "version": "1.0.0"},
  "requested_scope": {"sheets": ["PE-6"]}
}
~~~

文件哈希是 V2 的主版本锚点。源文件变化即视为新审阅，不允许在旧 review_id 中静默替换事实。

### 5.2 Evidence Graph

工作簿只解析一次，生成以下事实：

| 类型 | 关键字段 | 用途 |
|---|---|---|
| CellEvidence | evidence_id、sheet、coordinate、raw_value、formula、display_value、content_hash | 逐格可追溯来源 |
| SheetFact | sheet_id、name、layout、header_map、sheet_hash | 范围与布局识别 |
| ControlFact | control_id、标准列、执行列、附件引用、关联 CellEvidence ID | 将审计程序行变成语义对象 |
| AttachmentEvidence | attachment_id、索引、文件名、路径、状态、来源 CellEvidence ID | 附件匹配与证据充分性 |
| CheckpointFact | checkpoint_id、文本、目标 Sheet、来源 Evidence ID | 检查要点复核 |

evidence_id 由 schema 版本、源文件 SHA-256、规范化 Sheet 名、单元格坐标、原始值与公式哈希共同生成。它不追求跨版本文件的永久相同，而保证同一文件版本中指向唯一、不可伪造的事实。

对文本摘录，EvidenceRef 必须同时带 evidence_id、quote、start_offset、end_offset、content_hash。验证器必须在该 evidence_id 的不可变 display_value 中核验偏移和哈希。

### 5.3 语义标准化

现有各阶段会自行识别布局、遍历单元格或截断 Sheet 文本。V2 改为由 evidence.py 统一生成 ControlFact。规则不再依赖 A/B/C 固定列号，而依赖如下语义字段：

~~~json
{
  "control_id": "sha256:...",
  "standard_evidence_ids": ["ev:..."],
  "execution_evidence_ids": ["ev:..."],
  "attachment_refs": ["att:..."],
  "scope": {"sheet_id": "PE-6", "row": 12},
  "layout_confidence": "known"
}
~~~

无法识别布局的 Sheet 产生明确的 skipped 记录，不将其伪装成“已审阅且无发现”。

## 6. 策略包与规则执行

### 6.1 策略包

策略包是受版本控制的 JSON 目录。manifest 声明包 ID、版本、适用领域、兼容引擎范围和默认风险词典；每条 rule 文件声明规则的业务含义与绑定的可信 evaluator。

~~~json
{
  "rule_id": "itgc.procedure.interview_only",
  "version": "1.0.0",
  "title": "仅访谈且缺少实质性证据",
  "evaluator_id": "procedure.interview_only",
  "applies_to": {"fact_type": "ControlFact"},
  "severity": "P1",
  "risk_type": "证据不足",
  "required_evidence_types": ["截图", "导出", "日志", "清单"],
  "remediation_template": "补充可复核的系统或业务证据，并说明核查步骤。",
  "enabled": true
}
~~~

策略包不能包含 Python 代码、动态 SQL 或自由提示词。复杂逻辑只允许通过 evaluator_id 映射到仓库内、经过单测的函数。这样既让审计方法论可以版本化，又避免把业务规则变成不可控脚本。

### 6.2 ReviewPlan

planner.py 读取 Evidence Graph 与策略包，输出 ReviewPlan：

1. 验证请求 scope；显式指定但无法匹配的 Sheet 返回 scope_validation_failed，不再默认回退到全部 Sheet。
2. 选择适用规则和 ControlFact，记录每个计划项的输入 evidence_id。
3. 将规则分为 deterministic、llm_required、cross_validate 三类。
4. 估算单元数、LLM 调用数与预算；超过上限时生成明确的 partial_review 状态，而不是静默截断。

计划本身会存入 Review Artifact，以便回答“本次为什么检查了这个控制点、为什么没检查另一个控制点”。

### 6.3 执行与去重

确定性规则先执行，产出 CandidateFinding。候选项的稳定 identity_key 为 rule_id、rule_version、主 evidence_id 集合和结论类别的哈希。相同候选在同一次审阅中去重，但保留所有支持证据。

首批迁移规则只选择高价值、低歧义的三类：

1. 仅访谈且缺少实质性证据。
2. 标准程序要求的证据类型未在执行程序中体现。
3. OS/DB 管理员范围未覆盖。

其余现有规则继续走 V1 适配器，避免一次重写全部审阅逻辑。

## 7. LLM 判断与结论验证

### 7.1 受限 LLM 输入

LLM 不再接收任意整张 Sheet 文本。每个 JudgementRequest 只包含：

1. 规则 ID、规则版本、判定问题和允许的结果集。
2. 相关 ControlFact。
3. 有限、带 evidence_id 的原始证据片段。
4. 期望证据类型、反例和需要判断的歧义点。

输出采用 Pydantic 契约：

~~~json
{
  "decision": "supported | contradicted | insufficient",
  "conclusion": "string",
  "evidence_refs": [
    {
      "evidence_id": "ev:...",
      "quote": "逐字摘录",
      "start_offset": 0,
      "end_offset": 12,
      "role": "supporting | contradicting"
    }
  ],
  "unknown_reason": "仅在 insufficient 时必填",
  "reasoning_summary": ["最多 3 条可展示理由"]
}
~~~

模型输出不允许自行发明单元格坐标、附件名或规则。所有引用必须属于请求中给出的 evidence_id 白名单。

### 7.2 验证器

verifier.py 执行四层验证：

1. 契约验证：字段、枚举、必填关系和长度。
2. 引用验证：evidence_id 属于本次计划；摘录与偏移在源事实中精确匹配。
3. 结论验证：fail finding 至少有 supporting 证据；contradicted 不能被渲染为 fail；证据不足必须输出 unknown。
4. 规则验证：严重度、风险类型和整改建议必须来自策略包或显式人工覆盖。

若引用失效，V2 不替换为另一段单元格文本来“修复”结论。它会请求一次带验证错误的重试；仍失败则把该项降级为 unknown，并保留 error_code 和原始模型响应摘要。

P0 或 needs_review finding 继续保留现有交叉校验和对抗质疑，但其输入同样改为 Evidence Graph 中的最小充分事实包。

## 8. 输出、兼容性与存储

### 8.1 Review Artifact

每次审阅写入一个完整 artifact：

~~~text
assets/reviews/<review_id>/
  manifest.json
  evidence.json
  review-plan.json
  findings.json
  stages.json
  feedback.jsonl
~~~

写入遵循“临时文件 + fsync + 原子 rename”；完成后 manifest 状态才从 running 改为 completed。现有 assets/results/<review_id>_findings.json 在迁移期继续生成，内容来自 V2 的兼容投影。

### 8.2 Finding V2

Finding V2 增加以下字段，而保留现有前端需要的 issue_type、severity、sheet、cell、basis、suggestion、status 和 evidence_refs：

| 字段 | 作用 |
|---|---|
| finding_id | 本次运行内唯一 ID |
| identity_key | 同规则/同主证据的稳定去重键 |
| rule_id / rule_version | 方法论来源 |
| verification_status | supported、contradicted、insufficient、invalid |
| provenance | 引擎版本、策略包、阶段、模型版本 |
| evidence_refs_v2 | 带 evidence_id 与摘录偏移的证据 |
| review_scope | 本次实际覆盖的 Sheet/控制点 |
| resolution | 人工确认、驳回、修改、升级后的状态 |

findings.py 负责 V2 到 V1 的投影，保证 Workbench 在前端改造完成前仍可显示已有字段。

### 8.3 API

保留：

- POST /v1/chat/completions
- GET /v1/chat/completions/result/{task_id}
- GET /review/{review_id}/status
- GET /findings/{review_id}

新增：

- GET /reviews/{review_id}/manifest：审阅范围、输入哈希、引擎和策略版本。
- GET /reviews/{review_id}/evidence/{evidence_id}：仅返回该 finding 可访问的最小证据片段。
- POST /reviews/{review_id}/feedback：提交人工确认、驳回、修改或升级。
- POST /evaluations/run：仅开发/CI 环境运行金标评测。

本阶段不新增认证，因此 evidence 单项接口与现有 findings 接口同样仅面向受信任内网部署；在公开部署前必须先补访问控制。

## 9. 评测与人工反馈

### 9.1 金标集

金标集只保存脱敏或合成底稿。每个 case 包含输入文件哈希、策略包版本、预期 finding、预期 skipped 范围和人工说明。预期 finding 以 rule_id、主 evidence_id/坐标、severity 和 status 表达，而不是匹配自由文本。

评测报告至少输出：

1. 每条规则的 precision、recall、F1。
2. P0/P1/P2 的严重度一致率。
3. evidence 引用通过率与 invalid 引用率。
4. unknown 率、人工推翻率和模型调用失败率。
5. 每 case 的耗时、调用次数和估算 token/cost。

初期先建立基线，不在没有真实样本数据前设定虚构阈值。之后 CI 应阻止 P0 召回率下降、关键规则回归或 invalid evidence 上升。

### 9.2 人工反馈

反馈是 append-only 事件：

~~~json
{
  "feedback_id": "uuid",
  "finding_id": "finding:...",
  "action": "confirm | reject | edit | escalate",
  "reason_code": "false_positive | missing_evidence | severity_adjustment | rule_gap",
  "replacement_evidence_ids": ["ev:..."],
  "severity_override": "P2",
  "comment": "string",
  "created_at": "ISO-8601"
}
~~~

反馈不自动改写 finding，也不自动训练模型。evaluation.py 定期汇总高频 reason_code，形成可评审的“规则修改候选”或“金标新增候选”。

## 10. 错误处理与性能

| 情况 | V2 行为 |
|---|---|
| 文件哈希或解析失败 | 终止该 review，写入 manifest error，不生成“无问题”结果 |
| 显式 Sheet 无法匹配 | 记录 scope_validation_failed，默认不扩展为全 Sheet |
| Sheet 无可识别布局 | 记录 skipped，展示原因 |
| 策略包非法或版本不兼容 | 启动前失败，禁止部分执行 |
| LLM 超时/限流 | 按现有退避重试；失败项为 unknown，记录 stage error |
| 证据引用不通过 | 一次受限重试；仍失败为 invalid/unknown，不替换来源 |
| 输出写入中断 | manifest 保持 running/error；原子写入避免半份 completed 结果 |

性能采用“先确定性、后 LLM”的策略：

1. 同一文件只构建一次 Evidence Graph。
2. 以 file SHA、策略包版本、engine 版本、scope 生成缓存键；未变输入可复用 snapshot 和确定性结果。
3. LLM 只消费候选或歧义项，不把所有 Sheet 送入模型。
4. Sheet 级并行必须由可配置 Semaphore 限制，并记录每阶段耗时与调用数；本阶段不把并发上限写死在业务规则中。

## 11. 迁移路径

### 阶段 A：影子快照

新增 InputManifest、Evidence Graph 和 artifact 写入，但保留 V1 规则与输出。每次审阅同时写入 V2 证据快照，用于验证解析正确性，不改变用户结果。

### 阶段 B：三条规则试点

引入 itgc-core 1.0.0 策略包，将三条高价值确定性规则迁到 V2。V1 与 V2 在金标集和可选影子运行中比较；用户仍接收 V1 投影。

### 阶段 C：V2 判断与验证

将证据-步骤一致性和 A-C 判断迁到 JudgementRequest/Verifier，开启 V2 finding 投影。对于无法通过引用验证的结果，明确显示 unknown。

### 阶段 D：评测与反馈成为发布门禁

引入金标评测命令、CI 报告和人工反馈 API。规则包或模型变更必须附带评测结果。

企业队列、数据库、多租户与审批流仅在阶段 D 已证明准确性和使用频率后单独设计。

## 12. 测试与验收

### 12.1 测试层次

1. 单元：哈希、Evidence ID、布局到 ControlFact 映射、策略包校验、引用偏移验证、规则 evaluator。
2. 契约：V2 artifact、API 响应、V2 到 V1 投影的 schema 和向后兼容。
3. 集成：小型 xlsx + 检查要点 + 附件预览，断言计划、候选、验证器和 findings 的完整链路。
4. 金标：脱敏样本的规则匹配、严重度、证据支持度和跳过范围。
5. 失败注入：模型 429/超时、损坏 xlsx、策略包非法、原子写入中断、引用伪造。

### 12.2 首版完成定义

1. 任意 V2 finding 都可从 finding_id 跳转到 rule_id/version 与至少一个不可变 evidence_id。
2. 任意 fail finding 的证据验证状态不能为 invalid 或 insufficient。
3. 指定 Sheet 未匹配时，不会在未声明的情况下审阅全部 Sheet。
4. 三条试点规则可由 JSON 策略包配置，并具有独立单测和金标 case。
5. 同一输入、同一策略包、同一引擎版本的两次运行，其确定性结果和 identity_key 相同。
6. 现有 GET /findings/{review_id} 与工作台不因 V2 引入而失效。

## 13. 待实施前确认的事项

1. 初始金标集应由谁提供、可否使用脱敏历史底稿，及其保存位置。
2. itgc-core 1.0.0 的方法论所有者与规则版本发布责任人。
3. V2 影子运行是否允许调用真实 LLM，或先只运行确定性规则。
4. 本地 artifact 的保留期、是否允许清理源上传文件，以及未来对象存储迁移策略。
