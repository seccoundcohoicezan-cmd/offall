"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { get, post } from "@/lib/api";
import type { Job, Page } from "@/lib/types";
import { STATUS_LABEL, timeAgo } from "@/lib/format";
import { Badge, Button, EmptyState, ErrorNote, PageHeader, Select, Skeleton } from "@/components/ui";
import { toast } from "@/components/ui/toast";

const TONE = {
  queued: "neutral",
  running: "accent",
  waiting_quota: "warning",
  done: "success",
  failed: "danger",
  cancelled: "neutral",
} as const;
const PAGE = 25;

export default function JobsPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs", status, offset],
    queryFn: () => get<Page<Job>>(`/jobs?limit=${PAGE}&offset=${offset}${status ? `&status=${status}` : ""}`),
    refetchInterval: 5000,
  });

  async function act(path: string) {
    try {
      await post(path);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Jobs"
        subtitle="Semua tugas AI diproses di worker server, tetap jalan walau browser ditutup."
        action={
          <div className="flex items-center gap-2">
            <label htmlFor="status" className="text-sm text-muted">
              Status
            </label>
            <Select
              id="status"
              className="w-44"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Semua</option>
              {Object.keys(TONE).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </Select>
          </div>
        }
      />
      <ErrorNote error={error} />
      {isLoading && <Skeleton className="h-40" />}
      {data?.items.length === 0 && <EmptyState icon={<ListChecks />} title="Belum ada job" />}
      <ul className="flex flex-col gap-2">
        {data?.items.map((j) => (
          <li
            key={j.id}
            className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface/70 p-3 text-sm"
          >
            <Badge tone={TONE[j.status]}>{STATUS_LABEL[j.status]}</Badge>
            <div className="min-w-0 flex-1">
              <Link href={`/chat/${j.chat_id}`} className="font-medium hover:underline">
                {j.model_used ?? j.model_requested}
              </Link>
              <p className="truncate text-xs text-muted">
                {timeAgo(j.created_at)} · percobaan {j.attempts}
                {j.tokens_saved ? ` · ${j.tokens_saved} token dihemat` : ""}
                {j.status === "waiting_quota" && j.retry_at ? ` · coba lagi ${timeAgo(j.retry_at)}` : ""}
                {j.error ? ` · ${j.error}` : ""}
              </p>
            </div>
            {["queued", "running", "waiting_quota"].includes(j.status) && (
              <Button size="sm" variant="danger" onClick={() => act(`/jobs/${j.id}/cancel`)}>
                Batalkan
              </Button>
            )}
            {["failed", "cancelled"].includes(j.status) && !j.result_message_id && (
              <Button size="sm" variant="outline" onClick={() => act(`/jobs/${j.id}/retry`)}>
                Retry
              </Button>
            )}
          </li>
        ))}
      </ul>
      {data && data.total > PAGE && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <Button
            size="sm"
            variant="outline"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            Sebelumnya
          </Button>
          <span className="text-muted">
            {offset + 1}–{Math.min(offset + PAGE, data.total)} dari {data.total}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Berikutnya
          </Button>
        </div>
      )}
    </div>
  );
}
