"use client";

import React, { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { useQueryState } from "nuqs";
import { v4 as uuidv4 } from "uuid";
import type { FindingsPayload, ReviewProgress, UnderstoodRequirement } from "@/components/workbench/types";

type Message = {
  id: string;
  type: "human" | "ai" | "tool";
  content: string;
  tool_calls?: Array<{ name: string; id: string; args: Record<string, unknown> }>;
};

type TaskStatus = "idle" | "running" | "completed" | "failed" | "timeout";

type StreamContextType = {
  messages: Message[];
  isLoading: boolean;
  error: unknown;
  taskStatus: TaskStatus;
  elapsedSeconds: number;
  reviewStatus: "idle" | "running" | "completed" | "error";
  reviewElapsedSeconds: number;
  reviewProgress: ReviewProgress | null;
  findings: FindingsPayload | null;
  understoodRequirement: UnderstoodRequirement | null;
  submit: (input?: unknown) => void;
  stop: () => void;
};

const StreamContext = createContext<StreamContextType | undefined>(undefined);

function contentToText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";

  return content
    .map((part: any) => {
      if (!part || typeof part !== "object") return "";
      if (part.type === "text" && typeof part.text === "string") return part.text;
      if (typeof part.text === "string") return part.text;
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

type ReviewPollOpts = {
  backendUrl: string;
  reviewId: string;
  signal: () => AbortSignal | undefined;
  onTick: (elapsedSeconds: number) => void;
  onProgress?: (progress: ReviewProgress) => void;
  onCompleted: (payload: FindingsPayload) => void;
  onError: (message: string) => void;
};

async function pollReviewStatus(opts: ReviewPollOpts): Promise<void> {
  const intervalMs = 5000;
  const maxPolls = 720; // 60 min ceiling
  for (let i = 1; i <= maxPolls; i++) {
    const sig = opts.signal();
    if (sig?.aborted) return;
    await new Promise((r) => setTimeout(r, intervalMs));
    opts.onTick(i * (intervalMs / 1000));
    try {
      const res = await fetch(`${opts.backendUrl}/review/${opts.reviewId}/status`, {
        signal: opts.signal(),
      });
      if (!res.ok) continue;
      const data = await res.json();
      if (data.status === "completed") {
        const findingsRes = await fetch(`${opts.backendUrl}/findings/${opts.reviewId}`, {
          signal: opts.signal(),
        });
        if (findingsRes.ok) {
          const payload = (await findingsRes.json()) as FindingsPayload;
          if (payload && payload.findings) opts.onCompleted(payload);
        }
        return;
      }
      if (data.status === "error") {
        opts.onError(data.error || "审阅失败");
        return;
      }
      if (data.status === "cancelled") {
        opts.onError("审阅已取消");
        return;
      }
      if (data.status === "running" && data.progress && opts.onProgress) {
        try {
          opts.onProgress(data.progress as ReviewProgress);
        } catch {
          // malformed progress payload — ignore, keep polling
        }
      }
      // status === "running" -> keep polling
    } catch (e) {
      if ((e as any)?.name === "AbortError") return;
      // transient fetch error -> keep polling
    }
  }
  opts.onError("审阅超时（超过 60 分钟）");
}

function buildUserMessageText(messages: Message[]): string {
  const lastHuman = [...messages].reverse().find((m) => m.type === "human");
  if (!lastHuman) return "";
  return contentToText((lastHuman as any).content);
}

export const StreamProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [sessionId, setSessionId] = useState<string>(() => threadId || "");

  useEffect(() => {
    if (threadId) {
      setSessionId(threadId);
      return;
    }
    const id = uuidv4();
    setThreadId(id);
    setSessionId(id);
  }, [threadId, setThreadId]);

  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [findings, setFindings] = useState<FindingsPayload | null>(null);
  const [reviewStatus, setReviewStatus] = useState<"idle" | "running" | "completed" | "error">("idle");
  const [reviewElapsedSeconds, setReviewElapsedSeconds] = useState(0);
  const [reviewProgress, setReviewProgress] = useState<ReviewProgress | null>(null);
  const [understoodRequirement, setUnderstoodRequirement] = useState<UnderstoodRequirement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const reviewAbortRef = useRef<AbortController | null>(null);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    reviewAbortRef.current?.abort();
    reviewAbortRef.current = null;
    setIsLoading(false);
    setReviewStatus((prev) => (prev === "running" ? "idle" : prev));
    setTaskStatus((prev) => (prev === "running" ? "idle" : prev));
  };

  const submit: StreamContextType["submit"] = async (input) => {
    const maybeMessages = (input as any)?.messages;
    const nextMessages: Message[] = Array.isArray(maybeMessages) ? maybeMessages : messages;
    const text = buildUserMessageText(nextMessages);
    if (!text.trim()) return;

    stop();
    const abort = new AbortController();
    abortRef.current = abort;

    setError(null);
    setIsLoading(true);
    setTaskStatus("running");
    setElapsedSeconds(0);
    setFindings(null);
    setReviewStatus("idle");
    setReviewElapsedSeconds(0);
    setReviewProgress(null);
    setUnderstoodRequirement(null);
    reviewAbortRef.current?.abort();
    reviewAbortRef.current = null;
    setMessages(nextMessages);

    try {
      const sid = sessionId || threadId || uuidv4();
      if (!threadId) setThreadId(sid);
      if (!sessionId) setSessionId(sid);
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:5000";
      const aiId = uuidv4();
      const placeholderAi: Message = { id: aiId, type: "ai", content: "" };
      setMessages((prev) => [...prev, placeholderAi]);

      // Start agent task
      const startRes = await fetch(`${backendUrl}/v1/chat/completions`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: text }],
          session_id: sid,
          stream: false,
        }),
        signal: abort.signal,
      });

      if (!startRes.ok) {
        const data = await startRes.text();
        setError(data || "Backend request failed");
        setTaskStatus("failed");
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        return;
      }

      const { task_id } = await startRes.json();
      if (!task_id) {
        setError("No task ID returned");
        setTaskStatus("failed");
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        return;
      }

      setMessages((prev) =>
        prev.map((m) => (m.id === aiId ? { ...m, content: "正在分析底稿…" } : m)),
      );

      // Poll for result
      const pollInterval = 2000;
      const maxPolls = 90; // 3 minutes max
      let pollCount = 0;
      let aiText = "";
      let reviewId: string | undefined;
      let reviewSummary: { review_id?: string; status?: string } | undefined;

      while (pollCount < maxPolls && !abort.signal.aborted) {
        await new Promise((r) => setTimeout(r, pollInterval));
        pollCount += 1;
        setElapsedSeconds(pollCount * 2);

        const pollRes = await fetch(
          `${backendUrl}/v1/chat/completions/result/${task_id}`,
          { signal: abort.signal },
        );

        if (!pollRes.ok) continue;

        const pollData = await pollRes.json();

        // Surface the understood review requirement as soon as the agent has
        // called review_workpaper — even while the task is still processing.
        if (pollData?.review_summary) {
          setUnderstoodRequirement(pollData.review_summary as UnderstoodRequirement);
        }

        if (pollData.status === "completed") {
          aiText = pollData?.choices?.[0]?.message?.content || "";
          reviewId = pollData?.review_id;
          reviewSummary = pollData?.review_summary;
          break;
        }
        if (pollData.status === "error") {
          setError(pollData.error || "Agent error");
          setTaskStatus("failed");
          setMessages((prev) => prev.filter((m) => m.id !== aiId));
          return;
        }
        // Update placeholder with progress indicator
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, content: `正在分析底稿… (${pollCount * 2}s)` } : m,
          ),
        );
      }

      if (aiText.trim()) {
        setTaskStatus("completed");
        setMessages((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, content: aiText } : m)),
        );
        // If review_workpaper started a background review, poll its status
        if (reviewId && reviewSummary?.status === "running") {
          setReviewStatus("running");
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
        } else if (reviewId) {
          // review already completed (or no background review) — fetch findings directly
          fetch(`${backendUrl}/findings/${reviewId}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data: FindingsPayload | null) => {
              if (data && data.findings) {
                setFindings(data);
                setReviewStatus("completed");
              }
            })
            .catch(() => {
              // structured findings are optional; Markdown narrative still shows
            });
        }
      } else {
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        if (!abort.signal.aborted) {
          setError("Agent request timed out");
          setTaskStatus("timeout");
        }
      }
    } catch (e) {
      if ((e as any)?.name !== "AbortError") {
        setError(e);
        setTaskStatus("failed");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const value: StreamContextType = {
    messages,
    isLoading,
    error,
    taskStatus,
    elapsedSeconds,
    reviewStatus,
    reviewElapsedSeconds,
    reviewProgress,
    findings,
    understoodRequirement,
    submit,
    stop,
  };

  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
};

export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (!context) throw new Error("useStreamContext must be used within a StreamProvider");
  return context;
};

export default StreamContext;
