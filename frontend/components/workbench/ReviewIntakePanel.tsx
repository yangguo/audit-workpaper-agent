"use client";

import type { ChangeEvent, ClipboardEvent, FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Plus } from "lucide-react";

const ACCEPTED_FILE_TYPES =
  ".zip,.tar,.tar.gz,.tgz,.tar.bz2,.7z,.rar,.xlsx,.xls,.csv,.pdf,.docx,.doc,.pptx,.ppt";

export function ReviewIntakePanel(props: {
  archiveUrl: string;
  input: string;
  showUrlInput: boolean;
  isLoading: boolean;
  onArchiveUrlChange: (value: string) => void;
  onInputChange: (value: string) => void;
  onToggleUrlInput: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onFileUpload: (event: ChangeEvent<HTMLInputElement>) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
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
            className="min-h-28 w-full resize-none rounded-xl border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="描述想要分析的底稿范围与重点，例如：请检查证据充分性与截止测试异常项…"
            value={props.input}
            onChange={(event) => props.onInputChange(event.target.value)}
            onPaste={props.onPaste}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.metaKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                const el = event.target as HTMLElement | undefined;
                el?.closest("form")?.requestSubmit();
              }
            }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Label
            htmlFor="workbench-file-input"
            className="flex cursor-pointer items-center gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs hover:bg-accent"
          >
            <Plus className="size-4" />
            <span>上传文件</span>
          </Label>
          <input
            id="workbench-file-input"
            type="file"
            onChange={props.onFileUpload}
            multiple
            accept={ACCEPTED_FILE_TYPES}
            className="hidden"
          />
          <Button
            type="button"
            variant="outline"
            onClick={props.onToggleUrlInput}
          >
            {props.showUrlInput ? "收起链接" : "粘贴链接"}
          </Button>
          <Button
            type="submit"
            variant="brand"
            className="ml-auto"
            disabled={props.isLoading}
          >
            {props.isLoading ? "分析中…" : "开始分析"}
          </Button>
        </div>
      </form>
    </section>
  );
}
