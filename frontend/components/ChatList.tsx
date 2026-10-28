"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ChevronRight, MessageCircle, Search, Sparkles } from "lucide-react";
import { useChats } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { Skeleton } from "./ui";

export function ChatList({ onNavigate }: { onNavigate?: () => void }) {
  const { data, isLoading, isError } = useChats();
  const params = useParams<{ id?: string }>();
  const [q, setQ] = useState("");
  const items = (data?.items ?? []).filter((c) => c.title.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <nav aria-label="Daftar chat" className="flex h-full min-h-0 flex-col gap-3">
      <Link
        href="/chat"
        onClick={onNavigate}
        className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-accent to-accent-2 font-medium text-white shadow-lg shadow-accent/30 hover:brightness-110"
      >
        <Sparkles size={18} /> Chat Baru
      </Link>
      <label className="relative shrink-0">
        <span className="sr-only">Cari chat</span>
        <Search
          size={16}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
        />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Cari chat..."
          className="h-11 w-full rounded-xl border border-border bg-surface-2/70 pl-9 pr-3 text-sm placeholder:text-muted focus:border-accent focus:outline-none"
        />
      </label>
      <div className="-mx-1 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-1">
        {isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-14 shrink-0" />)}
        {isError && <p className="text-sm text-danger">Gagal memuat chat.</p>}
        {data && items.length === 0 && (
          <p className="px-2 py-6 text-center text-sm text-muted">
            {q ? "Tidak ada chat yang cocok." : "Belum ada chat."}
          </p>
        )}
        {items.map((c) => {
          const active = params.id === c.id;
          return (
            <Link
              key={c.id}
              href={`/chat/${c.id}`}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-3 rounded-2xl px-3 py-2.5 transition",
                active
                  ? "bg-gradient-to-r from-accent/45 to-accent/15 ring-1 ring-accent/60"
                  : "hover:bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                  active ? "bg-accent/40 text-white" : "bg-surface-2 text-muted",
                )}
              >
                <MessageCircle size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{c.title}</span>
                <span className="block text-xs text-muted">{timeAgo(c.updated_at ?? c.created_at)}</span>
              </span>
              <ChevronRight size={16} className="shrink-0 text-muted" />
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
