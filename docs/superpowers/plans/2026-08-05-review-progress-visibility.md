# 审阅运行中进度可见性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 审阅长时间运行时，在「调用追踪」面板实时展示当前阶段/sheet、各阶段 LLM 调用计数、已发现问题数、近期活动日志；并修复「处理耗时」卡片在审阅阶段停止计时的问题。

**Architecture:** 后端 pipeline 通过 `on_progress` 回调把阶段进度写入内存 registry，`GET /review/{id}/status` 顺带返回；前端复用现有 5s 轮询解析 `progress`，running 时在「调用追踪」面板渲染实时进度，完成后切回最终调用追踪。「处理耗时」改用总耗时（agent + review）。

**Tech Stack:** Python (asyncio, openpyxl, pytest, pytest-asyncio) · TypeScript / React / Next.js / vitest / @testing-library/react

## Global Constraints

- 后端测试用项目 venv: `.venv/Scripts/python.exe -m pytest`（系统 Python 无 dev 依赖）。
- 前端测试: `npm test -- --pool=forks --poolOptions.forks.singleFork=true`（已在 vitest.config.ts 固化，`npm test` 即可）。
- `LLM_CALL_STATS` 是 `Dict[str, Dict[str, int]]`（`defaultdict(lambda: defaultdict(int))`），每次审阅前由 `runner.py` `clear()`；每阶段调用次数在 `["calls"]` 键下（`llm.py:93`）。
- 进度是 best-effort：回调异常不得影响审阅；前端缺字段按 0/空处理。
- 不引入 SSE/WebSocket；不持久化 progress；不改最终 findings/stats 结构；不改审阅逻辑本身。
- 提交规则遵循用户全局约定：仅在用户要求时 commit；在默认分支上先开分支。

**Spec:** `docs/superpowers/specs/2026-08-05-review-progress-visibility-design.md`

---

### Task 1: pipeline `run_review` 增加 `on_progress` 回调

**Files:**
- Modify: `src/review/pipeline.py`（`run_review` 签名 76-84 行；新增 `_emit_progress` helper；8 个调用点）
- Test: `tests/review/test_pipeline.py`

**Interfaces:**
- Consumes: `LLM_CALL_STATS`（已 import 于 `pipeline.py:24`）
- Produces: `run_review(*, ..., on_progress: Optional[Callable[[dict], None]] = None)`；`on_progress` 收到 `{stage, current_sheet, llm_calls, findings_so_far, msg}`。`stage ∈ starting|checkpoints|evidence_steps|procedure_pairs|findings_review|hallucination|done`

- [ ] **Step 1: Write failing tests**

追加到 `tests/review/test_pipeline.py` 末尾：

```python
@pytest.mark.asyncio
async def test_run_review_emits_progress_at_stages(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')
    recorded: list[dict] = []
    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
        on_progress=lambda p: recorded.append(p),
    )
    stages = [p["stage"] for p in recorded]
    assert "starting" in stages
    assert "done" in stages
    assert recorded[-1]["stage"] == "done"
    assert recorded[-1]["findings_so_far"]["total"] == len(findings)
    for p in recorded:
        assert {"stage", "current_sheet", "llm_calls", "findings_so_far", "msg"} <= set(p.keys())
        assert isinstance(p["llm_calls"], dict)
        assert isinstance(p["findings_so_far"]["total"], int)


@pytest.mark.asyncio
async def test_run_review_ignores_on_progress_exceptions(monkeypatch):
    monkeypatch.setenv("REVIEW_LLM_BACKOFF_SCALE", "0")
    wb = openpyxl.Workbook()
    wb.active.title = "Empty"
    llm = _FakeLLM('{"results": []}')

    def boom(p):
        raise RuntimeError("progress callback broken")

    findings, stats = await run_review(
        wb=wb, checkpoints={}, attachments_preview={}, sheets=None, llm=llm,
        on_progress=boom,
    )
    # review still completed despite the callback throwing
    assert stats["total_findings"] == len(findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_pipeline.py::test_run_review_emits_progress_at_stages tests/review/test_pipeline.py::test_run_review_ignores_on_progress_exceptions -v`
