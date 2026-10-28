"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, FlaskConical, Star } from "lucide-react";
import { patch } from "@/lib/api";
import { useModels, useProviders, useSettings } from "@/lib/hooks";
import type { Model } from "@/lib/types";
import { cn } from "@/lib/cn";
import { ProviderIcon } from "@/components/ProviderIcon";
import { Badge, Card, EmptyState, PageHeader, Skeleton, Switch } from "@/components/ui";
import { toast } from "@/components/ui/toast";

export default function ModelsPage() {
  const models = useModels(true);
  const providers = useProviders();
  const settings = useSettings();
  const qc = useQueryClient();

  const order = settings.data?.fallback_order ?? [];
  const favorites = new Set(settings.data?.favorite_models ?? []);
  const all = models.data ?? [];
  const ranked = [...all].sort((a, b) => {
    const ia = order.indexOf(a.id);
    const ib = order.indexOf(b.id);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  async function saveSettings(body: Record<string, unknown>) {
    try {
      await patch("/settings", body);
      await qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["models"] });
    } catch (e) {
      toast.error(e);
    }
  }

  function move(index: number, dir: -1 | 1) {
    const ids = ranked.map((m) => m.id);
    const target = index + dir;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    saveSettings({ fallback_order: ids });
  }

  async function toggle(m: Model, on: boolean) {
    const provider = providers.data?.find((p) => p.name === m.provider);
    if (!provider) return;
    try {
      await patch(`/models/${provider.id}/${m.model_name}`, { is_enabled: on });
      qc.invalidateQueries({ queryKey: ["models"] });
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Models"
        subtitle="Urutan di bawah = urutan fallback mode Auto dan saat model gagal. Bintang = favorit di picker."
      />
      {models.isLoading && <Skeleton className="h-60" />}
      {models.data?.length === 0 && (
        <EmptyState icon={<FlaskConical />} title="Belum ada model">
          Tambahkan provider & key di halaman Multi-Provider.
        </EmptyState>
      )}
      <Card className="flex flex-col divide-y divide-border p-0">
        {ranked.map((m, i) => (
          <div
            key={m.id}
            className={cn("flex flex-wrap items-center gap-3 p-3", !m.is_enabled && "opacity-60")}
          >
            <div className="flex flex-col">
              <button
                onClick={() => move(i, -1)}
                disabled={i === 0}
                aria-label={`Naikkan ${m.display_name}`}
                className="text-muted disabled:opacity-30"
              >
                <ArrowUp size={14} />
              </button>
              <button
                onClick={() => move(i, 1)}
                disabled={i === ranked.length - 1}
                aria-label={`Turunkan ${m.display_name}`}
                className="text-muted disabled:opacity-30"
              >
                <ArrowDown size={14} />
              </button>
            </div>
            <span className="w-6 text-center text-sm text-muted">{i + 1}</span>
            <ProviderIcon provider={m.provider} size={32} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{m.display_name}</p>
              <p className="text-xs text-muted">
                {m.id} · konteks {Intl.NumberFormat("id-ID").format(m.context_window)} · ${m.cost_in}/$
                {m.cost_out} per 1M
              </p>
            </div>
            <Badge tone={m.tier === "strong" ? "accent" : "success"}>
              {m.tier === "strong" ? "Kuat" : "Hemat"}
            </Badge>
            <button
              aria-label={
                favorites.has(m.id) ? `Hapus favorit ${m.display_name}` : `Jadikan favorit ${m.display_name}`
              }
              aria-pressed={favorites.has(m.id)}
              onClick={() =>
                saveSettings({
                  favorite_models: favorites.has(m.id)
                    ? [...favorites].filter((f) => f !== m.id)
                    : [...favorites, m.id],
                })
              }
            >
              <Star size={18} className={favorites.has(m.id) ? "fill-warning text-warning" : "text-muted"} />
            </button>
            <Switch
              label={`Aktifkan ${m.display_name}`}
              checked={m.is_enabled}
              onChange={(on) => toggle(m, on)}
            />
          </div>
        ))}
      </Card>
    </div>
  );
}
