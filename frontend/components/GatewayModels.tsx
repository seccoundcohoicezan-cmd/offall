"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { del, get, post } from "@/lib/api";
import type { Model, Provider } from "@/lib/types";
import { Badge, Button, Input, Select } from "./ui";
import { toast } from "./ui/toast";

/** Model list for gateways such as 9Router: sync from /v1/models or add names by hand. */
export function GatewayModels({
  provider,
  collapsible = false,
}: {
  provider: Provider;
  collapsible?: boolean;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [tier, setTier] = useState("cheap");
  const [syncing, setSyncing] = useState(false);
  const models = useQuery({
    queryKey: ["models", true],
    queryFn: () => get<Model[]>("/models?include_all=true"),
  });
  const mine = (models.data?.filter((m) => m.provider === provider.name) ?? []).sort(
    (a, b) => Number(b.is_enabled) - Number(a.is_enabled) || a.model_name.localeCompare(b.model_name),
  );
  const enabled = mine.filter((m) => m.is_enabled).length;
  const base = `/providers/${provider.id}/models`;
  const refresh = () => qc.invalidateQueries({ queryKey: ["models"] });

  async function sync() {
    setSyncing(true);
    try {
      const res = await post<{ added: string[]; total: number }>(`${base}/sync`);
      toast.success(
        res.added.length ? `${res.added.length} model baru dari endpoint` : "Daftar model sudah terbaru",
      );
      refresh();
    } catch (e) {
      toast.error(e);
    } finally {
      setSyncing(false);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post(base, { model_name: name.trim(), tier });
      setName("");
      refresh();
    } catch (err) {
      toast.error(err);
    }
  }

  const body = (
    <div className="rounded-2xl border border-border bg-surface-2/40 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          Model aktif {enabled}/{mine.length}
        </p>
        <Button size="sm" variant="outline" onClick={sync} disabled={syncing}>
          <RefreshCw size={14} className={syncing ? "animate-spin" : ""} /> Sinkron model dari provider
        </Button>
      </div>
      {mine.length === 0 && (
        <p className="mb-2 text-xs text-muted">
          Belum ada model. Klik sinkron (9Router harus bisa dijangkau dari server) atau tambah nama model
          manual, misalnya
          <code className="mx-1">cc/claude-sonnet-4.5</code>.
        </p>
      )}
      <ul className="mb-2 flex flex-wrap gap-1.5">
        {mine.map((m) => (
          <li
            key={m.id}
            className="flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 text-xs"
          >
            <span className="font-mono">{m.model_name}</span>
            <Badge tone={m.tier === "strong" ? "accent" : "success"}>
              {m.tier === "strong" ? "kuat" : "hemat"}
            </Badge>
            <button
              aria-label={`Hapus model ${m.model_name}`}
              className="text-muted hover:text-danger"
              onClick={async () => {
                await del(`${base}/${m.model_name}`).catch(toast.error);
                refresh();
              }}
            >
              <Trash2 size={12} />
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex flex-wrap gap-2">
        <Input
          aria-label="Nama model"
          className="min-w-[12rem] flex-1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="nama model, mis. kr/qwen3-coder"
          required
        />
        <Select
          aria-label="Tier model"
          className="w-32"
          value={tier}
          onChange={(e) => setTier(e.target.value)}
        >
          <option value="cheap">Hemat</option>
          <option value="strong">Kuat</option>
        </Select>
        <Button type="submit" variant="outline">
          <Plus size={14} /> Tambah model
        </Button>
      </form>
    </div>
  );
  if (!collapsible) return body;
  return (
    <details className="group">
      <summary className="cursor-pointer select-none text-sm text-muted hover:text-text">
        Model ({enabled} aktif) · klik untuk lihat / sinkron
      </summary>
      <div className="mt-2">{body}</div>
    </details>
  );
}