Expected: FAIL — `TypeError: run_review() got an unexpected keyword argument 'on_progress'`.

- [ ] **Step 3: Add `_emit_progress` helper**

在 `src/review/pipeline.py` 的 `_parse_sheet_filter` 函数之前（约 37 行上方）插入：

```python
def _emit_progress(on_progress, stage: str, current_sheet: str, findings, msg: str) -> None:
    """Best-effort progress report. Never raises — pipeline must not break on a bad callback."""
    if on_progress is None:
        return
    try:
        sev = {"P0": 0, "P1": 0, "P2": 0}
        for f in findings:
            s = getattr(f, "severity", None) or "P2"
            if s not in sev:
                s = "P2"
            sev[s] += 1
        on_progress({
            "stage": stage,
            "current_sheet": current_sheet or "",
            "llm_calls": {k: int(v.get("calls", 0)) for k, v in LLM_CALL_STATS.items()},
            "findings_so_far": {
                "P0": sev["P0"], "P1": sev["P1"], "P2": sev["P2"],
                "total": len(findings),
            },
            "msg": msg,
        })
    except Exception:
        pass
```

- [ ] **Step 4: Add `on_progress` param to `run_review`**

修改 `src/review/pipeline.py:76` 的签名，在 `attachments_preview` 后加参数：

```python
async def run_review(
    *,
    wb: openpyxl.Workbook,
    checkpoints: Optional[Dict[str, List[str]]] = None,
    attachments: Optional[Dict[str, object]] = None,
    sheets: Optional[str] = None,
    llm,
    attachments_preview: Optional[Dict[str, object]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> Tuple[List[dict], dict]:
```

并在文件顶部 `from typing import ...` 行补上 `Callable`（若尚未导入）：把 `from typing import Dict, List, Optional, Tuple` 改为 `from typing import Callable, Dict, List, Optional, Tuple`。

- [ ] **Step 5: Insert the 8 progress call sites**

在 `src/review/pipeline.py` 中按下表插入调用（行号以当前文件为准，插入到指定代码之后）：

(a) sheet 循环开始前——在 `for sheet in target:`（146 行）之前插入：
```python
    _emit_progress(on_progress, "starting", "", findings, f"开始审阅，共 {len(target)} 个 sheet")
```

(b) sheet 循环内、`ws = wb[sheet]`（150 行）之后插入：
```python
        _emit_progress(on_progress, "checkpoints", sheet, findings, f"开始处理 {sheet}")
```

(c) checkpoint 评审之后——在 `findings += await _llm_check_sheet_by_checkpoints(...)` 块（183-188 行）之后插入：
```python
        _emit_progress(on_progress, "checkpoints", sheet, findings, f"完成 {sheet} checkpoint 评审")
```

(d) evidence_steps 之后——在 `_llm_check_evidence_vs_steps(...)` 块（193-197 行）之后插入：
```python
        _emit_progress(on_progress, "evidence_steps", sheet, findings, f"完成 {sheet} 证据-步骤一致性检查")
```

(e) procedure_pairs A-C judgement 之后——在 `findings += ac_findings`（206 行）之后插入：
```python
        _emit_progress(on_progress, "procedure_pairs", sheet, findings, f"完成 {sheet} 程序配对检查")
```

(f) `_llm_review_findings` 之前——在 `review = await _llm_review_findings(...)`（211 行）之前插入：
```python
    _emit_progress(on_progress, "findings_review", "", findings, "进入发现复核")
```

(g) cross-validation/challenge 之前——在 `for idx, f in enumerate(findings_sorted, start=1):`（216 行）之前插入：
```python
    _emit_progress(on_progress, "hallucination", "", findings_sorted, "进入交叉验证/对抗挑战")
```

(h) 结束——在 `stats = {`（238 行）之前插入：
```python
    _emit_progress(on_progress, "done", "", findings_sorted, "审阅完成")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_pipeline.py -v`
