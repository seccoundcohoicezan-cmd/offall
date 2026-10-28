"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Plus, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useChats } from "@/lib/hooks";
import { del } from "@/lib/api";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { Skeleton } from "./ui";
import { toast } from "./ui/toast";

export function ChatList() {
  const { data, isLoading, isError } = useChats();
  const params = useParams<{ id?: string }>();
  const qc = useQueryClient();

  async function remove(id: string) {
    if (!confirm("Hapus chat ini beserta seluruh riwayatnya?")) return;
    try {
      await del(`/chats/${id}`);
      await qc.invalidateQueries({ queryKey: ["chats"] });
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <nav aria-label="Daftar chat" className="flex h-full flex-col gap-2">
      <Link
        href="/chat"
        className="flex h-10 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-2 text-sm font-medium text-white"
      >
        <Plus size={16} /> Chat baru
      </Link>
      <div className="flex flex-col gap-1 overflow-y-auto">
        {isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}
        {isError && <p className="text-sm text-danger">Gagal memuat chat.</p>}
        {data?.items.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-muted">Belum ada chat.</p>
        )}
        {data?.items.map((c) => (
          <div
            key={c.id}
            className={cn(
              "group flex items-center gap-1 rounded-xl px-3 py-2 text-sm",
              params.id === c.id ? "bg-accent/15 text-text" : "text-muted hover:bg-surface-2 hover:text-text",
            )}
          >
            <Link href={`/chat/${c.id}`} className="min-w-0 flex-1">
              <span className="block truncate">{c.title}</span>
              <span className="text-[11px] text-muted">{timeAgo(c.updated_at ?? c.created_at)}</span>
            </Link>
            <button
              onClick={() => remove(c.id)}
              aria-label={`Hapus chat ${c.title}`}
              className="opacity-0 transition group-hover:opacity-100 focus:opacity-100"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </nav>
  );
}
