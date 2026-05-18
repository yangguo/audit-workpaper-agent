"use client";

import { Thread } from "@/components/thread";
import { StreamProvider } from "@/providers/Stream";
import { Toaster } from "@/components/ui/sonner";
import React from "react";

export default function HomePage(): React.ReactNode {
  return (
    <React.Suspense fallback={<div className="flex h-screen items-center justify-center text-muted-foreground">Loading...</div>}>
      <Toaster />
      <StreamProvider>
        <Thread />
      </StreamProvider>
    </React.Suspense>
  );
}
