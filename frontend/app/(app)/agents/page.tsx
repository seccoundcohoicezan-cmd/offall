"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { del, patch, post } from "@/lib/api";
import { useAgents } from "@/lib/hooks";
import type { Agent } from "@/lib/types";
import { ModelSelect } from "@/components/ModelPicker";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  Label,
  PageHeader,
  Skeleton,
  Switch,
  Textarea,
} from "@/components/ui";
import { toast } from "@/components/ui/toast";

const EMPTY = { name: "", description: "", instructions: "", default_model: "auto", is_enabled: true };

export default function AgentsPage() {
  const { data, isLoading, error } = useAgents();
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["agents"] });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      if (editing) await patch(`/agents/${editing}`, form);
      else await post("/agents", form);
      toast.success(editing ? "Agent diperbarui" : "Agent dibuat");
      setForm(EMPTY);
      setEditing(null);
      refresh();
    } catch (err) {
      toast.error(err);
    } finally {
      setSaving(false);
    }
  }

  function edit(a: Agent) {
    setEditing(a.id);
    setForm({
      name: a.name,
      description: a.description,
      instructions: a.instructions,
      default_model: a.default_model,
      is_enabled: a.is_enabled,
    });
  }

  async function remove(a: Agent) {
    if (!confirm(`Hapus agent ${a.name}?`)) return;
    await del(`/agents/${a.id}`).catch(toast.error);
    refresh();
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="AI Agents"
        subtitle="Beri nama & instruksi. Aktifkan agent di panel kanan chat untuk memakainya."
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <form onSubmit={save} className="flex flex-col gap-3">
            <h2 className="font-semibold">{editing ? "Edit agent" : "Agent baru"}</h2>
            <div>
              <Label htmlFor="agent-name">Nama agent</Label>
              <Input
                id="agent-name"
                required
                maxLength={80}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Data Analyst"
              />
            </div>
            <div>
              <Label htmlFor="agent-desc" hint="(opsional)">
                Deskripsi singkat
              </Label>
              <Input
                id="agent-desc"
                maxLength={300}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Analisis data & visualisasi"
              />
            </div>
            <div>
              <Label htmlFor="agent-instr">Instruksi (system prompt)</Label>
              <Textarea
                id="agent-instr"
                rows={8}
                maxLength={20000}
                value={form.instructions}
                onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                placeholder="Kamu analis data senior. Jawab dengan tabel bila relevan..."
              />
            </div>
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="mb-1 block text-sm font-medium">Model default</span>
                <ModelSelect
                  id="agent-model"
                  value={form.default_model}
                  onChange={(v) => setForm({ ...form, default_model: v })}
                />
              </div>
              <div className="flex items-center gap-2 text-sm">
                Aktif{" "}
                <Switch
                  label="Agent aktif"
                  checked={form.is_enabled}
                  onChange={(v) => setForm({ ...form, is_enabled: v })}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={saving}>
                <Plus size={16} /> {editing ? "Simpan" : "Buat agent"}
              </Button>
              {editing && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setEditing(null);
                    setForm(EMPTY);
                  }}
                >
                  Batal
                </Button>
              )}
            </div>
          </form>
        </Card>
        <div className="flex flex-col gap-3">
          <ErrorNote error={error} />
          {isLoading && <Skeleton className="h-24" />}
          {data?.length === 0 && (
            <EmptyState icon={<Bot />} title="Belum ada agent">
              Buat agent pertama di form sebelah.
            </EmptyState>
          )}
          {data?.map((a) => (
            <Card key={a.id} className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent-2">
                <Bot size={20} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {a.name} {!a.is_enabled && <span className="text-xs text-muted">(nonaktif)</span>}
                </p>
                <p className="text-sm text-muted">{a.description}</p>
                <p className="mt-1 line-clamp-2 text-xs text-muted">{a.instructions}</p>
                <p className="mt-1 text-xs text-accent-2">Model: {a.default_model}</p>
              </div>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => edit(a)} aria-label={`Edit ${a.name}`}>
                  <Pencil size={14} />
                </Button>
                <Button size="sm" variant="ghost" onClick={() => remove(a)} aria-label={`Hapus ${a.name}`}>
                  <Trash2 size={14} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
