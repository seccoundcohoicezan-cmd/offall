"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Bot,
  Code2,
  MessageCircle,
  FileText,
  Infinity as InfinityIcon,
  Languages,
  ListTree,
  Loader2,
  MoreHorizontal,
  Paperclip,
  Pencil,
  Rocket,
  RotateCcw,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  Target,
  Trash2,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { del, get, patch, post } from "@/lib/api";
import { followJob } from "@/lib/sse";
import { useAgents, useMe, useModels } from "@/lib/hooks";
import { useUi } from "@/lib/store";
import { uuid } from "@/lib/uuid";
import type { Chat, Job, Message, Page } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/format";
import { cn } from "@/lib/cn";
import { AgentPanel } from "./AgentPanel";
import { ChatList } from "./ChatList";
import { MessageBubble } from "./MessageBubble";
import { ModelPanel, ModelSelect } from "./ModelPicker";
import { ProviderIcon } from "./ProviderIcon";
import { Sheet } from "./Sheet";
import { Badge, Button, Skeleton } from "./ui";
import { toast } from "./ui/toast";

const TOOLS = [
  { label: "Analisis", icon: BarChart3, prefix: "Analisis secara mendalam: " },
  { label: "Riset", icon: Search, prefix: "Riset dan rangkum temuan tentang: " },
  { label: "Ringkas", icon: FileText, prefix: "Ringkas poin pentingnya: " },
  { label: "Kode", icon: Code2, prefix: "Tulis kode untuk: " },
  { label: "Terjemah", icon: Languages, prefix: "Terjemahkan ke bahasa Inggris: " },
  { label: "Langkah", icon: ListTree, prefix: "Jelaskan langkah demi langkah: " },
];
const FEATURES = [
  { icon: Zap, title: "Multi-Model", text: "Akses semua model AI" },
  { icon: ShieldCheck, title: "Aman & Stabil", text: "Gateway terkelola" },
  { icon: Rocket, title: "Mudah Digunakan", text: "Untuk semua kebutuhan" },
];
const CHIPS = [
  { icon: Zap, label: "Cepat" },
  { icon: Target, label: "Akurat" },
  { icon: ShieldCheck, label: "Aman" },
  { icon: InfinityIcon, label: "Tanpa Batas" },
];
const MAX_FILE_CHARS = 15_000;

interface LiveJob {
  id: string;
  text: string;
  status: string;
  detail?: string;
}

