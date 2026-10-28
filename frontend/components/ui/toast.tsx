"use client";

import { create } from "zustand";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

interface Toast {
  id: number;
  message: string;
  tone: "info" | "success" | "error";
}

interface ToastState {
  toasts: Toast[];
  push: (message: string, tone?: Toast["tone"]) => void;
  dismiss: (id: number) => void;
}

let seq = 0;

export const useToast = create<ToastState>((set) => ({
  toasts: [],
  push: (message, tone = "info") => {
    const id = ++seq;
    set((s) => ({ toasts: [...s.toasts, { id, message, tone }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  info: (m: string) => useToast.getState().push(m, "info"),
  success: (m: string) => useToast.getState().push(m, "success"),
  error: (e: unknown) => useToast.getState().push(e instanceof Error ? e.message : String(e), "error"),
};

export function Toaster() {
  const { toasts, dismiss } = useToast();
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            "pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2 text-sm shadow-xl backdrop-blur",
            t.tone === "error" && "border-danger/50 bg-danger/15",
            t.tone === "success" && "border-success/50 bg-success/15",
            t.tone === "info" && "border-border bg-surface",
          )}
        >
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            aria-label="Tutup notifikasi"
            className="text-muted hover:text-text"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
