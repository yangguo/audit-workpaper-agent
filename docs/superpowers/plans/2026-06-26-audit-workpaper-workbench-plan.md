# Audit Workpaper Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current chat-style `frontend/` homepage into a structured audit workbench with dedicated intake, evidence, summary, result, progress, and trace areas, while fixing the confirmed Web Interface Guidelines issues.

**Architecture:** Keep the existing Next.js App Router app and `StreamProvider`, but stop driving the entire UI directly from a message bubble layout. Introduce a small workbench component tree plus a derived view model that maps provider state into `summaryMetrics`, `analysisSections`, `evidenceItems`, `progressSteps`, and `toolTraces`. Preserve current backend contracts and file-upload behavior, but present them inside a stable desktop-first three-column workbench shell.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS 4, existing Radix/shadcn-style UI components, Vitest + Testing Library for new frontend tests.

---

## File Structure (Create/Modify Map)

**Modify**
- `frontend/package.json`
  - Add frontend test scripts and test dependencies.
- `frontend/app/page.tsx`
  - Replace direct `Thread` mount with workbench page shell; fix fallback copy to `Loading…`.
- `frontend/app/layout.tsx`
  - Update page title and description to match audit workbench positioning.
- `frontend/components/thread/index.tsx`
  - Reduce to orchestration layer or compatibility wrapper instead of monolithic page layout.
- `frontend/hooks/use-file-upload.tsx`
  - Expose evidence-friendly upload state and retry/remove behavior needed by the sidebar.
- `frontend/providers/Stream.tsx`
  - Add normalized task status and derived progress/result state helpers without changing backend protocol.

**Create**
- `frontend/components/workbench/WorkbenchShell.tsx`
- `frontend/components/workbench/WorkbenchHeader.tsx`
- `frontend/components/workbench/ReviewIntakePanel.tsx`
- `frontend/components/workbench/EvidenceListPanel.tsx`
- `frontend/components/workbench/ResultSummaryCards.tsx`
- `frontend/components/workbench/AnalysisResultPanel.tsx`
- `frontend/components/workbench/ProgressStatusPanel.tsx`
- `frontend/components/workbench/ToolTracePanel.tsx`
- `frontend/components/workbench/EmptyStatePanel.tsx`
- `frontend/components/workbench/types.ts`
- `frontend/components/workbench/view-model.ts`
- `frontend/components/workbench/__tests__/view-model.test.ts`
- `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
- `frontend/test/setup.ts`
- `frontend/vitest.config.ts`

**Review while implementing**
- `frontend/components/thread/messages/ai.tsx`
- `frontend/components/thread/messages/human.tsx`
- `frontend/components/thread/markdown-text.tsx`
- `frontend/components/ui/button.tsx`
- `frontend/components/ui/input.tsx`
- `frontend/components/ui/textarea.tsx`

---

### Task 1: Add frontend test harness for the new workbench

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/test/setup.ts`

- [ ] **Step 1: Write the failing test harness config first**

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test/setup.ts"],
    css: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
```

Create `frontend/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Add the failing test scripts and dependencies**

Update `frontend/package.json`:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.8.0",
    "@testing-library/react": "^16.3.0",
    "@testing-library/user-event": "^14.6.1",
    "jsdom": "^26.1.0",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 3: Run the empty test runner to verify the harness fails cleanly before feature tests exist**

Run: `npm run test -- --passWithNoTests=false`
Expected: FAIL with “No test files found”

- [ ] **Step 4: Install dependencies**

Run: `npm install`
Expected: packages added and lockfile updated without peer dependency errors

- [ ] **Step 5: Run the test runner again and confirm the same intentional failure**

Run: `npm run test -- --passWithNoTests=false`
Expected: FAIL with “No test files found”

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/test/setup.ts
git commit -m "test: add vitest harness for workbench refactor"
```

---

### Task 2: Define a stable workbench view model before changing layout

**Files:**
- Create: `frontend/components/workbench/types.ts`
- Create: `frontend/components/workbench/view-model.ts`
- Create: `frontend/components/workbench/__tests__/view-model.test.ts`

- [ ] **Step 1: Write the failing view-model test**

Create `frontend/components/workbench/__tests__/view-model.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildWorkbenchViewModel } from "../view-model";