function WelcomeHero() {
  return (
    <section className="hero-gradient relative hidden shrink-0 items-center gap-6 overflow-hidden rounded-3xl border border-accent/40 px-6 py-5 text-white neon-border lg:flex">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/logo-mark-wide.png"
        alt=""
        className="h-12 w-auto drop-shadow-[0_0_18px_rgba(192,132,252,0.8)]"
      />
      <div className="min-w-0">
        <p className="text-sm text-violet-200">Selamat datang di</p>
        <p className="text-3xl font-extrabold tracking-tight">OFALL</p>
        <p className="text-sm text-white/80">Satu platform, semua AI. Lebih produktif, lebih cerdas.</p>
      </div>
      <div className="ml-auto hidden gap-3 xl:flex">
        {FEATURES.map(({ icon: Icon, title, text }) => (
          <div
            key={title}
            className="flex items-center gap-3 rounded-2xl border border-white/15 bg-white/5 px-4 py-3 backdrop-blur"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10">
              <Icon size={20} />
            </span>
            <span>
              <span className="block text-sm font-semibold">{title}</span>
              <span className="block text-xs text-white/70">{text}</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function EmptyChat() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-3xl border border-border bg-surface/50 px-6 py-8 text-center">
      <span className="relative flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-accent/40 to-accent-2/20 text-accent-2 shadow-[0_0_40px_rgba(139,92,246,0.45)]">
        <Bot size={40} />
      </span>
      <p className="text-xl font-bold">Mulai percakapan</p>
      <p className="text-sm text-muted">
        Pilih model atau biarkan Auto memilihkan. Jawaban tetap diproses di server walau tab ditutup.
      </p>
      <div className="mt-1 flex flex-wrap justify-center gap-2">
        {CHIPS.map(({ icon: Icon, label }) => (
          <span
            key={label}
            className="flex items-center gap-1.5 rounded-xl border border-border bg-surface-2/60 px-3 py-1.5 text-xs"
          >
            <Icon size={13} className="text-accent-2" /> {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ChatView({ chatId }: { chatId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const agents = useAgents();
  const models = useModels();
  const { draftModel, setDraftModel } = useUi();
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [live, setLive] = useState<LiveJob | null>(null);
  const [draftAgent, setDraftAgent] = useState<string | null>(null);
  const [tab, setTab] = useState<"model" | "tools" | "file">("model");
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const following = useRef<string | null>(null);

  const chat = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => get<Chat>(`/chats/${chatId}`),
    enabled: !!chatId,
  });
  const messages = useQuery({
    queryKey: ["messages", chatId],
    queryFn: () => get<Page<Message>>(`/chats/${chatId}/messages?limit=200`),
    enabled: !!chatId,
  });
  const model = chat.data?.default_model ?? draftModel;
  const agentId = chatId ? (chat.data?.agent_id ?? null) : draftAgent;
  const modelInfo = models.data?.find((m) => m.id === model);

  const follow = useCallback(
    (jobId: string, initial = "") => {
      if (following.current === jobId) return () => undefined;
      following.current = jobId;
      const controller = new AbortController();
      setLive({ id: jobId, text: initial, status: "running" });
      let text = "";
      followJob(
        jobId,
        {
          onDelta: (t) => {
            text += t;
            setLive((l) => (l && l.id === jobId ? { ...l, text, status: "running", detail: undefined } : l));
          },
          onSnapshot: (t) => {
            text = t;
            setLive((l) => (l && l.id === jobId ? { ...l, text } : l));
          },
          onStatus: (d) =>
            setLive((l) =>
              l && l.id === jobId
                ? { ...l, status: String(d.status), detail: d.detail ? String(d.detail) : undefined }
                : l,
            ),
          onDone: async (d) => {
            following.current = null;
            if (d.status === "failed") toast.error(String(d.error ?? "Job gagal"));
            await Promise.all(
              [
                ["messages", chatId],
                ["providers"],
                ["usage"],
                ["jobs-last", chatId],
                ["jobs-active-count"],
              ].map((queryKey) => qc.invalidateQueries({ queryKey })),
            );
            setLive(null);
          },
        },
        controller.signal,
      );
      return () => {
        controller.abort();
        following.current = null;
      };
    },
    [chatId, qc],
  );

  // Re-attach to a job still running on the server (tab was closed / reopened).
  const lastJob = useQuery({
    queryKey: ["jobs-last", chatId],
    queryFn: () => get<Page<Job>>(`/jobs?chat_id=${chatId}&limit=1`),
    enabled: !!chatId,
  });
  const latest = lastJob.data?.items[0];
  const lastFailed: Job | null =
    latest && (latest.status === "failed" || (latest.status === "cancelled" && !latest.result_message_id))
      ? latest
      : null;
  useEffect(() => {
    const job = lastJob.data?.items[0];
    if (job && ["queued", "running", "waiting_quota"].includes(job.status))
      return follow(job.id, job.partial_output);
  }, [lastJob.data, follow]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.data, live?.text]);

  async function setModel(value: string) {
    if (!chatId) return setDraftModel(value);
    await patch(`/chats/${chatId}`, { default_model: value }).catch(toast.error);
    qc.invalidateQueries({ queryKey: ["chat", chatId] });
  }

  async function setAgent(id: string | null) {
    const agentModel = agents.data?.find((a) => a.id === id)?.default_model;
    const modelChange = agentModel && agentModel !== "auto" ? agentModel : undefined;
    if (!chatId) {
      setDraftAgent(id);
      if (modelChange) setDraftModel(modelChange);
      return;
    }
    const body = id ? { agent_id: id, default_model: modelChange } : { clear_agent: true };
    await patch(`/chats/${chatId}`, body).catch(toast.error);
    qc.invalidateQueries({ queryKey: ["chat", chatId] });
  }

  async function pickFile(f: File | undefined) {
    if (!f) return;
    if (f.size > 400_000) return toast.error("File terlalu besar (maks 400 KB teks).");
    const text = await f.text();
    if (text.includes("\u0000"))
      return toast.error("Hanya file teks (txt, md, csv, json, kode) yang didukung.");
    setFile({ name: f.name, text: text.slice(0, MAX_FILE_CHARS) });
    if (text.length > MAX_FILE_CHARS)
      toast.info(`File dipotong ke ${MAX_FILE_CHARS.toLocaleString("id-ID")} karakter pertama.`);
  }

  async function send() {
    const typed = input.trim();
    if ((!typed && !file) || sending) return;
    const content = file
      ? `${typed || "Tolong pelajari file berikut."}\n\nFile: ${file.name}\n\`\`\`\n${file.text}\n\`\`\``
      : typed;
    setSending(true);
    let createdId: string | null = null;
    try {
      let id = chatId;
      if (!id) {
        const created = await post<Chat>("/chats", { default_model: model, agent_id: draftAgent });
        id = createdId = created.id;
      }
      const res = await post<{ job_id: string }>(`/chats/${id}/messages`, {
        content,
        model,
        idempotency_key: uuid(),
      });
      setInput("");
      setFile(null);
      qc.invalidateQueries({ queryKey: ["chats"] });
      if (!chatId) {
        router.push(`/chat/${id}`);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["messages", chatId] });
      follow(res.job_id);
    } catch (e) {
      // Don't leave an empty "Chat baru" behind when the first message failed.
      if (createdId) await del(`/chats/${createdId}`).catch(() => undefined);
      toast.error(e);
    } finally {
      setSending(false);
    }
  }

  async function stop() {
    if (live) await post(`/jobs/${live.id}/cancel`).catch(toast.error);
  }

  async function retry() {
    if (!lastFailed) return;
    try {
      await post(`/jobs/${lastFailed.id}/retry`);
      await qc.invalidateQueries({ queryKey: ["jobs-last", chatId] });
    } catch (e) {
      toast.error(e);
    }
  }

  async function rename() {
    setMenuOpen(false);
    const title = prompt("Nama chat", chat.data?.title ?? "")?.trim();
    if (!chatId || !title) return;
    await patch(`/chats/${chatId}`, { title }).catch(toast.error);
    qc.invalidateQueries({ queryKey: ["chat", chatId] });
    qc.invalidateQueries({ queryKey: ["chats"] });
  }

  async function remove() {
    setMenuOpen(false);
    if (!chatId || !confirm("Hapus chat ini beserta seluruh riwayatnya?")) return;
    await del(`/chats/${chatId}`).catch(toast.error);
    qc.invalidateQueries({ queryKey: ["chats"] });
    router.push("/chat");
  }

  const initials = (me.data?.email ?? "?").slice(0, 2).toUpperCase();
  const items = messages.data?.items ?? [];
  const sidePanel = (
    <>
      <ModelPanel
        value={model}
        onChange={(v) => {
          setModel(v);
          setPanelOpen(false);
        }}
      />
      <AgentPanel value={agentId} onChange={setAgent} />
      <div className="rounded-3xl border border-border bg-surface/70 p-4 text-sm">
        <div className="flex items-center justify-between">
          <p className="font-semibold text-success">● Multi-Provider Active</p>
          <Link href="/providers" className="text-xs text-accent-2 hover:underline">
            Lihat semua ›
          </Link>
        </div>
        <p className="mt-1 text-xs text-muted">
          Key otomatis dirotasi saat limit. Jika semua habis, job menunggu kuota lalu lanjut sendiri.
        </p>
      </div>
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {!chatId && <WelcomeHero />}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[16rem_1fr] 2xl:grid-cols-[19rem_1fr_22rem]">
        <aside className="hidden min-h-0 rounded-3xl border border-border bg-surface/40 p-3 md:block">
          <ChatList />
        </aside>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-border bg-surface/40">
          <header className="flex items-start gap-3 border-b border-border p-3 sm:p-4">
            <span className="hidden h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-accent-2 text-white sm:flex">
              <Sparkles size={20} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted">AI Gateway</p>
              <h1 className="truncate text-base font-semibold sm:text-lg">
                {chat.data?.title ?? "Percakapan baru"}
              </h1>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="hidden sm:inline">
                  Model: {model === "auto" ? "Auto (Smart Routing)" : model}
                </span>
                <span className="inline-flex items-center gap-1 rounded-lg bg-accent/15 px-2 py-0.5 text-accent-2">
                  {modelInfo ? (
                    <ProviderIcon provider={modelInfo.provider} size={14} />
                  ) : (
                    <Sparkles size={12} />
                  )}
                  {modelInfo?.display_name ?? (model === "auto" ? "Auto" : model)}
                </span>
                {live && <Badge tone="accent">{STATUS_LABEL[live.status] ?? live.status}</Badge>}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setListOpen(true)}
                className="rounded-xl p-2 text-muted hover:bg-surface-2 md:hidden"
                aria-label="Daftar chat"
              >
                <MessageCircle size={20} />
              </button>
              <button
                onClick={() => setPanelOpen(true)}
                className="rounded-xl p-2 text-muted hover:bg-surface-2 xl:hidden"
                aria-label="Pilih model & agent"
              >
                <SlidersHorizontal size={20} />
              </button>
              {chatId && (
                <div className="relative">
                  <button
                    onClick={() => setMenuOpen(!menuOpen)}
                    className="rounded-xl p-2 text-muted hover:bg-surface-2"
                    aria-label="Opsi chat"
                    aria-expanded={menuOpen}
                  >
                    <MoreHorizontal size={20} />
                  </button>
                  {menuOpen && (
                    <div
                      role="menu"
                      className="absolute right-0 top-10 z-20 w-44 rounded-2xl border border-border bg-surface p-1.5 shadow-2xl"
                    >
                      <button
                        role="menuitem"
                        onClick={rename}
                        className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-surface-2"
                      >
                        <Pencil size={15} /> Ganti nama
                      </button>
                      <button
                        role="menuitem"
                        onClick={remove}
                        className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-danger hover:bg-danger/10"
                      >
                        <Trash2 size={15} /> Hapus chat
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5" aria-live="polite">
            <div className="flex flex-col gap-5">
              {chatId && messages.isLoading && [0, 1].map((i) => <Skeleton key={i} className="h-20" />)}
              {(!chatId || (!messages.isLoading && items.length === 0 && !live)) && <EmptyChat />}
              {items.map((m) => (
                <MessageBubble
                  key={m.id}
                  role={m.role}
                  content={m.content}
                  createdAt={m.created_at}
                  modelUsed={m.model_used}
                  tokensSaved={m.tokens_saved}
                  cached={m.cached}
                  memoriesUsed={m.memories_used}
                  initials={initials}
                />
              ))}
              {live && (
                <div data-testid="live-answer">
                  <MessageBubble role="assistant" content={live.text} streaming initials={initials} />
                  <div className="mt-2 flex items-center gap-2 pl-12 text-xs text-muted">
                    <Loader2 size={12} className="animate-spin" />
                    {live.status === "waiting_quota"
                      ? "Semua key sedang limit, job menunggu kuota pulih dan akan lanjut otomatis."
                      : (live.detail ?? "Diproses di server, aman untuk menutup tab.")}
                  </div>
                </div>
              )}
              {lastFailed && !live && (
                <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-danger/40 bg-danger/10 p-3 text-sm">
                  <Badge tone="danger">{STATUS_LABEL[lastFailed.status]}</Badge>
                  <span className="min-w-0 flex-1 break-words">
                    {lastFailed.error ?? "Jawaban dihentikan."}
                  </span>
                  <Button size="sm" variant="outline" onClick={retry}>
                    <RotateCcw size={14} /> Retry
                  </Button>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <form
            className="border-t border-border p-2.5 sm:p-3"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <div className="mb-2 flex gap-1" role="tablist" aria-label="Mode input">
              {(
                [
                  ["model", "Model", Sparkles],
                  ["tools", "Tools", Wrench],
                  ["file", "File", Paperclip],
                ] as const
              ).map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => (key === "file" && !file ? fileRef.current?.click() : setTab(key))}
                  className={cn(
                    "flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm transition",
                    tab === key
                      ? "bg-accent/20 text-text ring-1 ring-accent/60"
                      : "text-muted hover:text-text",
                  )}
                >
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>
            {tab === "tools" && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {TOOLS.map(({ label, icon: Icon, prefix }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => setInput((v) => (v.startsWith(prefix) ? v : prefix + v))}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-text"
                  >
                    <Icon size={13} /> {label}
                  </button>
                ))}
              </div>
            )}
            {file && (
              <div className="mb-2 flex items-center gap-2 rounded-xl border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs">
                <FileText size={14} className="text-accent-2" />
                <span className="min-w-0 flex-1 truncate">
                  {file.name} · {file.text.length.toLocaleString("id-ID")} karakter
                </span>
                <button
                  type="button"
                  onClick={() => setFile(null)}
                  aria-label="Lepas file"
                  className="text-muted hover:text-text"
                >
                  <X size={14} />
                </button>
              </div>
            )}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".txt,.md,.csv,.json,.py,.js,.ts,.tsx,.html,.css,.sql,.xml,.yaml,.yml,.log"
              onChange={(e) => {
                pickFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface-2/60 p-2 focus-within:border-accent">
              <label htmlFor="composer" className="sr-only">
                Tulis pesan
              </label>
              <textarea
                id="composer"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                maxLength={20000}
                placeholder="Tulis pesan Anda di sini..."
                className="max-h-40 min-h-[44px] flex-1 resize-none field-sizing-content bg-transparent px-1.5 py-1 text-[15px] placeholder:text-muted focus:outline-none"
              />
              {live ? (
                <button
                  type="button"
                  onClick={stop}
                  aria-label="Hentikan jawaban"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-danger/20 text-danger ring-1 ring-danger/50"
                >
                  <Square size={16} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={(!input.trim() && !file) || sending}
                  aria-label="Kirim pesan"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-white shadow-lg shadow-accent/40 transition hover:brightness-110 disabled:opacity-40"
                >
                  {sending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                </button>
              )}
            </div>
            <div className="mt-2 flex items-center gap-2 sm:flex-wrap">
              <button
                type="button"
                onClick={() => setModel("auto")}
                aria-pressed={model === "auto"}
                className={cn(
                  "hidden h-10 items-center gap-1.5 rounded-xl border px-3 text-sm sm:flex",
                  model === "auto"
                    ? "border-accent bg-accent/15 text-text"
                    : "border-border text-muted hover:text-text",
                )}
              >
                <Sparkles size={14} /> Auto (hemat)
              </button>
              <ModelSelect value={model} onChange={setModel} />
              <label htmlFor="agent-select" className="sr-only">
                Pilih agent
              </label>
              <select
                id="agent-select"
                value={agentId ?? ""}
                onChange={(e) => setAgent(e.target.value || null)}
                className="h-10 min-w-0 max-w-[10rem] flex-1 rounded-xl border border-border bg-surface-2 pl-2 pr-6 text-sm sm:flex-none 2xl:hidden"
              >
                <option value="">Tanpa agent</option>
                {agents.data
                  ?.filter((a) => a.is_enabled)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
              <div className="ml-auto hidden items-center gap-1 sm:flex">
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text"
                  aria-label="Lampirkan file teks"
                >
                  <Paperclip size={18} />
                </button>
                <button
                  type="button"
                  onClick={() => setInput((v) => `${v}${v ? "\n" : ""}\`\`\`\n\n\`\`\``)}
                  className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text"
                  aria-label="Sisipkan blok kode"
                >
                  <Code2 size={18} />
                </button>
                <Link
                  href="/settings"
                  className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text"
                  aria-label="Pengaturan chat"
                >
                  <Settings2 size={18} />
                </Link>
              </div>
            </div>
          </form>
        </section>

        <aside className="hidden min-h-0 flex-col gap-4 overflow-y-auto 2xl:flex">{sidePanel}</aside>
      </div>

      <Sheet open={listOpen} onClose={() => setListOpen(false)} title="Daftar chat">
        <div className="h-[60dvh]">
          <ChatList onNavigate={() => setListOpen(false)} />
        </div>
      </Sheet>
      <Sheet open={panelOpen} onClose={() => setPanelOpen(false)} title="Model & Agent">
        <div className="flex flex-col gap-4">{sidePanel}</div>
      </Sheet>
    </div>
  );
}
