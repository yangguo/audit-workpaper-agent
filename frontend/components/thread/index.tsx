"use client";

import { v4 as uuidv4 } from "uuid";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { useState, FormEvent } from "react";
import { Button } from "../ui/button";
import { SquarePen } from "lucide-react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import { useFileUpload } from "@/hooks/use-file-upload";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";
import { ReviewIntakePanel } from "@/components/workbench/ReviewIntakePanel";
import { buildWorkbenchViewModel } from "@/components/workbench/view-model";

export function Thread() {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [input, setInput] = useState("");
  const [archiveUrl, setArchiveUrl] = useState("");
  const [showUrlInput, setShowUrlInput] = useState(false);

  const {
    contentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock: _removeBlock,
    resetBlocks,
    dragOver,
    handlePaste,
    uploadFiles,
    attachmentDirectoryFiles,
    handleAttachmentDirectoryUpload,
    uploadAttachmentDirectory,
  } = useFileUpload();

  void _removeBlock;

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
      const message = (stream.error as { message?: string }).message;
      if (!message || lastError.current === message) return;
      lastError.current = message;
      toast.error("分析失败，请检查输入材料后重试。", {
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

  const buildMessageText = (
    uploadedPaths: string[] = [],
    attachmentsDirPath = "",
  ): string => {
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
    if (attachmentsDirPath) {
      const suffix = `附件目录路径：\n- ${attachmentsDirPath}`;
      text = text ? `${text}\n${suffix}` : suffix;
    }
    return text;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    // Upload files before building message
    let uploadedPaths: string[] = [];
    let attachmentsDirPath = "";
    const filesToUpload = contentBlocks
      .filter((b) => b.file)
      .map((b) => b.file!);

    if (filesToUpload.length > 0) {
      try {
        uploadedPaths = await uploadFiles(filesToUpload);
      } catch (error) {
        console.error("File upload failed:", error);
        const message = error instanceof Error ? error.message : String(error);
        const isConnectionError =
          message.includes("Failed to fetch") || message.includes("NetworkError");
        toast.error(
          isConnectionError ? "无法连接后端服务" : "文件上传失败，请重试",
          {
            description: isConnectionError
              ? "请确认后端已启动：python src/main.py -m http -p 5000"
              : message,
          },
        );
        return;
      }
    }

    if (attachmentDirectoryFiles.length > 0) {
      try {
        attachmentsDirPath = await uploadAttachmentDirectory(attachmentDirectoryFiles);
      } catch (error) {
        console.error("Attachment directory upload failed:", error);
        const message = error instanceof Error ? error.message : String(error);
        const isConnectionError =
          message.includes("Failed to fetch") || message.includes("NetworkError");
        toast.error(
          isConnectionError ? "无法连接后端服务" : "附件目录上传失败，请重试",
          {
            description: isConnectionError
              ? "请确认后端已启动：python src/main.py -m http -p 5000"
              : message,
          },
        );
        return;
      }
    }

    const text = buildMessageText(uploadedPaths, attachmentsDirPath);
    if ((!text.trim() && contentBlocks.length === 0) || isLoading) return;

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

  const chatStarted = !!messages.length;

  const model = buildWorkbenchViewModel({
    status: stream.taskStatus,
    archiveUrl,
    contentBlocks,
    messages,
    isLoading,
    elapsedSeconds: stream.elapsedSeconds,
    error: stream.error,
    findings: stream.findings,
    reviewStatus: stream.reviewStatus,
    reviewElapsedSeconds: stream.reviewElapsedSeconds,
    understoodRequirement: stream.understoodRequirement,
  });

  const statusLabel =
    stream.taskStatus === "running"
      ? "处理中"
      : stream.taskStatus === "failed" || stream.taskStatus === "timeout"
        ? "处理失败"
        : stream.taskStatus === "completed"
          ? "已完成"
          : "系统正常";

  const isEmpty =
    model.evidenceItems.length === 0 && model.analysisSections.length === 0;

  return (
    <div
      ref={dropRef}
      className={cn(
        "flex h-screen w-full flex-col overflow-hidden transition-colors",
        dragOver && "ring-2 ring-primary ring-inset",
      )}
    >
      <WorkbenchShell
        header={{
          title: "审计底稿审阅",
          subtitle: chatStarted
            ? `会话 ${threadId ?? "当前任务"}`
            : "准备开始新的审阅任务",
          statusLabel,
          action: (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setThreadId(null);
                window.location.reload();
              }}
            >
              <SquarePen className="size-4" />
              新建审阅
            </Button>
          ),
        }}
        summaryMetrics={model.summaryMetrics}
        analysisSections={model.analysisSections}
        evidenceItems={model.evidenceItems}
        progressSteps={model.progressSteps}
        toolTraces={model.toolTraces}
        understoodRequirement={model.understoodRequirement}
        isEmpty={isEmpty}
        errorMessage={model.errorMessage}
        runningMessage={model.runningMessage}
        intake={
          <ReviewIntakePanel
            archiveUrl={archiveUrl}
            input={input}
            showUrlInput={showUrlInput}
            isLoading={isLoading}
            onArchiveUrlChange={setArchiveUrl}
            onInputChange={setInput}
            onToggleUrlInput={() => setShowUrlInput((value) => !value)}
            onSubmit={handleSubmit}
            onFileUpload={handleFileUpload}
            onAttachmentDirectoryUpload={handleAttachmentDirectoryUpload}
            attachmentDirectoryFileCount={attachmentDirectoryFiles.length}
            onPaste={handlePaste}
          />
        }
      />
    </div>
  );
}
