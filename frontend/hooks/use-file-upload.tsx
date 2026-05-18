"use client";

import { useState, useRef, useEffect, ChangeEvent } from "react";
import { toast } from "sonner";

const SUPPORTED_EXTENSIONS = [
  ".zip",
  ".tar",
  ".tar.gz",
  ".tgz",
  ".tar.bz2",
  ".7z",
  ".rar",
  ".xlsx",
  ".xls",
  ".csv",
  ".pdf",
  ".docx",
  ".doc",
  ".pptx",
  ".ppt",
];

const MAX_FILE_SIZE = 100 * 1024 * 1024;

interface ContentBlock {
  type: string;
  text: string;
  metadata: { name: string };
  file?: File;
}

interface UseFileUploadOptions {
  initialBlocks?: ContentBlock[];
}

export function useFileUpload({ initialBlocks = [] }: UseFileUploadOptions = {}) {
  const [contentBlocks, setContentBlocks] = useState<ContentBlock[]>(initialBlocks);
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragCounter = useRef(0);

  const isDuplicate = (file: File, blocks: ContentBlock[]) => {
    return blocks.some((b) => b?.metadata?.name === file.name);
  };

  const isSupportedFile = (file: File) => {
    const name = file.name.toLowerCase();
    return SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext));
  };

  const uploadFiles = async (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = (await res.json()) as {
      files?: Array<{ path?: string; saved_path?: string }>;
      error?: string;
      detail?: string;
    };
    if (!res.ok) throw new Error(data?.error || data?.detail || `Upload failed (${res.status})`);
    return (data.files || [])
      .map((f) => f.path || f.saved_path)
      .filter((p): p is string => typeof p === "string" && p.length > 0);
  };

  const addFileBlocks = (files: File[]) => {
    const validFiles = files.filter((file) => {
      if (!isSupportedFile(file)) return false;
      if (file.size > MAX_FILE_SIZE) {
        toast.error(`文件 ${file.name} 超过 100MB 限制`);
        return false;
      }
      return true;
    });

    const duplicateFiles = validFiles.filter((file) => isDuplicate(file, contentBlocks));
    const uniqueFiles = validFiles.filter((file) => !isDuplicate(file, contentBlocks));

    if (duplicateFiles.length > 0) {
      toast.error(`重复文件: ${duplicateFiles.map((f) => f.name).join(", ")}`);
    }

    if (uniqueFiles.length > 0) {
      const newBlocks = uniqueFiles.map((file) => ({
        type: "text" as const,
        text: file.name,
        metadata: { name: file.name },
        file,
      }));
      setContentBlocks((prev) => [...prev, ...newBlocks]);
    }
  };

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const fileArray = Array.from(files);
    addFileBlocks(fileArray);
    e.target.value = "";
  };

  // Drag and drop handlers
  useEffect(() => {
    if (!dropRef.current) return;

    const handleWindowDragEnter = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        dragCounter.current += 1;
        setDragOver(true);
      }
    };
    const handleWindowDragLeave = (e: DragEvent) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        dragCounter.current -= 1;
        if (dragCounter.current <= 0) {
          setDragOver(false);
          dragCounter.current = 0;
        }
      }
    };
    const handleWindowDrop = async (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setDragOver(false);

      if (!e.dataTransfer) return;
      const files = Array.from(e.dataTransfer.files);
      addFileBlocks(files);
    };
    const handleWindowDragEnd = () => {
      dragCounter.current = 0;
      setDragOver(false);
    };

    window.addEventListener("dragenter", handleWindowDragEnter);
    window.addEventListener("dragleave", handleWindowDragLeave);
    window.addEventListener("drop", handleWindowDrop);
    window.addEventListener("dragend", handleWindowDragEnd);

    const handleWindowDragOver = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("dragover", handleWindowDragOver);

    return () => {
      window.removeEventListener("dragenter", handleWindowDragEnter);
      window.removeEventListener("dragleave", handleWindowDragLeave);
      window.removeEventListener("drop", handleWindowDrop);
      window.removeEventListener("dragend", handleWindowDragEnd);
      window.removeEventListener("dragover", handleWindowDragOver);
    };
  }, [contentBlocks]);

  const removeBlock = (idx: number) => {
    setContentBlocks((prev) => prev.filter((_, i) => i !== idx));
  };

  const resetBlocks = () => setContentBlocks([]);

  const handlePaste = async (e: React.ClipboardEvent<HTMLTextAreaElement | HTMLInputElement>) => {
    const items = e.clipboardData.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i];
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length === 0) return;
    e.preventDefault();
    addFileBlocks(files);
  };

  return {
    contentBlocks,
    setContentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock,
    resetBlocks,
    dragOver,
    handlePaste,
    uploadFiles,
  };
}
