"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import type { UsageSummary, UsageTotals } from "@/lib/types";
import { formatTokens, formatUsd } from "@/lib/format";
import { UsageChart } from "@/components/UsageChart";
import { Card, ErrorNote, PageHeader, Select, Skeleton } from "@/components/ui";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted">{sub}</p>}
    </Card>
  );
}

function Row({ name, t }: { name: string; t: UsageTotals }) {
  return (
    <tr className="border-t border-border">
      <td className="py-2 pr-3">{name}</td>
      <td className="py-2 pr-3 text-right">{t.requests}</td>
      <td className="py-2 pr-3 text-right">{formatTokens(t.tokens_in + t.tokens_out)}</td>
      <td className="py-2 pr-3 text-right">{formatTokens(t.tokens_saved)}</td>
      <td className="py-2 pr-3 text-right">{t.cache_hits}</td>
      <td className="py-2 text-right">{formatUsd(t.cost)}</td>
    </tr>
  );
}

function Table({ title, rows }: { title: string; rows: { name: string; t: UsageTotals }[] }) {
  return (
    <Card className="overflow-x-auto">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted">
          <tr>
            <th className="py-1 text-left font-medium">Nama</th>
            <th className="py-1 text-right font-medium">Request</th>
            <th className="py-1 text-right font-medium">Token</th>
            <th className="py-1 text-right font-medium">Dihemat</th>
            <th className="py-1 text-right font-medium">Cache hit</th>
            <th className="py-1 text-right font-medium">Biaya</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Row key={r.name} {...r} />
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="py-4 text-center text-muted">
                Belum ada pemakaian.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

export default function UsagePage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, error } = useQuery({
    queryKey: ["usage", days],
    queryFn: () => get<UsageSummary>(`/usage/summary?days=${days}`),
  });
  const t = data?.total;
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Analytics"
        subtitle="Token, biaya, cache, dan penghematan per hari, provider, dan key."
        action={
          <div className="flex items-center gap-2">
            <label htmlFor="range" className="text-sm text-muted">
              Rentang
            </label>
            <Select
              id="range"
              className="w-36"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={1}>Hari ini</option>
              <option value={7}>7 hari</option>
              <option value={30}>30 hari</option>
              <option value={90}>90 hari</option>
            </Select>
          </div>
        }
      />
      <ErrorNote error={error} />
      {isLoading && <Skeleton className="h-64" />}
      {t && data && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label="Token terpakai"
              value={formatTokens(t.tokens_in + t.tokens_out)}
              sub={`${t.requests} request`}
            />
            <Stat
              label="Token dihemat"
              value={formatTokens(t.tokens_saved)}
              sub={`${t.saving_pct}% penghematan`}
            />
            <Stat
              label="Cache hit"
              value={String(t.cache_hits)}
              sub={`${(t.cache_hit_rate * 100).toFixed(1)}% dari request`}
            />
            <Stat label="Estimasi biaya" value={formatUsd(t.cost)} sub="harga list per 1M token" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <UsageChart
              title="Token terpakai per hari"
              bars={data.per_day.map((d) => ({
                label: d.day.slice(5),
                value: d.tokens_in + d.tokens_out,
                detail: `${d.requests} req`,
              }))}
            />
            <UsageChart
              title="Token dihemat per hari"
              color="var(--success)"
              bars={data.per_day.map((d) => ({
                label: d.day.slice(5),
                value: d.tokens_saved,
                detail: `${d.cache_hits} cache hit`,
              }))}
            />
          </div>
          <Table title="Per provider" rows={data.per_provider.map((p) => ({ name: p.provider, t: p }))} />
          <Table
            title="Per key (Akun A/B/C)"
            rows={data.per_key.map((k) => ({ name: `${k.provider} · ${k.label} (${k.key_hint})`, t: k }))}
          />
        </div>
      )}
    </div>
  );
}
