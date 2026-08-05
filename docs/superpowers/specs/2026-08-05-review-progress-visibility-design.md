# 审阅运行中进度可见性 — 设计

- 日期: 2026-08-05
- 状态: 已批准（待 spec 复核）
- 方案: A — 复用现有 5s 轮询 + registry 暴露 progress

## 背景与问题

审阅大底稿时，后台审阅任务会运行数十分钟。当前在前端只能看到一行静态文字「审阅进行中… 已运行 Xs」，看不到当前在查哪个 sheet、哪个阶段、调了多少次 LLM、已发现多少问题。用户长时间等待却无任何反馈。

两个具体问题:

1. **「处理耗时」卡片计时会停止**。计时架构是两段式、两个独立计时器:
   - 阶段①智能体任务轮询 `/v1/chat/completions/result/{task_id}`，`elapsedSeconds` 每 2s +2（`frontend/providers/Stream.tsx:214`）。智能体调用 `review_workpaper` 启动后台审阅后立即返回，任务状态变 `completed`，循环退出，`elapsedSeconds` 冻结（通常仅几秒）。
   - 阶段②审阅状态轮询 `/review/{id}/status`，`reviewElapsedSeconds` 每 5s +5（`Stream.tsx:64`），最长 60 分钟。
   - 「处理耗时」卡片接的是 `elapsedSeconds`（`frontend/components/workbench/view-model.ts:207` 与 `:245`），而非 `reviewElapsedSeconds`。因此漫长的审阅阶段卡片不动。`reviewElapsedSeconds` 仅用于「审阅进行中… 已运行 Xs」文字。

2. **后端在 running 期间几乎不暴露中间信息**。`GET /review/{id}/status` 在 running 时仅返回 `{status:"running", started_at, source, stats:null, error:null}`；`stats` 要等审阅结束才填（`src/review/runner.py:74` `get_status`，`stats` 由 pipeline 结束时写入）。前端无从展示进度。

有利条件:
- `LLM_CALL_STATS`（`src/review/llm.py` 全局）在每次审阅开始前由 `runner.py:201` `clear()`，故它就是本次审阅的逐阶段 LLM 调用计数，进度快照可直接读取。
- `run_review`（`src/review/pipeline.py:76`）逐 sheet 顺序执行，`findings: List[Finding]` 随执行累加，「已发现问题数」可直接数当前 `findings`。

## 目标

- 审阅运行中，在右侧「调用追踪」面板实时展示: 当前阶段/sheet、各阶段 LLM 调用计数、已发现问题数（P0/P1/P2）、近期活动日志。
- 完成后该面板平滑切换为最终的调用追踪（现有行为不变）。
- 修复「处理耗时」卡片，使其在审阅阶段持续走表。
- 不引入 SSE/新基础设施，复用现有 5s 轮询与内存 registry。
- 进度是 best-effort: 进度缺失/出错时一切回退到现有行为，绝不影响审阅本身。

## 架构

```
pipeline (逐 sheet / 阶段)
   │ on_progress(payload)   每个 stage/sheet 边界调用 (try/except 包裹)
   ▼
runner: _REGISTRY[review_id]["progress"] = { ... }   (内存, 5s 内对 status 可见)
   │
   ▼
GET /review/{id}/status   返回新增 progress 字段
   │ 前端 5s 轮询 (已有)
   ▼
Stream.tsx: onProgress → reviewProgress state (进 context)
   │
   ▼
view-model: running 时把 reviewProgress 喂给「调用追踪」面板;
            「处理耗时」卡片改用总耗时 = elapsedSeconds + reviewElapsedSeconds
```

## 后端设计

### progress 数据结构

由 runner 维护并写入 `_REGISTRY[review_id]["progress"]`:

```python
{
  "stage": "checkpoints",            # 见下方阶段枚举
  "current_sheet": "SA-9 用户权限",   # 当前处理的 sheet 标题; 阶段无 sheet 时为 ""
  "llm_calls": {                      # 快照 LLM_CALL_STATS: stage -> 调用次数
    "checkpoints": 3,
    "evidence_steps": 0,
    "procedure_pairs": 0,
    "findings_review": 0,
    "hallucination": 0
  },
  "findings_so_far": {"P0": 0, "P1": 1, "P2": 2, "total": 3},
  "recent_events": [                  # 滚动, 仅保留最近 15 条
    {"t": "14:56:20", "msg": "完成 SA-9 checkpoint 评审（3 次调用）"}
  ],
  "updated_at": "2026-08-05T14:56:20"
}
```

