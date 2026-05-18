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

      const res = await fetch(`${backendUrl}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          messages: [{ role: "user", content: text }],
          session_id: sid,
          stream: true,
        }),
        signal: abort.signal,
      });

      if (!res.ok || !res.body) {
        const data = await res.text();
        setError(data || "Backend request failed");
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let lastText = "";

      while (!abort.signal.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        while (true) {
          const idx = buffer.indexOf("\n\n");
          if (idx === -1) break;
          const rawEvent = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);

          const dataLines = rawEvent
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trim());
          if (dataLines.length === 0) continue;

          const dataText = dataLines.join("\n");
          if (dataText === "[DONE]") continue;

          try {
            const chunk = JSON.parse(dataText);
            const delta = chunk?.choices?.[0]?.delta?.content;
            if (typeof delta === "string") {
              lastText = lastText + delta;
              setMessages((prev) =>
                prev.map((m) => (m.id === aiId ? { ...m, content: lastText } : m)),
              );
            }
          } catch {
            // skip unparseable chunks
          }
        }
      }

      if (!lastText.trim()) {
        setMessages((prev) => prev.filter((m) => m.id !== aiId));
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
