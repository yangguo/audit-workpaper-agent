"use client";

import { v4 as uuidv4 } from "uuid";
import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { useState, FormEvent } from "react";
import { Button } from "../ui/button";
import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { HumanMessage } from "./messages/human";
import { TooltipIconButton } from "./tooltip-icon-button";
import {
  ArrowDown,
  LoaderCircle,
  SquarePen,
  Plus,
  FileArchive,
  Link,
} from "lucide-react";
import { useQueryState, parseAsBoolean } from "nuqs";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { toast } from "sonner";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { useFileUpload } from "@/hooks/use-file-upload";
import { ContentBlocksPreview } from "./ContentBlocksPreview";
import { Input } from "../ui/input";

function StickyToBottomContent(props: {
  content: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const context = useStickToBottomContext();
  return (
    <div
      ref={context.scrollRef}
      style={{ width: "100%", height: "100%" }}
      className={props.className}
    >
      <div
        ref={context.contentRef}
        className={props.contentClassName}
      >
        {props.content}
      </div>
      {props.footer}
    </div>
  );
}

function ScrollToBottom(props: { className?: string }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={props.className}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>滚动到底部</span>
    </Button>
  );
}

export function Thread() {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [hideToolCalls, setHideToolCalls] = useQueryState(
    "hideToolCalls",
    parseAsBoolean.withDefault(false),
  );
  const [input, setInput] = useState("");
  const [archiveUrl, setArchiveUrl] = useState("");
  const [showUrlInput, setShowUrlInput] = useState(false);

  const {
    contentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock,
    resetBlocks,
    dragOver,
    handlePaste,
    uploadFiles,
  } = useFileUpload();

  const [firstTokenReceived, setFirstTokenReceived] = useState(false);

  const stream = useStreamContext();
  const messages = stream.messages;
  const isLoading = stream.isLoading;

  const lastError = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!stream.error) {
      lastError.current = undefined;
      return;
    }
    try {
      const message = (stream.error as any).message;
      if (!message || lastError.current === message) return;
      lastError.current = message;
      toast.error("发生错误，请重试。", {
        description: (
          <p>
            <strong>Error:</strong> <code>{message}</code>
          </p>
        ),
        richColors: true,
        closeButton: true,
      });
    } catch {
      // no-op
    }
  }, [stream.error]);

  const prevMessageLength = useRef(0);
  useEffect(() => {
    if (
      messages.length !== prevMessageLength.current &&
      messages?.length &&
      messages[messages.length - 1].type === "ai"
    ) {
      setFirstTokenReceived(true);
    }
    prevMessageLength.current = messages.length;
  }, [messages]);

  const buildMessageText = (uploadedPaths: string[] = []): string => {
    const parts: string[] = [];

    if (archiveUrl.trim()) {
      parts.push(`请分析这个文件链接: ${archiveUrl.trim()}`);
    }

    if (input.trim()) {
      parts.push(input.trim());
    }

    let text = parts.join("\n");
    if (uploadedPaths.length > 0) {
      const suffix = ["已上传文件路径：", ...uploadedPaths.map((p) => `- ${p}`)].join("\n");
      text = text ? `${text}\n${suffix}` : suffix;
    }
    return text;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    // Upload files before building message
    let uploadedPaths: string[] = [];
    const filesToUpload = contentBlocks
      .filter((b) => b.file)
      .map((b) => b.file!);

    if (filesToUpload.length > 0) {
      try {
        uploadedPaths = await uploadFiles(filesToUpload);
      } catch {
        toast.error("文件上传失败，请重试");
        return;
      }
    }

    const text = buildMessageText(uploadedPaths);
    if ((!text.trim() && contentBlocks.length === 0) || isLoading) return;
    setFirstTokenReceived(false);

    const msgContent: Array<{ type: string; text?: string; metadata?: { name: string } }> = [];

    if (text.trim()) {
      msgContent.push({ type: "text", text: text.trim() });
    }

    for (const block of contentBlocks) {
      msgContent.push({
        type: "text",
        text: "",
        metadata: { name: block.metadata.name },
      });
    }

    const newHumanMessage = {
      id: uuidv4(),
      type: "human" as const,
      content: msgContent,
    };

    stream.submit({
      messages: [...stream.messages, newHumanMessage],
    });

    setInput("");
    setArchiveUrl("");
    setShowUrlInput(false);
    resetBlocks();
  };

  const chatStarted = !!threadId || !!messages.length;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-white">
      <div
        className={cn(
          "grid w-full",
        )}
      >
        <motion.div
          className={cn(
            "relative flex min-w-0 flex-1 flex-col overflow-hidden",
            !chatStarted && "grid-rows-[1fr]",
          )}
          layout
        >
          {/* Header */}
          {chatStarted && (
            <div className="relative z-10 flex items-center justify-between gap-3 border-b p-2">
              <div className="flex items-center gap-2">
                <FileArchive className="size-6 text-blue-600" />
                <span className="text-xl font-semibold tracking-tight">
                  审计底稿审阅
                </span>
              </div>
              <div className="flex items-center gap-4">
                <TooltipIconButton
                  size="lg"
                  className="p-4"
                  tooltip="新建会话"
                  variant="ghost"
                  onClick={() => {
                    setThreadId(null);
                    window.location.reload();
                  }}
                >
                  <SquarePen className="size-5" />
                </TooltipIconButton>
              </div>
              <div className="from-background to-background/0 absolute inset-x-0 top-full h-5 bg-gradient-to-b" />
            </div>
          )}

          <StickToBottom className="relative flex-1 overflow-hidden">
            <StickyToBottomContent
              className={cn(
                "absolute inset-0 overflow-y-scroll px-4 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent",
                !chatStarted && "mt-[20vh] flex flex-col items-stretch",
                chatStarted && "grid grid-rows-[1fr_auto]",
              )}
              contentClassName="pt-8 pb-16 max-w-3xl mx-auto flex flex-col gap-4 w-full"
              content={
                <>
                  {messages
                    .filter((m) => m.type !== "tool")
                    .map((message, index) =>
                      message.type === "human" ? (
                        <HumanMessage
                          key={message.id || `${message.type}-${index}`}
                          message={message}
                          isLoading={isLoading}
                        />
                      ) : (
                        <AssistantMessage
                          key={message.id || `${message.type}-${index}`}
                          message={message}
                          isLoading={isLoading}
                        />
                      ),
                    )}
                  {isLoading && !firstTokenReceived && (
                    <AssistantMessageLoading />
                  )}
                </>
              }
              footer={
                <div className="sticky bottom-0 flex flex-col items-center gap-8 bg-white">
                  {!chatStarted && (
                    <div className="flex flex-col items-center gap-4">
                      <FileArchive className="size-12 text-blue-600" />
                      <h1 className="text-2xl font-semibold tracking-tight">
                        审计底稿审阅
                      </h1>
                      <p className="text-muted-foreground text-sm">
                        上传审计底稿文件或提供下载链接，自动分析内容并辅助审阅
                      </p>
                    </div>
                  )}

                  <ScrollToBottom className="animate-in fade-in-0 zoom-in-95 absolute bottom-full left-1/2 mb-4 -translate-x-1/2" />

                  <div
                    ref={dropRef}
                    className={cn(
                      "bg-muted relative z-10 mx-auto mb-8 w-full max-w-3xl rounded-2xl shadow-xs transition-all",
                      dragOver
                        ? "border-primary border-2 border-dotted"
                        : "border border-solid",
                    )}
                  >
                    <form
                      onSubmit={handleSubmit}
                      className="mx-auto grid max-w-3xl grid-rows-[1fr_auto] gap-2"
                    >
                      <ContentBlocksPreview
                        blocks={contentBlocks}
                        onRemove={removeBlock}
                      />

                      {/* URL input section */}
                      {showUrlInput && (
                        <div className="flex items-center gap-2 px-3.5 pt-2">
                          <Link className="size-4 text-muted-foreground shrink-0" />
                          <Input
                            type="url"
                            value={archiveUrl}
                            onChange={(e) => setArchiveUrl(e.target.value)}
                            placeholder="输入文件下载链接 (https://...)"
                            className="border-0 bg-transparent h-8 text-sm shadow-none focus-visible:ring-0"
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                const form = (e.target as HTMLElement).closest("form");
                                form?.requestSubmit();
                              }
                            }}
                          />
                        </div>
                      )}

                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onPaste={handlePaste}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            !e.shiftKey &&
                            !e.metaKey &&
                            !e.nativeEvent.isComposing
                          ) {
                            e.preventDefault();
                            const el = e.target as HTMLElement | undefined;
                            const form = el?.closest("form");
                            form?.requestSubmit();
                          }
                        }}
                        placeholder="描述您想要分析的底稿文件，或粘贴文件下载链接。例如：请分析这份底稿并检查证据充分性"
                        className="field-sizing-content resize-none border-none bg-transparent p-3.5 pb-0 shadow-none ring-0 outline-none focus:ring-0 focus:outline-none"
                      />

                      <div className="flex items-center gap-6 p-2 pt-4">
                        <div>
                          <div className="flex items-center space-x-2">
                            <Switch
                              id="render-tool-calls"
                              checked={hideToolCalls ?? false}
                              onCheckedChange={setHideToolCalls}
                            />
                            <Label
                              htmlFor="render-tool-calls"
                              className="text-sm text-gray-600"
                            >
                              隐藏工具调用
                            </Label>
                          </div>
                        </div>
                        <Label
                          htmlFor="file-input"
                          className="flex cursor-pointer items-center gap-2"
                        >
                          <Plus className="size-5 text-gray-600" />
                          <span className="text-sm text-gray-600">
                            上传文件
                          </span>
                        </Label>
                        <input
                          id="file-input"
                          type="file"
                          onChange={handleFileUpload}
                          multiple
                          accept=".zip,.tar,.tar.gz,.tgz,.tar.bz2,.7z,.rar,.xlsx,.xls,.csv,.pdf,.docx,.doc,.pptx,.ppt"
                          className="hidden"
                        />
                        <button
                          type="button"
                          onClick={() => setShowUrlInput(!showUrlInput)}
                          className="flex cursor-pointer items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
                        >
                          <Link className="size-5" />
                          <span>粘贴链接</span>
                        </button>
                        {stream.isLoading ? (
                          <Button
                            key="stop"
                            onClick={() => stream.stop()}
                            variant="outline"
                            className="ml-auto"
                          >
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            取消
                          </Button>
                        ) : (
                          <Button
                            type="submit"
                            variant="brand"
                            className="ml-auto shadow-md transition-all"
                            disabled={
                              isLoading ||
                              (!input.trim() && !archiveUrl.trim() && contentBlocks.length === 0)
                            }
                          >
                            发送
                          </Button>
                        )}
                      </div>
                    </form>
                  </div>
                </div>
              }
            />
          </StickToBottom>
        </motion.div>
      </div>
    </div>
  );
}