describe("buildWorkbenchViewModel", () => {
  it("derives evidence, summary metrics, result sections, and progress state", () => {
    const model = buildWorkbenchViewModel({
      status: "completed",
      archiveUrl: "https://example.com/audit.zip",
      contentBlocks: [
        { type: "text", text: "Workbook.xlsx", metadata: { name: "Workbook.xlsx" } },
        { type: "text", text: "Evidence.pdf", metadata: { name: "Evidence.pdf" } },
      ],
      messages: [
        {
          id: "ai-1",
          type: "ai",
          content: "## 结论摘要\n存在 3 个异常点\n\n## 建议动作\n复核收入截止测试",
          tool_calls: [{ id: "tool-1", name: "analyze_worksheet", args: { file_path: "assets/uploads/a.xlsx" } }],
        },
      ],
      isLoading: false,
      elapsedSeconds: 42,
      error: null,
    });

    expect(model.evidenceItems).toHaveLength(2);
    expect(model.summaryMetrics.find((item) => item.label === "异常项")?.value).toBe("3");
    expect(model.analysisSections.map((section) => section.title)).toEqual(["结论摘要", "建议动作"]);
    expect(model.progressSteps.at(-1)?.status).toBe("completed");
    expect(model.toolTraces[0]?.name).toBe("analyze_worksheet");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/view-model.test.ts`
Expected: FAIL with “Cannot find module '../view-model'”

- [ ] **Step 3: Add the view-model types**

Create `frontend/components/workbench/types.ts`:

```ts
export type WorkbenchStatus = "idle" | "uploading" | "running" | "completed" | "failed" | "timeout";

export type EvidenceItem = {
  id: string;
  name: string;
  source: "upload" | "link";
  status: "ready" | "uploading" | "failed";
};

export type SummaryMetric = {
  label: string;
  value: string;
};

export type AnalysisSection = {
  title: string;
  body: string;
};

export type ProgressStep = {
  label: string;
  status: "pending" | "active" | "completed" | "failed";
};

export type ToolTrace = {
  id: string;
  name: string;
  argsSummary: string;
};

export type WorkbenchViewModel = {
  status: WorkbenchStatus;
  evidenceItems: EvidenceItem[];
  summaryMetrics: SummaryMetric[];
  analysisSections: AnalysisSection[];
  progressSteps: ProgressStep[];
  toolTraces: ToolTrace[];
  lastUpdatedLabel: string;
};
```

- [ ] **Step 4: Write the minimal implementation**

Create `frontend/components/workbench/view-model.ts`:

```ts
import type {
  AnalysisSection,
  ToolTrace,
  WorkbenchStatus,
  WorkbenchViewModel,
} from "./types";

type Input = {
  status: WorkbenchStatus;
  archiveUrl: string;
  contentBlocks: Array<{ type: string; text?: string; metadata?: { name?: string } }>;
  messages: Array<{ id: string; type: string; content: string; tool_calls?: Array<{ id: string; name: string; args: Record<string, unknown> }> }>;
  isLoading: boolean;
  elapsedSeconds: number;
  error: unknown;
};

function splitSections(content: string): AnalysisSection[] {
  const matches = content.split(/^## /m).map((item) => item.trim()).filter(Boolean);
  if (matches.length <= 1) return [{ title: "分析结果", body: content.trim() }];
  return matches.map((item) => {
    const [title, ...body] = item.split("\n");
    return { title: title.trim(), body: body.join("\n").trim() };
  });
}

export function buildWorkbenchViewModel(input: Input): WorkbenchViewModel {
  const latestAi = [...input.messages].reverse().find((message) => message.type === "ai");
  const analysisSections = latestAi?.content ? splitSections(latestAi.content) : [];
  const anomalyMatch = latestAi?.content.match(/(\d+)\s*个异常/);
  const toolTraces: ToolTrace[] = (latestAi?.tool_calls ?? []).map((call) => ({
    id: call.id,
    name: call.name,
    argsSummary: JSON.stringify(call.args),
  }));

  return {
    status: input.error ? "failed" : input.isLoading ? "running" : input.status,
    evidenceItems: input.contentBlocks
      .filter((block) => block.metadata?.name)
      .map((block, index) => ({
        id: `${block.metadata?.name}-${index}`,
        name: block.metadata?.name ?? "未命名文件",
        source: "upload",
        status: "ready",
      }))
      .concat(
        input.archiveUrl
          ? [{ id: "archive-url", name: input.archiveUrl, source: "link", status: "ready" as const }]
          : [],
      ),
    summaryMetrics: [
      { label: "风险等级", value: latestAi?.content.includes("高风险") ? "高" : "中" },
      { label: "异常项", value: anomalyMatch?.[1] ?? "0" },
      { label: "处理耗时", value: `${input.elapsedSeconds}s` },
    ],
    analysisSections,
    progressSteps: [
      { label: "准备材料", status: "completed" },
      { label: "分析底稿", status: input.isLoading ? "active" : input.error ? "failed" : "completed" },
      { label: "生成结论", status: input.isLoading ? "pending" : input.error ? "failed" : "completed" },
    ],
    toolTraces,
    lastUpdatedLabel: input.elapsedSeconds > 0 ? `${input.elapsedSeconds}s 前更新` : "刚刚更新",
  };
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/view-model.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/components/workbench/types.ts frontend/components/workbench/view-model.ts frontend/components/workbench/__tests__/view-model.test.ts
git commit -m "feat: add workbench view model"
```

---

### Task 3: Build the workbench shell and empty state before wiring live data

**Files:**
- Create: `frontend/components/workbench/WorkbenchShell.tsx`
- Create: `frontend/components/workbench/WorkbenchHeader.tsx`
- Create: `frontend/components/workbench/ReviewIntakePanel.tsx`
- Create: `frontend/components/workbench/EvidenceListPanel.tsx`
- Create: `frontend/components/workbench/ResultSummaryCards.tsx`
- Create: `frontend/components/workbench/AnalysisResultPanel.tsx`
- Create: `frontend/components/workbench/ProgressStatusPanel.tsx`
- Create: `frontend/components/workbench/ToolTracePanel.tsx`
- Create: `frontend/components/workbench/EmptyStatePanel.tsx`
- Create: `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`

- [ ] **Step 1: Write the failing shell test**

Create `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkbenchShell } from "../WorkbenchShell";

describe("WorkbenchShell", () => {
  it("renders the audit workbench regions", () => {
    render(
      <WorkbenchShell
        header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "系统正常" }}
        summaryMetrics={[{ label: "异常项", value: "3" }]}
        analysisSections={[{ title: "结论摘要", body: "存在 3 个异常项" }]}
        evidenceItems={[{ id: "1", name: "Workbook.xlsx", source: "upload", status: "ready" }]}
        progressSteps={[{ label: "分析底稿", status: "active" }]}
        toolTraces={[{ id: "t1", name: "analyze_worksheet", argsSummary: '{"file_path":"assets/uploads/a.xlsx"}' }]}
        isEmpty={false}
      />
    );

    expect(screen.getByRole("heading", { name: "审计底稿审阅" })).toBeInTheDocument();
    expect(screen.getByText("证据列表")).toBeInTheDocument();
    expect(screen.getByText("分析结果")).toBeInTheDocument();
    expect(screen.getByText("进度状态")).toBeInTheDocument();
    expect(screen.getByText("调用追踪")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: FAIL with “Cannot find module '../WorkbenchShell'”

- [ ] **Step 3: Write the minimal shell and leaf components**

Create `frontend/components/workbench/WorkbenchHeader.tsx`:

```tsx
export function WorkbenchHeader({
  title,
  subtitle,
  statusLabel,
}: {
  title: string;
  subtitle: string;
  statusLabel: string;
}) {
  return (
    <header className="flex items-center justify-between border-b bg-white px-6 py-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
        {statusLabel}
      </div>
    </header>
  );
}
```

Create `frontend/components/workbench/WorkbenchShell.tsx`:

```tsx
import { WorkbenchHeader } from "./WorkbenchHeader";
import { EmptyStatePanel } from "./EmptyStatePanel";
import { EvidenceListPanel } from "./EvidenceListPanel";
import { ResultSummaryCards } from "./ResultSummaryCards";
import { AnalysisResultPanel } from "./AnalysisResultPanel";
import { ProgressStatusPanel } from "./ProgressStatusPanel";
import { ToolTracePanel } from "./ToolTracePanel";
import type { AnalysisSection, EvidenceItem, ProgressStep, SummaryMetric, ToolTrace } from "./types";

export function WorkbenchShell(props: {
  header: { title: string; subtitle: string; statusLabel: string };
  summaryMetrics: SummaryMetric[];
  analysisSections: AnalysisSection[];
  evidenceItems: EvidenceItem[];
  progressSteps: ProgressStep[];
  toolTraces: ToolTrace[];
  isEmpty: boolean;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <WorkbenchHeader {...props.header} />
      <div className="grid flex-1 grid-cols-[320px_minmax(0,1fr)_320px] gap-4 p-4">
        <aside className="space-y-4">
          <section className="rounded-2xl border bg-white p-4">
            <h2 className="text-base font-semibold">输入面板</h2>
          </section>
          <EvidenceListPanel items={props.evidenceItems} />
        </aside>
        <main className="space-y-4">
          <ResultSummaryCards items={props.summaryMetrics} />
          {props.isEmpty ? <EmptyStatePanel /> : <AnalysisResultPanel sections={props.analysisSections} />}
        </main>
        <aside className="space-y-4">
          <ProgressStatusPanel steps={props.progressSteps} />
          <ToolTracePanel traces={props.toolTraces} />
        </aside>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the minimal leaf component implementations**

Use these exact component shapes:

```tsx
// EvidenceListPanel.tsx
import type { EvidenceItem } from "./types";
export function EvidenceListPanel({ items }: { items: EvidenceItem[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">证据列表</h2>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item.id} className="rounded-xl border px-3 py-2 text-sm">
            {item.name}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

```tsx
// ResultSummaryCards.tsx
import type { SummaryMetric } from "./types";
export function ResultSummaryCards({ items }: { items: SummaryMetric[] }) {
  return (
    <section className="grid grid-cols-3 gap-3">
      {items.map((item) => (
        <div key={item.label} className="rounded-2xl border bg-white p-4">
          <p className="text-sm text-muted-foreground">{item.label}</p>
          <p className="mt-2 text-2xl font-semibold">{item.value}</p>
        </div>
      ))}
    </section>
  );
}
```

```tsx
// AnalysisResultPanel.tsx
import type { AnalysisSection } from "./types";
export function AnalysisResultPanel({ sections }: { sections: AnalysisSection[] }) {
  return (
    <section className="rounded-2xl border bg-white p-5">
      <h2 className="text-base font-semibold">分析结果</h2>
      <div className="mt-4 space-y-5">
        {sections.map((section) => (
          <article key={section.title}>
            <h3 className="text-sm font-semibold text-slate-900">{section.title}</h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{section.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
```

```tsx
// ProgressStatusPanel.tsx
import type { ProgressStep } from "./types";
export function ProgressStatusPanel({ steps }: { steps: ProgressStep[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">进度状态</h2>
      <ul className="mt-3 space-y-2">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center justify-between text-sm">
            <span>{step.label}</span>
            <span>{step.status}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

```tsx
// ToolTracePanel.tsx
import type { ToolTrace } from "./types";
export function ToolTracePanel({ traces }: { traces: ToolTrace[] }) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">调用追踪</h2>
      <ul className="mt-3 space-y-3">
        {traces.map((trace) => (
          <li key={trace.id} className="rounded-xl border px-3 py-2 text-sm">
            <p className="font-medium">{trace.name}</p>
            <p className="mt-1 break-all text-xs text-muted-foreground">{trace.argsSummary}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

```tsx
// EmptyStatePanel.tsx
export function EmptyStatePanel() {
  return (
    <section className="rounded-2xl border bg-white p-10 text-center">
      <h2 className="text-xl font-semibold">开始一次审阅任务</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        上传底稿文件或粘贴文件链接，并补充审阅要求。
      </p>
    </section>
  );
}
```

- [ ] **Step 5: Run the shell test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/components/workbench
git commit -m "feat: add audit workbench shell components"
```

---

### Task 4: Refactor provider and intake state into workbench-friendly data

**Files:**
- Modify: `frontend/providers/Stream.tsx`
- Modify: `frontend/hooks/use-file-upload.tsx`
- Modify: `frontend/components/thread/index.tsx`

- [ ] **Step 1: Write a failing provider-facing test through the view model**

Append this case to `frontend/components/workbench/__tests__/view-model.test.ts`:

```ts
it("marks failure and timeout states for the status rail", () => {
  const failed = buildWorkbenchViewModel({
    status: "failed",
    archiveUrl: "",
    contentBlocks: [],
    messages: [],
    isLoading: false,
    elapsedSeconds: 180,
    error: new Error("timeout"),
  });

  expect(failed.status).toBe("failed");
  expect(failed.progressSteps.some((step) => step.status === "failed")).toBe(true);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/view-model.test.ts`
Expected: FAIL because the current implementation does not reliably distinguish error-driven failure state

- [ ] **Step 3: Extend `Stream.tsx` with explicit task status and elapsed seconds**

Add state:

```ts
const [taskStatus, setTaskStatus] = useState<"idle" | "running" | "completed" | "failed" | "timeout">("idle");
const [elapsedSeconds, setElapsedSeconds] = useState(0);
```

Update lifecycle:

```ts
setTaskStatus("running");
setElapsedSeconds(0);
```

Inside the polling loop:

```ts
setElapsedSeconds(pollCount * 2);

if (pollData.status === "completed") {
  setTaskStatus("completed");
}

if (pollData.status === "error") {
  setTaskStatus("failed");
}
```

Timeout branch:

```ts
setTaskStatus("timeout");
setError("Agent request timed out");
```

Expose from context:

```ts
type StreamContextType = {
  messages: Message[];
  isLoading: boolean;
  error: unknown;
  taskStatus: "idle" | "running" | "completed" | "failed" | "timeout";
  elapsedSeconds: number;
  submit: (input?: unknown) => void;
  stop: () => void;
};
```

- [ ] **Step 4: Make file upload state evidence-friendly**

Update `frontend/hooks/use-file-upload.tsx`:

```ts
interface ContentBlock {
  type: string;
  text: string;
  metadata: { name: string };
  file?: File;
  uploadStatus?: "ready" | "uploading" | "failed";
}
```

When files are added:

```ts
const newBlocks = uniqueFiles.map((file) => ({
  type: "text" as const,
  text: file.name,
  metadata: { name: file.name },
  file,
  uploadStatus: "ready" as const,
}));
```

On upload start and failure, update the matching blocks instead of only showing toasts.

- [ ] **Step 5: Reduce `thread/index.tsx` into a data orchestration component**

Replace page-sized layout concerns with:

```tsx
const stream = useStreamContext();
const model = buildWorkbenchViewModel({
  status: stream.taskStatus,
  archiveUrl,
  contentBlocks,
  messages: stream.messages,
  isLoading: stream.isLoading,
  elapsedSeconds: stream.elapsedSeconds,
  error: stream.error,
});
```

Keep `handleSubmit`, upload logic, and reset logic in this file for now; remove direct shell markup in the next task.

- [ ] **Step 6: Run the view-model test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/view-model.test.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/providers/Stream.tsx frontend/hooks/use-file-upload.tsx frontend/components/thread/index.tsx frontend/components/workbench/view-model.ts frontend/components/workbench/__tests__/view-model.test.ts
git commit -m "feat: normalize workbench state and evidence data"
```

---

### Task 5: Mount the real workbench on the homepage and preserve current submit behavior

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/components/thread/index.tsx`
- Modify: `frontend/app/layout.tsx`

- [ ] **Step 1: Write the failing homepage integration test**

Append this case to `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`:

```tsx
it("shows the empty workbench call to action when no evidence or result exists", () => {
  render(
    <WorkbenchShell
      header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "系统正常" }}
      summaryMetrics={[]}
      analysisSections={[]}
      evidenceItems={[]}
      progressSteps={[]}
      toolTraces={[]}
      isEmpty
    />
  );

  expect(screen.getByText("开始一次审阅任务")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: FAIL if `isEmpty` is not yet respected by the live shell

- [ ] **Step 3: Replace the existing page mount**

Update `frontend/app/page.tsx`:

```tsx
export default function HomePage(): React.ReactNode {
  return (
    <React.Suspense fallback={<div className="flex h-screen items-center justify-center text-muted-foreground">Loading…</div>}>
      <Toaster />
      <StreamProvider>
        <Thread />
      </StreamProvider>
    </React.Suspense>
  );
}
```

The only copy change here is `Loading…`.

- [ ] **Step 4: Update the app metadata**

Update `frontend/app/layout.tsx`:

```ts
export const metadata: Metadata = {
  title: "审计底稿工作台",
  description: "上传审计底稿与证据材料，生成结构化审阅结论、进度状态与调用追踪。",
};
```

- [ ] **Step 5: Return `WorkbenchShell` from `Thread`**

Replace the page-sized JSX in `frontend/components/thread/index.tsx` with:

```tsx
return (
  <WorkbenchShell
    header={{
      title: "审计底稿审阅",
      subtitle: chatStarted ? `会话 ${threadId ?? "当前任务"}` : "开始新的审阅任务",
      statusLabel: stream.taskStatus === "running" ? "处理中" : "系统正常",
    }}
    summaryMetrics={model.summaryMetrics}
    analysisSections={model.analysisSections}
    evidenceItems={model.evidenceItems}
    progressSteps={model.progressSteps}
    toolTraces={model.toolTraces}
    isEmpty={!chatStarted && model.evidenceItems.length === 0 && model.analysisSections.length === 0}
  />
);
```

Pass the live intake controls into `ReviewIntakePanel` via props rather than rebuilding the whole form inside the shell.

- [ ] **Step 6: Run the shell test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/app/page.tsx frontend/app/layout.tsx frontend/components/thread/index.tsx
git commit -m "feat: mount audit workbench on homepage"
```

---

### Task 6: Restore the full intake form inside the left rail with accessible controls

**Files:**
- Modify: `frontend/components/workbench/ReviewIntakePanel.tsx`
- Modify: `frontend/components/thread/index.tsx`
- Review: `frontend/components/ui/input.tsx`
- Review: `frontend/components/ui/textarea.tsx`

- [ ] **Step 1: Write the failing accessibility-focused shell test**

Append this case to `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`:

```tsx
import userEvent from "@testing-library/user-event";

it("renders labeled intake controls with an accessible submit button", async () => {
  const user = userEvent.setup();

  render(
    <ReviewIntakePanel
      archiveUrl=""
      input=""
      showUrlInput
      isLoading={false}
      onArchiveUrlChange={() => {}}
      onInputChange={() => {}}
      onToggleUrlInput={() => {}}
      onSubmit={(event) => event.preventDefault()}
    />
  );

  expect(screen.getByLabelText("文件下载链接")).toBeInTheDocument();
  expect(screen.getByLabelText("审阅要求")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开始分析" })).toBeInTheDocument();
  await user.tab();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: FAIL because `ReviewIntakePanel` does not yet exist or lacks accessible labels

- [ ] **Step 3: Create the real intake panel with labels and visible focus**

Create `frontend/components/workbench/ReviewIntakePanel.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ReviewIntakePanel(props: {
  archiveUrl: string;
  input: string;
  showUrlInput: boolean;
  isLoading: boolean;
  onArchiveUrlChange: (value: string) => void;
  onInputChange: (value: string) => void;
  onToggleUrlInput: () => void;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
}) {
  return (
    <section className="rounded-2xl border bg-white p-4">
      <h2 className="text-base font-semibold">输入面板</h2>
      <form onSubmit={props.onSubmit} className="mt-4 space-y-4">
        {props.showUrlInput ? (
          <div className="space-y-2">
            <label htmlFor="archive-url" className="text-sm font-medium">
              文件下载链接
            </label>
            <Input
              id="archive-url"
              name="archiveUrl"
              type="url"
              autoComplete="off"
              aria-label="文件下载链接"
              placeholder="输入文件下载链接，例如 https://example.com/audit.zip…"
              value={props.archiveUrl}
              onChange={(event) => props.onArchiveUrlChange(event.target.value)}
            />
          </div>
        ) : null}
        <div className="space-y-2">
          <label htmlFor="review-input" className="text-sm font-medium">
            审阅要求
          </label>
          <textarea
            id="review-input"
            name="reviewInput"
            aria-label="审阅要求"
            className="min-h-28 w-full rounded-xl border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="描述想要分析的底稿范围与重点，例如：请检查证据充分性与截止测试异常项…"
            value={props.input}
            onChange={(event) => props.onInputChange(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" onClick={props.onToggleUrlInput}>
            {props.showUrlInput ? "收起链接" : "粘贴链接"}
          </Button>
          <Button type="submit" variant="brand" disabled={props.isLoading}>
            {props.isLoading ? "分析中…" : "开始分析"}
          </Button>
        </div>
      </form>
    </section>
  );
}
```

- [ ] **Step 4: Wire the intake props from `thread/index.tsx`**

Use:

```tsx
<ReviewIntakePanel
  archiveUrl={archiveUrl}
  input={input}
  showUrlInput={showUrlInput}
  isLoading={isLoading}
  onArchiveUrlChange={setArchiveUrl}
  onInputChange={setInput}
  onToggleUrlInput={() => setShowUrlInput((value) => !value)}
  onSubmit={handleSubmit}
/>
```

- [ ] **Step 5: Remove the old raw textarea/button layout and keep only data logic in `Thread`**

Delete:
- raw `<textarea>` with `outline-none focus:outline-none`
- raw link toggle `<button>`
- footer-sized chat composer container

Retain:
- submit keyboard behavior
- upload invocation
- reset logic

- [ ] **Step 6: Run the shell test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/components/workbench/ReviewIntakePanel.tsx frontend/components/thread/index.tsx frontend/components/workbench/__tests__/WorkbenchShell.test.tsx
git commit -m "feat: add accessible intake panel for workbench"
```

---

### Task 7: Present running, failed, and completed states in the status rail and result pane

**Files:**
- Modify: `frontend/components/workbench/AnalysisResultPanel.tsx`
- Modify: `frontend/components/workbench/ProgressStatusPanel.tsx`
- Modify: `frontend/components/workbench/ToolTracePanel.tsx`
- Modify: `frontend/components/workbench/WorkbenchShell.tsx`
- Modify: `frontend/components/workbench/view-model.ts`

- [ ] **Step 1: Write the failing status-state test**

Append this case to `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`:

```tsx
it("shows failed progress state and recovery copy", () => {
  render(
    <WorkbenchShell
      header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "处理失败" }}
      summaryMetrics={[]}
      analysisSections={[]}
      evidenceItems={[]}
      progressSteps={[{ label: "分析底稿", status: "failed" }]}
      toolTraces={[]}
      isEmpty={false}
      errorMessage="分析失败，请检查输入材料后重试。"
    />
  );

  expect(screen.getByText("分析失败，请检查输入材料后重试。")).toBeInTheDocument();
  expect(screen.getByText("failed")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: FAIL because `errorMessage` is not rendered yet

- [ ] **Step 3: Extend the shell and result panel to render status-aware copy**

Update `WorkbenchShell.tsx` props:

```tsx
errorMessage?: string;
runningMessage?: string;
```

Update `AnalysisResultPanel.tsx`:

```tsx
export function AnalysisResultPanel({
  sections,
  runningMessage,
  errorMessage,
}: {
  sections: AnalysisSection[];
  runningMessage?: string;
  errorMessage?: string;
}) {
  return (
    <section className="rounded-2xl border bg-white p-5">
      <h2 className="text-base font-semibold">分析结果</h2>
      {errorMessage ? (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {errorMessage}
        </div>
      ) : null}
      {runningMessage ? (
        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">
          {runningMessage}
        </div>
      ) : null}
      <div className="mt-4 space-y-5">
        {sections.map((section) => (
          <article key={section.title}>
            <h3 className="text-sm font-semibold text-slate-900">{section.title}</h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{section.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Feed real status copy from the view model**

In `view-model.ts`, add:

```ts
const errorMessage =
  input.error instanceof Error
    ? "分析失败，请检查输入材料后重试。"
    : typeof input.error === "string"
      ? "分析失败，请检查输入材料后重试。"
      : undefined;

const runningMessage = input.isLoading ? `正在分析底稿… 已运行 ${input.elapsedSeconds}s` : undefined;
```

Return both fields from the model and pass them through `Thread` into `WorkbenchShell`.

- [ ] **Step 5: Run the shell test to verify it passes**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend test suite**

Run: `npm run test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/components/workbench frontend/components/thread/index.tsx
git commit -m "feat: add workbench status and recovery states"
```

---

### Task 8: Finish guideline fixes, lint, and production verification

**Files:**
- Modify: `frontend/components/thread/index.tsx`
- Modify: `frontend/providers/Stream.tsx`
- Review: `frontend/components/ui/button.tsx`
- Review: `frontend/components/ui/input.tsx`
- Review: `frontend/components/ui/textarea.tsx`

- [ ] **Step 1: Write the final failing copy and focus assertions**

Append this case to `frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`:

```tsx
it("uses ellipsis glyphs in loading copy", () => {
  render(
    <WorkbenchShell
      header={{ title: "审计底稿审阅", subtitle: "会话 A", statusLabel: "处理中" }}
      summaryMetrics={[]}
      analysisSections={[]}
      evidenceItems={[]}
      progressSteps={[]}
      toolTraces={[]}
      isEmpty={false}
      runningMessage="正在分析底稿… 已运行 8s"
    />
  );

  expect(screen.getByText("正在分析底稿… 已运行 8s")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails if raw `...` remains**

Run: `npm run test -- frontend/components/workbench/__tests__/WorkbenchShell.test.tsx`
Expected: FAIL if running copy still uses `...`

- [ ] **Step 3: Apply the remaining guideline fixes**

Required code changes:

```ts
// frontend/providers/Stream.tsx
setMessages((prev) =>
  prev.map((m) => (m.id === aiId ? { ...m, content: "正在分析底稿…" } : m)),
);

setMessages((prev) =>
  prev.map((m) =>
    m.id === aiId ? { ...m, content: `正在分析底稿… (${pollCount * 2}s)` } : m,
  ),
);
```

```tsx
// frontend/app/page.tsx
fallback={<div className="flex h-screen items-center justify-center text-muted-foreground">Loading…</div>}
```

```tsx
// Remove any remaining raw icon/action buttons in thread/index.tsx
// Replace with shared <Button> or <TooltipIconButton> only
```

- [ ] **Step 4: Run lint**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 5: Run production build**

Run: `npm run build`
Expected: PASS with no TypeScript or Next build errors

- [ ] **Step 6: Manual smoke test**

Run:

```bash
npm run dev
```

Verify manually:
- empty state shows `开始一次审阅任务`
- upload or link can be added
- submit starts `处理中`
- status rail updates while polling
- completed response renders in structured result area
- failure keeps evidence visible and shows retry-oriented copy

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "fix: finish workbench guideline and verification updates"
```

---

## Plan Self-Review

- Spec coverage:
  - Workbench shell with left/middle/right information architecture: Tasks 3, 5, 6
  - Structured state model for idle/uploading/running/completed/failed/timeout: Tasks 2, 4, 7
  - Evidence-first upload presentation: Tasks 4, 6
  - Summary/result/progress/trace regions: Tasks 2, 3, 7
  - Guideline fixes for labels, focus, metadata, and ellipsis copy: Tasks 5, 6, 8
  - Verification of desktop-first workbench behavior: Task 8
- Placeholder scan:
  - No `TODO`, `TBD`, or “handle appropriately” placeholders remain.
  - Each code-changing step includes exact file paths, code, and command expectations.
- Type consistency:
  - Workbench state names are consistent across `types.ts`, `view-model.ts`, `Stream.tsx`, and `WorkbenchShell.tsx`.
  - Evidence, summary, sections, progress, and traces use the same field names throughout the plan.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-audit-workpaper-workbench-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
