"use client";

import React, { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { useQueryState } from "nuqs";
import { v4 as uuidv4 } from "uuid";

type Message = {
  id: string;
  type: "human" | "ai" | "tool";
  content: string;
  tool_calls?: Array<{ name: string; id: string; args: Record<string, unknown> }>;
};

type StreamContextType = {
  messages: Message[];
  isLoading: boolean;
  error: unknown;
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
  const abortRef = useRef<AbortController | null>(null);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
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
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        return;
      }

      const { task_id } = await startRes.json();
      if (!task_id) {
        setError("No task ID returned");
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        return;
      }

      setMessages((prev) =>
        prev.map((m) => (m.id === aiId ? { ...m, content: "正在分析底稿..." } : m)),
      );

      // Poll for result
      const pollInterval = 2000;
      const maxPolls = 90; // 3 minutes max
      let pollCount = 0;
      let aiText = "";

      while (pollCount < maxPolls && !abort.signal.aborted) {
        await new Promise((r) => setTimeout(r, pollInterval));
        pollCount += 1;

        const pollRes = await fetch(
          `${backendUrl}/v1/chat/completions/result/${task_id}`,
          { signal: abort.signal },
        );

        if (!pollRes.ok) continue;

        const pollData = await pollRes.json();

        if (pollData.status === "completed") {
          aiText = pollData?.choices?.[0]?.message?.content || "";
          break;
        }
        if (pollData.status === "error") {
          setError(pollData.error || "Agent error");
          setMessages((prev) => prev.filter((m) => m.id !== aiId));
          return;
        }
        // Update placeholder with progress indicator
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, content: `正在分析底稿... (${pollCount * 2}s)` } : m,
          ),
        );
      }

      if (aiText.trim()) {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiId ? { ...m, content: aiText } : m)),
        );
      } else {
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        if (!abort.signal.aborted) setError("Agent request timed out");
      }
    } catch (e) {
      if ((e as any)?.name !== "AbortError") setError(e);
    } finally {
      setIsLoading(false);
    }
  };

  const value: StreamContextType = {
    messages,
    isLoading,
    error,
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