`stage` 枚举: `starting` | `checkpoints` | `evidence_steps` | `procedure_pairs` | `findings_review` | `hallucination` | `done`。这些 stage 名取自 `run_review` 实际执行的阶段; 实现时以代码中真实阶段为准，不臆造。

### `run_review` 增加 on_progress 参数

`src/review/pipeline.py:76` 签名新增可选参数:

```python
async def run_review(
    *,
    wb, checkpoints=None, attachments=None, sheets=None, llm,
    attachments_preview=None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> Tuple[List[dict], dict]:
```

调用点（每个都包 `try/except Exception: pass`，回调失败不得影响审阅）:

1. 进入主 sheet 循环前: `stage="starting"`, `current_sheet=""`, `msg="开始审阅，共 N 个 sheet"`。
2. 每个 sheet 开始: `stage="checkpoints"`, `current_sheet=sheet`, `msg=f"开始处理 {sheet}"`。
3. 该 sheet 的 checkpoint 评审后: `msg=f"完成 {sheet} checkpoint 评审"`。
4. 该 sheet 的 evidence_steps 后: `msg=f"完成 {sheet} 证据-步骤一致性检查"`。
5. 该 sheet 的 procedure_pairs（含 A-C judgement）后: `msg=f"完成 {sheet} 程序配对检查"`。
6. 全部 sheet 完成、进入 `_llm_review_findings` 前: `stage="findings_review"`, `current_sheet=""`, `msg="进入发现复核"`。
7. 进入 cross-validation/challenge 前: `stage="hallucination"`, `msg="进入交叉验证/对抗挑战"`。
8. 结束: `stage="done"`, `msg="审阅完成"`。

每次调用，payload 包含 `{stage, current_sheet, llm_calls(快照 LLM_CALL_STATS), findings_so_far(数当前 findings 列表按 severity), msg}`。`findings_so_far` 计算: 遍历当前 `findings` 列表，按 `f.severity` 计数（缺失 severity 归 P2），`total = len(findings)`。

> 注: `recent_events` 滚动与 `updated_at` 由 runner 侧维护（见下），pipeline 每次只传 `msg` 与上述快照字段。

### runner 接线

`src/review/runner.py`:

- `_run_review` 在调用 `run_review` 时传入 `on_progress` 闭包。闭包接收 payload，合并进 `entry["progress"]`:
  - 覆盖 `stage` / `current_sheet` / `llm_calls` / `findings_so_far`。
  - 把 `{t: _now_time_only(), msg: payload["msg"]}` 追加到 `entry["progress"]["recent_events"]`，截断保留最近 15 条。
  - 更新 `updated_at`。
- `get_status`（`runner.py:74`）返回字典新增 `"progress": entry.get("progress")`。
- `entry` 初始化时不设 `progress`（`get_status` 返回 `progress: None`，前端按缺失处理）。
- 回调闭包内部也包 `try/except`，双保险。

`_now_time_only()` 返回 `HH:MM:SS` 字符串（用于 recent_events 显示）。`updated_at` 用完整 ISO 时间。

### 不变项

- `LLM_CALL_STATS.clear()`（`runner.py:201`）保持不变。
- pipeline 最终 `stats`（`pipeline.py:238`）保持不变; `progress` 与最终 `stats` 是两套数据，progress 仅用于运行中展示。

## 前端设计

### 类型

`frontend/components/workbench/types.ts` 新增:

```ts
export type ReviewProgress = {
  stage: string;
  current_sheet: string;
  llm_calls: Record<string, number>;
  findings_so_far: { P0: number; P1: number; P2: number; total: number };
  recent_events: { t: string; msg: string }[];
  updated_at: string;
};
```

### `pollReviewStatus`（`frontend/providers/Stream.tsx:57`）

`ReviewPollOpts` 新增 `onProgress?: (p: ReviewProgress) => void`。在循环内，`data.status === "running"` 且 `data.progress` 存在时调用 `opts.onProgress(data.progress)`（包 try/catch，畸形 payload 忽略）。

### Stream context（`Stream.tsx`）

- 新增 state `const [reviewProgress, setReviewProgress] = useState<ReviewProgress | null>(null);`
- `submit` 开始时 `setReviewProgress(null)`; `pollReviewStatus` 调用处传 `onProgress: setReviewProgress`。
- context value 与类型新增 `reviewProgress`。

