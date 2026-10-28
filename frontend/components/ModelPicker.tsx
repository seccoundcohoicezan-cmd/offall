"use client";

import Link from "next/link";
import { ChevronRight, Sparkles, Wand2 } from "lucide-react";
import { useModels } from "@/lib/hooks";
import type { Model } from "@/lib/types";
import { cn } from "@/lib/cn";
import { ProviderIcon } from "./ProviderIcon";
import { Skeleton } from "./ui";

function sortModels(models: Model[]): Model[] {
  return [...models].sort((a, b) => Number(b.favorite) - Number(a.favorite));
}

/** Compact dropdown used in the composer. */
export function ModelSelect({
  value,
  onChange,
  id = "model-select",
}: {
  value: string;
  onChange: (v: string) => void;
  id?: string;
}) {
  const { data } = useModels();
  const known = !data || value === "auto" || data.some((m) => m.id === value);
  return (
    <div className="relative flex min-w-0 flex-1 sm:flex-none">
      <label htmlFor={id} className="sr-only">
        Pilih model
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 min-w-0 max-w-[13rem] flex-1 rounded-xl sm:flex-none border border-border bg-surface-2 pl-3 pr-8 text-sm focus:border-accent focus:outline-none"
      >
        <option value="auto">Auto (hemat)</option>
        {!known && <option value={value}>{value} (tidak tersedia)</option>}
        {data &&
          Object.entries(
            sortModels(data).reduce<Record<string, Model[]>>((acc, m) => {
              (acc[m.provider_display] ??= []).push(m);
              return acc;
            }, {}),
          ).map(([group, models]) => (
            <optgroup key={group} label={group}>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.favorite ? "★ " : ""}
                  {m.display_name}
                </option>
              ))}
            </optgroup>
          ))}
      </select>
    </div>
  );
}

/** Right-panel radio list, the "Pilih Provider / Model" card from the design. */
export function ModelPanel({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data, isLoading } = useModels();
  const options: { id: string; title: string; hint: string; provider?: string; strong?: boolean }[] = [
    { id: "auto", title: "Smart Routing (Auto)", hint: "Ringan → model murah, sulit → model kuat" },
    ...sortModels(data ?? []).map((m) => ({
      id: m.id,
      title: m.display_name,
      hint: m.tier === "strong" ? "Kuat untuk analisis & coding" : "Cepat & hemat",
      provider: m.provider,
      strong: m.tier === "strong",
    })),
  ];
  return (
    <fieldset className="min-w-0 rounded-3xl border border-border bg-surface/70 p-4">
      <legend className="sr-only">Pilih provider atau model</legend>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-lg font-semibold">Pilih Provider / Model</p>
        <span className="flex items-center gap-1 rounded-lg bg-accent/15 px-2 py-0.5 text-xs text-accent-2">
          <Wand2 size={12} /> Smart Routing
        </span>
      </div>
      <div className="flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
        {isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}
        {options.map((o) => (
          <label
            key={o.id}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-2xl border p-3 transition",
              value === o.id
                ? "border-accent bg-accent/10 neon-border"
                : "border-border hover:border-accent/50",
            )}
          >
            <input
              type="radio"
              name="model-panel"
              className="accent-[var(--accent)]"
              checked={value === o.id}
              onChange={() => onChange(o.id)}
            />
            {o.provider ? (
              <ProviderIcon provider={o.provider} size={40} />
            ) : (
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-2 text-white">
                <Sparkles size={16} />
              </span>
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{o.title}</span>
              <span className="block truncate text-xs text-muted">{o.hint}</span>
              {o.id === "auto" && (
                <span className="mt-1 inline-block rounded-md bg-success/15 px-1.5 text-[10px] text-success">
                  Recommended
                </span>
              )}
            </span>
            <ChevronRight size={16} className="shrink-0 text-muted" />
          </label>
        ))}
        {data && data.length === 0 && (
          <p className="text-sm text-muted">
            Belum ada model aktif.{" "}
            <Link className="text-accent-2 underline" href="/providers">
              Tambah API key
            </Link>
            .
          </p>
        )}
      </div>
    </fieldset>
  );
}