Expected: PASS（含两个新测试 + 既有测试全过）。

- [ ] **Step 7: Run full review suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: 全部 PASS（170+ 用例）。

---

### Task 2: runner 接线 + `get_status` 暴露 progress

**Files:**
- Modify: `src/review/runner.py`（新增 `_make_progress_cb`、`_now_time_only`；`_run_review` 调用处传 `on_progress`；`get_status` 返回 `progress`）
- Test: `tests/review/test_runner.py`

**Interfaces:**
- Consumes: Task 1 的 `run_review(on_progress=...)`
- Produces: `get_status(review_id)["progress"]` = `{stage, current_sheet, llm_calls, findings_so_far, recent_events, updated_at}` 或 `None`

- [ ] **Step 1: Write failing test**

追加到 `tests/review/test_runner.py` 末尾：

```python
@pytest.mark.asyncio
async def test_progress_callback_updates_status():
    _REGISTRY.clear()
    review_id = "test-rid"
    _REGISTRY[review_id] = {
        "status": "running",
        "started_at": runner._now(),
        "source": "wp.xlsx",
    }
    # before any progress, status.progress is None
    assert get_status(review_id)["progress"] is None

    cb = runner._make_progress_cb(review_id)
    cb({
        "stage": "checkpoints",
        "current_sheet": "SA-4c",
        "llm_calls": {"checkpoints": 2},
        "findings_so_far": {"P0": 0, "P1": 1, "P2": 0, "total": 1},
        "msg": "完成 SA-4c checkpoint 评审",
    })
    st = get_status(review_id)
    assert st["progress"]["stage"] == "checkpoints"
    assert st["progress"]["current_sheet"] == "SA-4c"
    assert st["progress"]["findings_so_far"]["total"] == 1
    assert st["progress"]["recent_events"][-1]["msg"] == "完成 SA-4c checkpoint 评审"
    assert len(st["progress"]["recent_events"]) == 1

    # rolling window caps recent_events at 15
    for i in range(20):
        cb({
            "stage": "checkpoints", "current_sheet": "", "llm_calls": {},
            "findings_so_far": {"P0": 0, "P1": 0, "P2": 0, "total": 0},
            "msg": f"evt {i}",
        })
    assert len(get_status(review_id)["progress"]["recent_events"]) == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_runner.py::test_progress_callback_updates_status -v`
Expected: FAIL — `AttributeError: module 'review.runner' has no attribute '_make_progress_cb'`.

- [ ] **Step 3: Add `_now_time_only` and `_make_progress_cb`**

在 `src/review/runner.py` 的 `_now` 函数（约 70 行）之后插入：

```python
def _now_time_only() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _make_progress_cb(review_id: str):
    """Return an on_progress callback that updates the registry entry's progress.

    Best-effort: swallows all exceptions so a callback bug can never break the review.
    Maintains a rolling `recent_events` list (last 15).
    """
    def _cb(payload: dict) -> None:
        try:
            entry = _REGISTRY.get(review_id)
            if entry is None:
                return
            prev = entry.get("progress") or {}
            events = list(prev.get("recent_events") or [])
            events.append({"t": _now_time_only(), "msg": str(payload.get("msg", ""))})
            events = events[-15:]
            entry["progress"] = {
                "stage": payload.get("stage", ""),
                "current_sheet": payload.get("current_sheet", ""),
                "llm_calls": payload.get("llm_calls", {}) or {},
                "findings_so_far": payload.get("findings_so_far") or {
                    "P0": 0, "P1": 0, "P2": 0, "total": 0,
                },
                "recent_events": events,
                "updated_at": _now(),
            }
        except Exception:
            pass
    return _cb
```

- [ ] **Step 4: Wire `on_progress` into the `run_review` call**

在 `src/review/runner.py` 的 `_run_review` 中，把 `run_review(...)` 调用（203-210 行）改为多传 `on_progress`：