### view-model（`frontend/components/workbench/view-model.ts`）

- `Input` 新增 `reviewProgress?: ReviewProgress | null`、`reviewStatus?`。
- 「处理耗时」卡片值改为总耗时:
  - 定义 `const totalElapsed = input.elapsedSeconds + (input.reviewElapsedSeconds ?? 0);`
  - findings 路径（`:207`）与 markdown 路径（`:245`）的「处理耗时」value 均改为 `` `${totalElapsed}s` ``。
- 「调用追踪」面板数据:
  - `WorkbenchViewModel` 新增字段 `liveProgress?: ReviewProgress`。
  - running 且 `reviewProgress` 存在时，`liveProgress = reviewProgress`（`toolTraces` 可为空）。
  - 完成时 `liveProgress = undefined`，维持现有 `toolTraces`（来自最终 stats）。
- `WorkbenchShell` 把 `liveProgress` 透传给 `ToolTracePanel`（`WorkbenchShell.tsx:70`）。

### ToolTracePanel（`frontend/components/workbench/ToolTracePanel.tsx`）

新增可选 prop `liveProgress?: ReviewProgress`。渲染优先级:

1. `liveProgress` 存在 → 渲染实时进度:
   - 顶部一行: 当前阶段 + current_sheet（如「checkpoints · SA-9 用户权限」）。
   - 一组小卡片/行: 各阶段 LLM 调用数（`checkpoints: 3` …）。
   - 已发现问题: `P0 x / P1 y / P2 z / 共 n`。
   - 近期事件: `recent_events` 倒序展示（最近在上），每条 `HH:MM:SS  msg`。
2. 否则 `traces.length > 0` → 现有 traces 列表（不变）。
3. 否则 → 现有空占位文字（不变）。

实时进度块内对 `liveProgress` 字段做防御: 缺字段按 0/空处理，不抛错。

## 错误处理

- `on_progress` 回调抛异常 → pipeline 内 `try/except Exception: pass` 吞掉; runner 闭包内同样 `try/except`。双保险，审阅不受影响。
- 前端收到畸形/缺字段 `progress` → `pollReviewStatus` 的 `onProgress` 包 try/catch 忽略; ToolTracePanel 对缺字段按 0/空渲染。
- `progress` 为 `null`（审阅重启后 registry 丢失、或旧逻辑）→ 一切回退现有行为（仅「审阅进行中… 已运行 Xs」文字）。
- timer 修复不影响完成态: 完成时 `reviewElapsedSeconds` 停止，`totalElapsed` 即定格总时长。

## 测试

### 后端（pytest, 用 `.venv/Scripts/python.exe -m pytest`）

- `tests/review/test_pipeline.py`（或新文件）: 用 mock llm + 极小 workbook 调 `run_review(on_progress=recorder)`，断言:
  - 回调被调用，且至少覆盖 `planner`、某 sheet 的 `checkpoints`、`findings_review`、`done` 等 stage。
  - payload 含 `stage/current_sheet/llm_calls/findings_so_far/msg` 且 `findings_so_far.total == len(当前 findings)` 合理单调非减。
  - `on_progress` 抛异常时 `run_review` 不崩（传一个会抛的回调，断言审阅仍正常返回）。
- `tests/review/test_runner.py`: 断言 `get_status` 返回含 `progress` 字段（running 时为已写入的 dict，初始为 None）。

### 前端（vitest, `--pool=forks --poolOptions.forks.singleFork=true`）

- `frontend/components/workbench/__tests__/view-model.test.ts`:
  - `reviewStatus==="running"` + `reviewProgress` 时，产出实时面板数据，且「处理耗时」= `elapsedSeconds + reviewElapsedSeconds`。
  - `reviewStatus==="completed"` 时维持现有 `toolTraces` 行为不变。
- ToolTracePanel 渲染测试（如已有则补充）: 传 `liveProgress` 时渲染阶段/计数/事件; 缺字段不崩。

## 范围与非目标

- 不做 SSE / WebSocket 实时推送（5s 轮询对几十分钟任务足够）。
- 不持久化 progress（重启丢失，与现有 registry 一致）。
- 不改 `LLM_CALL_STATS` 全局语义。
- 不改最终 findings / stats 结构。
- 不改后端审阅逻辑本身（仅加回调调用点）。
