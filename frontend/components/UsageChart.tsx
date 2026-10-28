"use client";

import { useState } from "react";
import { formatTokens } from "@/lib/format";

export interface Bar {
  label: string;
  value: number;
  detail?: string;
}

/** Single-series bar chart: one hue, thin bars, rounded data-end, hover tooltip per bar. */
export function UsageChart({
  title,
  bars,
  color = "var(--accent)",
}: {
  title: string;
  bars: Bar[];
  color?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...bars.map((b) => b.value));
  const height = 160;
  return (
    <figure className="rounded-2xl border border-border bg-surface/70 p-4">
      <figcaption className="mb-3 text-sm font-semibold">{title}</figcaption>
      {bars.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted">Belum ada data.</p>
      ) : (
        <div className="relative">
          <div
            className="flex items-end gap-[2px] border-b border-border"
            style={{ height }}
            role="img"
            aria-label={title}
          >
            {bars.map((b, i) => (
              <div
                key={b.label}
                className="flex h-full flex-1 items-end"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={`${b.label}: ${b.value}`}
              >
                <div
                  className="mx-auto w-full max-w-6 rounded-t-[4px] transition-opacity"
                  style={{
                    height: `${(b.value / max) * 100}%`,
                    minHeight: b.value ? 2 : 0,
                    background: color,
                    opacity: hover === null || hover === i ? 1 : 0.45,
                  }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted">
            <span>{bars[0].label}</span>
            <span>maks {formatTokens(max)}</span>
            <span>{bars[bars.length - 1].label}</span>
          </div>
          {hover !== null && (
            <div className="pointer-events-none absolute -top-2 left-1/2 -translate-x-1/2 rounded-lg border border-border bg-surface px-2 py-1 text-xs shadow-lg">
              <b>{bars[hover].label}</b>: {formatTokens(bars[hover].value)}
              {bars[hover].detail && <span className="text-muted"> · {bars[hover].detail}</span>}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
