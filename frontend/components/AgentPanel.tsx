"use client";

import Link from "next/link";
import { Bot, Settings2 } from "lucide-react";
import { useAgents } from "@/lib/hooks";
import { Skeleton, Switch } from "./ui";

/** One agent can be active per chat; its instructions become the system prompt. */
export function AgentPanel({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const { data, isLoading } = useAgents();
  const agents = data?.filter((a) => a.is_enabled) ?? [];
  return (
    <div className="rounded-2xl border border-border bg-surface/70 p-3">
      <div className="mb-3 flex items-center justify-between">
        <p className="font-semibold">
          AI Agents{" "}
          <span className="ml-1 rounded-md bg-accent/20 px-1.5 text-[10px] text-accent-2">Beta</span>
        </p>
        <Link href="/agents" className="flex items-center gap-1 text-xs text-muted underline hover:text-text">
          <Settings2 size={12} /> Manage
        </Link>
      </div>
      <div className="flex flex-col divide-y divide-border">
        {isLoading && <Skeleton className="h-12" />}
        {agents.map((a) => (
          <div key={a.id} className="flex items-center gap-3 py-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-surface-2 text-accent-2">
              <Bot size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{a.name}</p>
              <p className="truncate text-xs text-muted">
                {a.description || a.instructions.slice(0, 60) || "Tanpa instruksi"}
              </p>
            </div>
            <Switch
              label={`Aktifkan agent ${a.name}`}
              checked={value === a.id}
              onChange={(on) => onChange(on ? a.id : null)}
            />
          </div>
        ))}
        {!isLoading && agents.length === 0 && (
          <p className="py-2 text-sm text-muted">
            Belum ada agent.{" "}
            <Link href="/agents" className="text-accent-2 underline">
              Buat agent
            </Link>{" "}
            dengan nama & instruksi sendiri.
          </p>
        )}
      </div>
    </div>
  );
}