```python
        findings, stats = await run_review(
            wb=wb,
            checkpoints=checkpoints,
            attachments=attachments,
            attachments_preview=attachments,
            sheets=sheets,
            llm=llm,
            on_progress=_make_progress_cb(review_id),
        )
```

- [ ] **Step 5: Expose `progress` in `get_status`**

在 `src/review/runner.py:74` 的 `get_status` 返回字典中加入 `"progress"`（插在 `"stats"` 之后、`"error"` 之前）：

```python
    status = {
        "review_id": review_id,
        "status": entry["status"],
        "started_at": entry.get("started_at"),
        "source": entry.get("source"),
        "stats": entry.get("stats"),
        "progress": entry.get("progress"),
        "error": entry.get("error"),
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/review/test_runner.py -v`
Expected: PASS（含新测试 + 既有测试）。

- [ ] **Step 7: Run full review suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/review/ -q`
Expected: 全部 PASS。

---

### Task 3: 前端 types + view-model（timer 修复 + liveProgress）

**Files:**
- Modify: `frontend/components/workbench/types.ts`（新增 `ReviewProgress` 类型；`WorkbenchViewModel` 加 `liveProgress`）
- Modify: `frontend/components/workbench/view-model.ts`（`Input` 加 `reviewProgress`；timer 改总耗时；产出 `liveProgress`）
- Test: `frontend/components/workbench/__tests__/view-model.test.ts`

**Interfaces:**
- Produces: `ReviewProgress` 类型；`WorkbenchViewModel.liveProgress?: ReviewProgress | null`；「处理耗时」= `elapsedSeconds + reviewElapsedSeconds`

- [ ] **Step 1: Write failing tests**

追加到 `frontend/components/workbench/__tests__/view-model.test.ts` 的 `describe` 块内：

```ts
  it("shows total elapsed time and live progress while review is running", () => {
    const model = buildWorkbenchViewModel({
      status: "running",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 6,
      reviewStatus: "running",
      reviewElapsedSeconds: 120,
      reviewProgress: {
        stage: "checkpoints",
        current_sheet: "SA-9",
        llm_calls: { checkpoints: 3 },
        findings_so_far: { P0: 0, P1: 1, P2: 2, total: 3 },
        recent_events: [{ t: "10:00:00", msg: "完成 SA-9 checkpoint 评审" }],
        updated_at: "2026-08-05T10:00:00",
      },
      error: null,
    });
    const metric = model.summaryMetrics.find((m) => m.label === "处理耗时");
    expect(metric?.value).toBe("126s");
    expect(model.liveProgress?.stage).toBe("checkpoints");
    expect(model.liveProgress?.findings_so_far.total).toBe(3);
  });

  it("does not surface live progress when review is not running", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "",
      contentBlocks: [],
      messages: [],
      isLoading: false,
      elapsedSeconds: 42,
      error: null,
    });
    expect(model.liveProgress).toBeUndefined();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- --run view-model`
Expected: FAIL — `ReviewProgress` 类型缺失 / `model.liveProgress` 为 `undefined` / 处理耗时值不符。

- [ ] **Step 3: Add `ReviewProgress` type and `liveProgress` field**

在 `frontend/components/workbench/types.ts` 的 `ToolTrace` 类型之后（约 35 行）插入：

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

并在 `WorkbenchViewModel`（49-60 行）的 `toolTraces` 之后加一行：

```ts
  toolTraces: ToolTrace[];
  liveProgress?: ReviewProgress | null;
  understoodRequirement?: UnderstoodRequirement | null;
```

- [ ] **Step 4: Update `view-model.ts` — import, Input, timer, liveProgress**

(a) 顶部 import 加 `ReviewProgress`：

```ts
import type {
  AnalysisSection,
  EvidenceItem,
  Finding,
  FindingsPayload,
  ProgressStep,
  ReviewProgress,
  ToolTrace,
  UnderstoodRequirement,
  WorkbenchStatus,
  WorkbenchViewModel,
} from "./types";
```

(b) `Input` 类型（13-38 行）的 `understoodRequirement` 之前加：

```ts
  reviewProgress?: ReviewProgress | null;
  understoodRequirement?: UnderstoodRequirement | null;
