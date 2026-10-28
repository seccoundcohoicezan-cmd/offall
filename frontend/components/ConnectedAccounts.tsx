"use client";

import Link from "next/link";
import { CheckCircle2, Plus, AlertTriangle } from "lucide-react";
import { useProviders } from "@/lib/hooks";
import { ProviderIcon } from "./ProviderIcon";
import { Skeleton } from "./ui";
import { formatTokens } from "@/lib/format";

/** Sidebar card: each provider's key pool at a glance (usable keys + today's tokens). */
export function ConnectedAccounts() {
  const { data, isLoading } = useProviders();
  const usable = data?.filter((p) => p.usable_keys > 0).length ?? 0;
  return (
    <div className="rounded-2xl border border-border bg-surface/70 p-3">
      <div className="mb-2 flex items-center justify-between text-sm font-medium">
        <span>+ Connected AI Accounts</span>
        <span className="rounded-md bg-accent/20 px-1.5 text-xs text-accent-2">
          {usable}/{data?.length ?? 0}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {isLoading && [0, 1].map((i) => <Skeleton key={i} className="h-16" />)}
        {data?.map((p) => {
          const today = p.keys.reduce((s, k) => s + k.tokens_used_today, 0);
          const quota = p.keys.reduce((s, k) => s + (k.daily_token_quota ?? 0), 0);
          const pct = quota ? Math.min(100, (today / quota) * 100) : Math.min(100, p.usable_keys ? 12 : 0);
          return (
            <Link
              key={p.id}
              href="/providers"
              className="rounded-xl border border-border bg-surface-2/60 p-2.5 hover:border-accent/60"
            >
              <div className="flex items-center gap-2.5">
                <ProviderIcon provider={p.name} size={30} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{p.display_name}</p>
                  <p className={p.usable_keys ? "text-xs text-success" : "text-xs text-warning"}>
                    ● {p.usable_keys}/{p.keys.length} key aktif
                  </p>
                </div>
                {p.usable_keys ? (
                  <CheckCircle2 size={16} className="text-success" />
                ) : (
                  <AlertTriangle size={16} className="text-warning" />
                )}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                  <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-[11px] text-muted">
                  {formatTokens(today)}
                  {quota ? ` / ${formatTokens(quota)}` : ""}
                </span>
              </div>
            </Link>
          );
        })}
        <Link
          href="/providers"
          className="flex h-10 items-center justify-center gap-1.5 rounded-xl border border-dashed border-accent/60 text-sm text-accent-2 hover:bg-accent/10"
        >
          <Plus size={16} /> Add Provider
        </Link>
      </div>
    </div>
  );
}
