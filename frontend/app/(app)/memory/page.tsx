"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Check,
  History,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  ScrollText,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { del, get, patch, post } from "@/lib/api";
import type { AuditEntry, HistoryHit, Memory, MemoryKind, MemoryProfile, Page } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  PageHeader,
  Select,
  Skeleton,
} from "@/components/ui";
import { toast } from "@/components/ui/toast";

const KIND_LABEL: Record<MemoryKind, string> = {
  fact: "Fakta",
  preference: "Preferensi",
  context: "Konteks",
};
const TABS = [
  { key: "memories", label: "Memori", icon: Brain },
  { key: "history", label: "Cari riwayat", icon: History },
  { key: "audit", label: "Log aktivitas", icon: ScrollText },
] as const;

function MemoryRow({ m, onChange }: { m: Memory; onChange: () => void }) {
  async function run(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      if (done) toast.success(done);
      onChange();
    } catch (e) {
      toast.error(e);
    }
  }
  function edit() {
    const content = prompt("Ubah memori", m.content)?.trim();
    if (content && content !== m.content)
      run(() => patch(`/memories/${m.id}`, { content }), "Memori diperbarui");
  }
  return (
    <li
      className="flex flex-wrap items-start gap-3 rounded-2xl border border-border bg-surface/70 p-3"
      data-testid="memory-row"
    >
      <div className="min-w-[12rem] flex-1">
        <p className="text-sm">{m.content}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <Badge tone="accent">{KIND_LABEL[m.kind] ?? m.kind}</Badge>
          <Badge>{m.source === "auto" ? "dipelajari otomatis" : "ditambah manual"}</Badge>
          {m.pinned && <Badge tone="warning">disematkan</Badge>}
          <span>
            dipakai {m.use_count}× · {timeAgo(m.created_at)}
          </span>
          {m.source_chat_id && (
            <Link href={`/chat/${m.source_chat_id}`} className="text-accent-2 hover:underline">
              dari chat
            </Link>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {m.status === "pending" ? (
          <>
            <Button
              size="sm"
              onClick={() => run(() => patch(`/memories/${m.id}`, { status: "active" }), "Memori disetujui")}
            >
              <Check size={14} /> Setujui
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => run(() => patch(`/memories/${m.id}`, { status: "rejected" }), "Memori ditolak")}
            >
              <X size={14} /> Tolak
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              variant="ghost"
              aria-label={m.pinned ? "Lepas sematan" : "Sematkan (selalu dipakai)"}
              title={m.pinned ? "Lepas sematan" : "Sematkan: selalu dipakai di setiap chat"}
              onClick={() => run(() => patch(`/memories/${m.id}`, { pinned: !m.pinned }))}
            >
              {m.pinned ? <PinOff size={14} /> : <Pin size={14} />}
            </Button>
            <Button size="sm" variant="ghost" aria-label="Ubah memori" onClick={edit}>
              <Pencil size={14} />
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="ghost"
          aria-label="Hapus memori"
          onClick={() =>
            confirm("Hapus memori ini?") && run(() => del(`/memories/${m.id}`), "Memori dihapus")
          }
        >
          <Trash2 size={14} />
        </Button>
      </div>
    </li>
  );
}

function MemoriesTab() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const profile = useQuery({
    queryKey: ["memory-profile"],
    queryFn: () => get<MemoryProfile>("/memories/profile"),
  });
  const pending = useQuery({
    queryKey: ["memories", "pending"],
    queryFn: () => get<Page<Memory>>("/memories?status=pending"),
  });
  const list = useQuery({
    queryKey: ["memories", "active", q],
    queryFn: () => get<Page<Memory>>(`/memories?status=active&q=${encodeURIComponent(q)}`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["memories"] });
    qc.invalidateQueries({ queryKey: ["memory-profile"] });
  };

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post("/memories", { content, kind });
      setContent("");
      toast.success("Memori disimpan");
      refresh();
    } catch (err) {
      toast.error(err);
    }
  }

  async function rebuild() {
    try {
      await post("/memories/profile/rebuild");
      toast.info("Profil sedang disusun ulang di server, cek lagi sebentar.");
      setTimeout(refresh, 6000);
    } catch (err) {
      toast.error(err);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="hero-gradient border-accent/40 text-white">
        <div className="flex flex-wrap items-start gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10">
            <Brain size={22} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-violet-200">Model pengguna (yang AI ketahui tentang kamu)</p>
            {profile.isLoading ? (
              <Skeleton className="mt-2 h-10" />
            ) : (
              <p className="mt-1 text-[15px] leading-relaxed">
                {profile.data?.summary ||
                  "Belum ada profil. Profil terbentuk otomatis setelah AI mempelajari beberapa hal tentangmu."}
              </p>
            )}
            <p className="mt-2 text-xs text-white/70">
              {profile.data?.active ?? 0} memori aktif · {profile.data?.pending ?? 0} menunggu review
              {profile.data?.updated_at ? ` · diperbarui ${timeAgo(profile.data.updated_at)}` : ""}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={rebuild}
            className="border-white/30 bg-white/10 text-white hover:bg-white/20"
          >
            <RefreshCw size={14} /> Susun ulang
          </Button>
        </div>
      </Card>

      <Card>
        <form onSubmit={add} className="flex flex-wrap items-end gap-2">
          <label className="min-w-[14rem] flex-1">
            <span className="mb-1 block text-sm font-medium">Ajari AI sesuatu tentangmu</span>
            <Input
              value={content}
              onChange={(e) => setContent(e.target.value)}
              minLength={3}
              maxLength={300}
              required
              placeholder="Contoh: Saya dosen DKV, suka jawaban singkat dengan poin-poin."
            />
          </label>
          <Select
            aria-label="Jenis memori"
            className="w-36"
            value={kind}
            onChange={(e) => setKind(e.target.value as MemoryKind)}
          >
            <option value="fact">Fakta</option>
            <option value="preference">Preferensi</option>
            <option value="context">Konteks</option>
          </Select>
          <Button type="submit">
            <Plus size={16} /> Simpan
          </Button>
        </form>
        <p className="mt-2 text-xs text-muted">
          Tip: di chat kamu juga bisa menulis &quot;ingat bahwa ...&quot;, AI akan menyimpannya otomatis.
        </p>
      </Card>

      {!!pending.data?.items.length && (
        <section>
          <h2 className="mb-2 font-semibold">Menunggu review ({pending.data.total})</h2>
          <ul className="flex flex-col gap-2">
            {pending.data.items.map((m) => (
              <MemoryRow key={m.id} m={m} onChange={refresh} />
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Memori aktif ({list.data?.total ?? 0})</h2>
          <label className="relative w-full sm:w-72">
            <span className="sr-only">Cari memori</span>
            <Search
              size={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Cari memori..."
              className="pl-9"
            />
          </label>
        </div>
        <ErrorNote error={list.error} />
        {list.isLoading && <Skeleton className="h-24" />}
        {list.data?.items.length === 0 && (
          <EmptyState icon={<Brain />} title="Belum ada memori">
            Ngobrol seperti biasa; fakta & preferensi penting akan diingat otomatis.
          </EmptyState>
        )}
        <ul className="flex flex-col gap-2">
          {list.data?.items.map((m) => (
            <MemoryRow key={m.id} m={m} onChange={refresh} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function HistoryTab() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const hits = useQuery({
    queryKey: ["history-search", term],
    queryFn: () => get<HistoryHit[]>(`/search/messages?q=${encodeURIComponent(term)}`),
    enabled: term.length >= 2,
  });
  return (
    <div className="flex flex-col gap-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setTerm(q.trim());
        }}
        className="flex gap-2"
      >
        <label className="relative flex-1">
          <span className="sr-only">Cari di semua percakapan</span>
          <Search
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='Contoh: "kubernetes", "anggaran PkM"...'
            className="pl-9"
          />
        </label>
        <Button type="submit" disabled={q.trim().length < 2}>
          Cari
        </Button>
      </form>
      <p className="text-xs text-muted">
        Di chat, kalimat seperti &quot;kita pernah bahas ...&quot; membuat AI otomatis mencari cuplikan dari
        percakapan lama.
      </p>
      {hits.isFetching && <Skeleton className="h-20" />}
      <ErrorNote error={hits.error} />
      {hits.data?.length === 0 && <EmptyState icon={<History />} title="Tidak ditemukan" />}
      <ul className="flex flex-col gap-2">
        {hits.data?.map((h) => (
          <li key={h.message_id}>
            <Link
              href={`/chat/${h.chat_id}`}
              className="block rounded-2xl border border-border bg-surface/70 p-3 hover:border-accent/60"
              data-testid="history-hit"
            >
              <p className="flex items-center gap-2 text-sm font-medium">
                {h.chat_title}
                <Badge>{h.role === "user" ? "kamu" : "AI"}</Badge>
                <span className="text-xs font-normal text-muted">{timeAgo(h.created_at)}</span>
              </p>
              <p className="mt-1 text-sm text-muted">{h.snippet}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AuditTab() {
  const [offset, setOffset] = useState(0);
  const logs = useQuery({
    queryKey: ["audit", offset],
    queryFn: () => get<Page<AuditEntry>>(`/audit?limit=50&offset=${offset}`),
  });
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted">
        Semua perubahan yang dilakukan AI (agent), kamu, atau admin pada akunmu tercatat di sini.
      </p>
      {logs.isLoading && <Skeleton className="h-32" />}
      {logs.data?.items.length === 0 && <EmptyState icon={<ScrollText />} title="Belum ada aktivitas" />}
      <ul className="divide-y divide-border rounded-2xl border border-border bg-surface/70">
        {logs.data?.items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
            <Badge tone={a.actor === "agent" ? "accent" : a.actor === "admin" ? "warning" : "neutral"}>
              {a.actor}
            </Badge>
            <span className="font-mono text-xs">{a.action}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted">
              {Object.entries(a.detail)
                .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
                .join(" · ")}
            </span>
            <span className="text-xs text-muted">{timeAgo(a.created_at)}</span>
          </li>
        ))}
      </ul>
      {logs.data && logs.data.total > 50 && (
        <div className="flex justify-between text-sm">
          <Button
            size="sm"
            variant="outline"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Sebelumnya
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={offset + 50 >= logs.data.total}
            onClick={() => setOffset(offset + 50)}
          >
            Berikutnya
          </Button>
        </div>
      )}
    </div>
  );
}

export default function MemoryPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("memories");
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Memory"
        subtitle="Yang diingat AI tentangmu lintas chat, pencarian riwayat, dan log aktivitas."
      />
      <div className="mb-4 flex gap-1 overflow-x-auto" role="tablist">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-sm",
              tab === key ? "bg-accent/20 ring-1 ring-accent/60" : "text-muted hover:text-text",
            )}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>
      {tab === "memories" && <MemoriesTab />}
      {tab === "history" && <HistoryTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}