```

(c) 在 `buildWorkbenchViewModel` 函数开头（`const uploaded = uploadedEvidence(input);` 之后）加总耗时与 liveProgress 计算：

```ts
  const totalElapsed = input.elapsedSeconds + (input.reviewElapsedSeconds ?? 0);
  const liveProgress =
    input.reviewStatus === "running" && input.reviewProgress
      ? input.reviewProgress
      : undefined;
```

(d) findings 路径（约 207 行）的「处理耗时」改为总耗时：
```ts
      { label: "处理耗时", value: `${totalElapsed}s` },
```

(e) markdown 路径（约 245 行）的「处理耗时」同样改为：
```ts
    { label: "处理耗时", value: `${totalElapsed}s` },
```

(f) 两个 `return {` 对象中，在 `toolTraces,` 之后各加一行 `liveProgress,`（findings 路径约 219 行、markdown 路径约 250 行）。

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- --run view-model`
Expected: PASS（含两个新测试 + 既有 view-model 测试）。

- [ ] **Step 6: Run full frontend test suite + lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: 全部 PASS，lint 无新增错误。

---

### Task 4: ToolTracePanel 渲染 liveProgress

**Files:**
- Modify: `frontend/components/workbench/ToolTracePanel.tsx`
- Test: `frontend/components/workbench/__tests__/ToolTracePanel.test.tsx`（新建）

**Interfaces:**
- Consumes: `ReviewProgress` 类型（Task 3）
- Produces: `ToolTracePanel({ traces, liveProgress? })`；`liveProgress` 存在时渲染实时进度块

- [ ] **Step 1: Write failing test**

新建 `frontend/components/workbench/__tests__/ToolTracePanel.test.tsx`：

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToolTracePanel } from "../ToolTracePanel";
import type { ReviewProgress } from "../types";

const progress: ReviewProgress = {
  stage: "checkpoints",
  current_sheet: "SA-9 用户权限",
  llm_calls: { checkpoints: 3, evidence_steps: 1 },
  findings_so_far: { P0: 0, P1: 1, P2: 2, total: 3 },
  recent_events: [
    { t: "10:00:02", msg: "完成 SA-9 checkpoint 评审" },
    { t: "10:00:01", msg: "开始处理 SA-9" },
  ],
  updated_at: "2026-08-05T10:00:02",
};

