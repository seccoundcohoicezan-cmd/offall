"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, FlaskConical, Plus, Trash2 } from "lucide-react";
import { del, patch, post } from "@/lib/api";
import type { KeyStatus, Provider, ProviderKey, Strategy } from "@/lib/types";
import { formatTokens, STATUS_LABEL, timeAgo } from "@/lib/format";
import { ProviderIcon } from "./ProviderIcon";
import { cn } from "@/lib/cn";
import { GatewayModels } from "./GatewayModels";
import { CUSTOM_MODEL_PROVIDERS, KEYLESS_PROVIDERS } from "@/lib/providers";
import { Badge, Button, Card, Input, Label, Select, Switch } from "./ui";
import { toast } from "./ui/toast";

const TONE: Record<KeyStatus, "success" | "warning" | "danger" | "neutral"> = {
  active: "success",
  cooling_down: "warning",
  exhausted: "warning",
  invalid: "danger",
  disabled: "neutral",
};

function recovery(k: ProviderKey): string | null {
  if (k.status === "cooling_down" && k.cooldown_until) return `pulih ${timeAgo(k.cooldown_until)}`;
  if (k.status === "exhausted" && k.reset_at) return `reset ${timeAgo(k.reset_at)}`;
  return null;
}

export function KeyPoolCard({ provider }: { provider: Provider }) {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [quota, setQuota] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["providers"] });
    qc.invalidateQueries({ queryKey: ["models"] });
  };
  const base = `/providers/${provider.id}`;

  async function addKey(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await post(`${base}/keys`, {
        label: label || `Akun ${String.fromCharCode(65 + provider.keys.length)}`,
        api_key: secret,
        daily_token_quota: quota ? Number(quota) : null,
      });
      setLabel("");
      setSecret("");
      setQuota("");
      toast.success("Key disimpan terenkripsi");
      refresh();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function run(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      if (done) toast.success(done);
      refresh();
    } catch (err) {
      toast.error(err);
    }
  }

  async function test(k: ProviderKey) {
    try {
      const res = await post<{ ok: boolean; message: string }>(`${base}/keys/${k.id}/test`);
      if (res.ok) toast.success(`${k.label}: ${res.message}`);
      else toast.error(`${k.label}: ${res.message}`);
      refresh();
    } catch (err) {
      toast.error(err);
    }
  }

  async function move(index: number, dir: -1 | 1) {
    const keys = [...provider.keys];
    const target = index + dir;
    if (target < 0 || target >= keys.length) return;
    [keys[index], keys[target]] = [keys[target], keys[index]];
    await run(() =>
      Promise.all(
        keys.map((k, i) => (k.priority === i ? null : patch(`${base}/keys/${k.id}`, { priority: i }))),
      ),
    );
  }

  const usable = provider.usable_keys;

  function editBaseUrl() {
    const value = prompt("Base URL (kosongkan untuk endpoint resmi)", provider.base_url ?? "");
    if (value === null) return;
    run(
      () => patch(base, { base_url: value.trim() }),
      value.trim() ? "Base URL diperbarui" : "Kembali ke endpoint resmi",
    );
  }
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <ProviderIcon provider={provider.name} size={40} />
        <div className="flex-1">
          <h2 className="font-semibold">{provider.display_name}</h2>
          <p className="text-xs text-muted">
            {usable}/{provider.keys.length} key bisa dipakai
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1 text-xs">
            <span className="text-muted">Endpoint:</span>
            <span
              className={cn(
                "font-mono",
                provider.base_url && !CUSTOM_MODEL_PROVIDERS.has(provider.name) && provider.name !== "ollama"
                  ? "text-warning"
                  : "text-muted",
              )}
            >
              {provider.base_url || "resmi (default)"}
            </span>
            <button type="button" onClick={editBaseUrl} className="text-accent-2 underline">
              ubah
            </button>
          </p>
          {provider.base_url && !CUSTOM_MODEL_PROVIDERS.has(provider.name) && provider.name !== "ollama" && (
            <p className="mt-1 text-xs text-warning">
              Provider resmi memakai Base URL kustom. Kosongkan jika ingin langsung ke API resmi.
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor={`strategy-${provider.id}`} className="text-xs text-muted">
            Strategi rotasi
          </label>
          <Select
            id={`strategy-${provider.id}`}
            className="h-9 w-40"
            value={provider.rotation_strategy}
            onChange={(e) =>
              run(() => patch(base, { rotation_strategy: e.target.value as Strategy }), "Strategi diperbarui")
            }
          >
            <option value="fill_first">Fill-first</option>
            <option value="round_robin">Round-robin</option>
            <option value="least_used">Least-used</option>
          </Select>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Hapus provider ${provider.display_name}`}
            onClick={() =>
              confirm(`Hapus provider ${provider.display_name} dan semua key-nya?`) &&
              run(() => del(base), "Provider dihapus")
            }
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {provider.keys.length > 0 && usable <= 1 && !(usable === 1 && KEYLESS_PROVIDERS.has(provider.name)) && (
        <p
          role="alert"
          className="rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
        >
          {usable === 0
            ? "Semua key sedang tidak bisa dipakai. Job akan menunggu kuota pulih."
            : "Tinggal 1 key aktif. Tambah key cadangan agar rotasi tetap jalan."}
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {provider.keys.map((k, i) => {
          const pct = k.daily_token_quota
            ? Math.min(100, (k.tokens_used_today / k.daily_token_quota) * 100)
            : null;
          return (
            <li
              key={k.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface-2/50 p-3"
              data-testid="key-row"
            >
              <div className="flex flex-col">
                <button
                  onClick={() => move(i, -1)}
                  disabled={i === 0}
                  aria-label={`Naikkan prioritas ${k.label}`}
                  className="text-muted disabled:opacity-30"
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={i === provider.keys.length - 1}
                  aria-label={`Turunkan prioritas ${k.label}`}
                  className="text-muted disabled:opacity-30"
                >
                  <ArrowDown size={14} />
                </button>
              </div>
              <div className="min-w-[10rem] flex-1">
                <p className="text-sm font-medium">
                  {i + 1}. {k.label} <span className="font-mono text-xs text-muted">{k.key_hint}</span>
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <Badge tone={TONE[k.status]}>{STATUS_LABEL[k.status]}</Badge>
                  <span>Hari ini: {formatTokens(k.tokens_used_today)} token</span>
                  {k.daily_token_quota && (
                    <span>Sisa: {formatTokens(Math.max(0, k.daily_token_quota - k.tokens_used_today))}</span>
                  )}
                  {recovery(k) && <span>{recovery(k)}</span>}
                </div>
                {pct !== null && (
                  <div className="mt-1.5 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-border">
                    <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
                  </div>
                )}
                {k.last_error && k.status !== "active" && (
                  <p className="mt-1 truncate text-xs text-danger">{k.last_error}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => test(k)}>
                  <FlaskConical size={14} /> Tes
                </Button>
                <Switch
                  label={`Aktifkan ${k.label}`}
                  checked={k.status !== "disabled"}
                  onChange={(on) => run(() => patch(`${base}/keys/${k.id}`, { enabled: on }))}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Hapus key ${k.label}`}
                  onClick={() =>
                    confirm(`Hapus key ${k.label}?`) && run(() => del(`${base}/keys/${k.id}`), "Key dihapus")
                  }
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </li>
          );
        })}
      </ul>

      {CUSTOM_MODEL_PROVIDERS.has(provider.name) && <GatewayModels provider={provider} />}

      <form onSubmit={addKey} className="grid gap-2 sm:grid-cols-[1fr_2fr_1fr_auto] sm:items-end">
        <div>
          <Label htmlFor={`label-${provider.id}`}>Label</Label>
          <Input
            id={`label-${provider.id}`}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={`Akun ${String.fromCharCode(65 + provider.keys.length)}`}
            maxLength={80}
          />
        </div>
        <div>
          <Label htmlFor={`secret-${provider.id}`}>API key</Label>
          <Input
            id={`secret-${provider.id}`}
            type="password"
            autoComplete="off"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={KEYLESS_PROVIDERS.has(provider.name) ? "opsional" : "sk-..."}
            required={!KEYLESS_PROVIDERS.has(provider.name)}
          />
        </div>
        <div>
          <Label htmlFor={`quota-${provider.id}`} hint="(opsional)">
            Kuota/hari
          </Label>
          <Input
            id={`quota-${provider.id}`}
            type="number"
            min={1}
            value={quota}
            onChange={(e) => setQuota(e.target.value)}
            placeholder="token"
          />
        </div>
        <Button type="submit" disabled={busy}>
          <Plus size={16} /> Tambah key
        </Button>
      </form>
    </Card>
  );
}
