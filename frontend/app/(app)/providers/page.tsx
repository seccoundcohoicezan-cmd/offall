"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Boxes, ShieldCheck } from "lucide-react";
import { post } from "@/lib/api";
import { useProviders } from "@/lib/hooks";
import { PROVIDER_OPTIONS, URL_PROVIDERS } from "@/lib/providers";
import { KeyPoolCard } from "@/components/KeyPoolCard";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
} from "@/components/ui";
import { toast } from "@/components/ui/toast";

export default function ProvidersPage() {
  const { data, isLoading, error } = useProviders();
  const qc = useQueryClient();
  const [name, setName] = useState("anthropic");
  const [baseUrl, setBaseUrl] = useState("");
  const existing = new Set(data?.map((p) => p.name));

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post("/providers", { name, base_url: URL_PROVIDERS.has(name) ? baseUrl || null : null });
      setBaseUrl("");
      qc.invalidateQueries({ queryKey: ["providers"] });
      toast.success("Provider ditambahkan. Sekarang tambah API key-nya.");
    } catch (err) {
      toast.error(err);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Multi-Provider & Key Pool"
        subtitle="Banyak key per provider. Saat satu key kena limit, gateway pindah otomatis ke key berikutnya."
      />
      <p className="mb-4 flex items-start gap-2 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-sm">
        <ShieldCheck size={18} className="mt-0.5 shrink-0 text-accent-2" />
        <span>
          <b>Gunakan hanya key milik sendiri atau yang diizinkan pemiliknya.</b> Key disimpan terenkripsi
          (AES-256-GCM) dan tidak pernah ditampilkan utuh lagi. Membuat akun massal untuk mengakali batas
          gratis melanggar ketentuan provider.
        </span>
      </p>
      <Card className="mb-4">
        <form onSubmit={create} className="grid gap-2 sm:grid-cols-[1fr_1.5fr_auto] sm:items-end">
          <div>
            <Label htmlFor="provider-name">Provider</Label>
            <Select id="provider-name" value={name} onChange={(e) => setName(e.target.value)}>
              {PROVIDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value} disabled={existing.has(o.value)}>
                  {o.label}
                  {existing.has(o.value) ? " (sudah ada)" : ""}
                </option>
              ))}
            </Select>
          </div>
          {URL_PROVIDERS.has(name) ? (
            <div>
              <Label htmlFor="provider-url" hint="(alamat endpoint, bukan API key)">
                Base URL
              </Label>
              <Input
                id="provider-url"
                type="url"
                inputMode="url"
                autoComplete="off"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  name === "ollama"
                    ? "http://host.docker.internal:11434"
                    : "http://host.docker.internal:20128/v1"
                }
              />
            </div>
          ) : (
            <p className="self-center text-xs text-muted">
              Memakai endpoint resmi provider. API key diisi di kartu provider setelah ditambahkan.
            </p>
          )}
          <Button type="submit" disabled={existing.has(name)}>
            <Boxes size={16} /> Tambah provider
          </Button>
        </form>
      </Card>
      <ErrorNote error={error} />
      <div className="flex flex-col gap-4">
        {isLoading && [0, 1].map((i) => <Skeleton key={i} className="h-48" />)}
        {data?.length === 0 && (
          <EmptyState icon={<Boxes />} title="Belum ada provider">
            Tambahkan Claude, OpenAI, Gemini, Groq, dll. di atas.
          </EmptyState>
        )}
        {data?.map((p) => (
          <KeyPoolCard key={p.id} provider={p} />
        ))}
      </div>
    </div>
  );
}