describe("ToolTracePanel", () => {
  it("renders live progress when provided", () => {
    render(<ToolTracePanel traces={[]} liveProgress={progress} />);
    expect(screen.getByText(/checkpoints/)).toBeInTheDocument();
    expect(screen.getByText(/SA-9 用户权限/)).toBeInTheDocument();
    expect(screen.getByText(/checkpoints.*3|3.*checkpoints/)).toBeInTheDocument();
    expect(screen.getByText(/共\s*3/)).toBeInTheDocument();
    expect(screen.getByText(/完成 SA-9 checkpoint 评审/)).toBeInTheDocument();
  });

  it("renders traces when no live progress", () => {
    render(
      <ToolTracePanel
        traces={[{ id: "t1", name: "analyze_worksheet", argsSummary: "{}" }]}
      />,
    );
    expect(screen.getByText("analyze_worksheet")).toBeInTheDocument();
  });

  it("renders placeholder when empty", () => {
    render(<ToolTracePanel traces={[]} />);
    expect(screen.getByText(/工具调用将显示在此处/)).toBeInTheDocument();
  });

  it("does not crash on missing progress fields", () => {
    render(
      <ToolTracePanel
        traces={[]}
        liveProgress={
          { stage: "checkpoints" } as unknown as ReviewProgress
        }
      />,
    );
    expect(screen.getByText(/checkpoints/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- --run ToolTracePanel`
Expected: FAIL — `liveProgress` prop 不存在 / 实时进度未渲染。

- [ ] **Step 3: Implement liveProgress rendering in ToolTracePanel**

替换 `frontend/components/workbench/ToolTracePanel.tsx` 全文：

```tsx
import type { ReviewProgress, ToolTrace } from "./types";

export function ToolTracePanel({
  traces,
  liveProgress,
}: {
  traces: ToolTrace[];
  liveProgress?: ReviewProgress | null;
}) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">调用追踪</h2>
      {liveProgress ? (
        <LiveProgressView progress={liveProgress} />
      ) : traces.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          任务运行后，工具调用将显示在此处。
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {traces.map((trace) => (
            <li
              key={trace.id}
              className="rounded-xl border px-3 py-2 text-sm"
            >
              <p className="font-medium">{trace.name}</p>
              <p className="mt-1 break-all text-xs text-muted-foreground">
                {trace.argsSummary}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LiveProgressView({ progress }: { progress: ReviewProgress }) {
  const fs = progress.findings_so_far ?? { P0: 0, P1: 0, P2: 0, total: 0 };
  const calls = progress.llm_calls ?? {};
  const events = progress.recent_events ?? [];
  return (
    <div className="mt-3 space-y-3 text-sm">
      <div className="rounded-xl border px-3 py-2">
        <p className="font-medium">
          {progress.stage || "运行中"}
          {progress.current_sheet ? ` · ${progress.current_sheet}` : ""}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          LLM 调用：{Object.keys(calls).length === 0
            ? "0"
            : Object.entries(calls).map(([k, v]) => `${k} ${v}`).join("，")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          已发现：P0 {fs.P0 ?? 0} / P1 {fs.P1 ?? 0} / P2 {fs.P2 ?? 0} / 共 {fs.total ?? 0}
        </p>
      </div>
      {events.length > 0 && (
        <ul className="space-y-1">
          {[...events].reverse().map((e, i) => (
            <li key={`${e.t}-${i}`} className="break-all text-xs text-muted-foreground">
              <span className="font-mono">{e.t}</span> {e.msg}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- --run ToolTracePanel`
Expected: PASS（4 个用例）。

- [ ] **Step 5: Run full frontend suite + lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: 全部 PASS。

---

### Task 5: Stream 接线 + WorkbenchShell/thread 透传 liveProgress

**Files:**
- Modify: `frontend/providers/Stream.tsx`（`ReviewPollOpts` 加 `onProgress`；`pollReviewStatus` 解析 `progress`；新增 `reviewProgress` state + context）
- Modify: `frontend/components/workbench/WorkbenchShell.tsx`（props 加 `liveProgress`，透传给 `ToolTracePanel`）
- Modify: `frontend/components/thread/index.tsx`（view-model 入参加 `reviewProgress`；Shell 传 `liveProgress={model.liveProgress}`）
- Verify: `npm run lint && npm run build`（Stream provider 涉及 fetch，按集成层验证；逻辑由 Task 3/4 测试覆盖）

**Interfaces:**
- Consumes: `ReviewProgress`（Task 3）；后端 `GET /review/{id}/status` 的 `progress` 字段（Task 2）
- Produces: `useStreamContext().reviewProgress`；运行中「调用追踪」面板显示实时进度

- [ ] **Step 1: Extend `pollReviewStatus` with `onProgress`**

在 `frontend/providers/Stream.tsx`：

(a) `ReviewPollOpts`（48-55 行）加字段：
```ts
type ReviewPollOpts = {
  backendUrl: string;
  reviewId: string;
  signal: () => AbortSignal | undefined;
  onTick: (elapsedSeconds: number) => void;
  onProgress?: (progress: ReviewProgress) => void;
  onCompleted: (payload: FindingsPayload) => void;
  onError: (message: string) => void;
};
```

(b) 在 `pollReviewStatus` 的 `// status === "running" -> keep polling`（89 行）之前插入：
```ts
      if (data.status === "running" && data.progress && opts.onProgress) {
        try {
          opts.onProgress(data.progress as ReviewProgress);
        } catch {
          // malformed progress payload — ignore, keep polling
        }
      }
```

- [ ] **Step 2: Add `reviewProgress` state + context**

在 `frontend/providers/Stream.tsx`：

(a) 顶部 import 加 `ReviewProgress` 类型（从 `components/workbench/types`）。同时把 `StreamContextType`（约 18-30 行的接口/类型定义）加 `reviewProgress: ReviewProgress | null;`。

(b) 在 `reviewElapsedSeconds` state（125 行）之后加：
```ts
  const [reviewProgress, setReviewProgress] = useState<ReviewProgress | null>(null);
```

(c) `submit` 的重置区（约 153-157 行，`setReviewStatus("idle")` 附近）加：
```ts
    setReviewProgress(null);
```

(d) `pollReviewStatus({...})` 调用处（259-272 行）加 `onProgress: setReviewProgress`：
```ts
          await pollReviewStatus({
            backendUrl,
            reviewId,
            signal: () => reviewAbortRef.current?.signal,
            onTick: (secs) => setReviewElapsedSeconds(secs),
            onProgress: setReviewProgress,
            onCompleted: (payload) => {
              setFindings(payload);
              setReviewStatus("completed");
            },
            onError: (msg) => {
              setError(msg);
              setReviewStatus("error");
            },
          });
```

(e) context value（304-316 行）加 `reviewProgress,`。

- [ ] **Step 3: Thread `liveProgress` through WorkbenchShell**

(a) `frontend/components/workbench/WorkbenchShell.tsx` 的 props 类型（18-35 行）加：
```ts
  liveProgress?: ReviewProgress | null;
```
并在该文件顶部 import 加 `ReviewProgress`（与其它 type import 一起）。

(b) `<ToolTracePanel>` 调用处（70 行）改为：
```tsx
          <ToolTracePanel traces={props.toolTraces} liveProgress={props.liveProgress} />
```

- [ ] **Step 4: Wire `reviewProgress` into view-model and Shell in thread/index.tsx**

(a) `frontend/components/thread/index.tsx` 的 `buildWorkbenchViewModel({...})`（179-191 行）加一行：
```ts
    reviewProgress: stream.reviewProgress,
```

(b) `<WorkbenchShell>`（213 行起）的 props 中，在 `toolTraces={model.toolTraces}`（238 行）之后加：
```tsx
        liveProgress={model.liveProgress}
```

- [ ] **Step 5: Verify build + lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint 无新增错误；build 成功（无类型错误）。

- [ ] **Step 6: Manual end-to-end smoke（需后端在跑）**

启动后端（`bash scripts/http_run.sh -p 5000`）+ 前端（`cd frontend && NODE_OPTIONS="--max-old-space-size=4096 --max-semi-space-size=256" npm run dev`），上传一个底稿发起审阅，观察：
- 「处理耗时」卡片在审阅阶段持续走表（不再几秒后冻住）。
- 右侧「调用追踪」面板在运行中显示当前 stage/sheet、LLM 调用数、已发现 P0/P1/P2、近期事件日志；约每 5s 刷新。
- 审阅完成后面板切回最终调用追踪（或空）。
Expected: 上述行为均成立。

---

## Self-Review 记录

- **Spec 覆盖**: 后端 on_progress 8 调用点（Task 1）、runner 接线 + get_status（Task 2）、timer 修复 + liveProgress（Task 3）、ToolTracePanel 实时视图（Task 4）、Stream 接线 + 透传（Task 5）——spec 各节均有对应任务。
- **占位符扫描**: 无 TBD/TODO；每个代码步骤含完整代码。
- **类型一致性**: `ReviewProgress` 字段名（stage/current_sheet/llm_calls/findings_so_far/recent_events/updated_at）在 types.ts、view-model、ToolTracePanel、Stream、后端 payload 全程一致；`WorkbenchViewModel.liveProgress` 与 Shell/thread 透传一致；`run_review(on_progress=...)` 与 runner 调用一致。
- **范围**: 单一实现计划可覆盖，5 个任务顺序无环依赖（Task 1→2 后端；Task 3→4→5 前端，Task 3 产出类型供 4/5 使用）。
