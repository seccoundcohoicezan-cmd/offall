"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Code2, FileText, Loader2, RotateCcw, Search, Send, Sparkles, Square } from "lucide-react";
import { get, patch, post } from "@/lib/api";
import { followJob } from "@/lib/sse";
import { useAgents, useMe } from "@/lib/hooks";
import { useUi } from "@/lib/store";
import type { Chat, Job, Message, Page } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/format";
import { AgentPanel } from "./AgentPanel";
import { ChatList } from "./ChatList";
import { MessageBubble } from "./MessageBubble";
import { ModelPanel, ModelSelect } from "./ModelPicker";
import { Badge, Button, EmptyState, Skeleton } from "./ui";
import { toast } from "./ui/toast";

const QUICK = [
  { label: "Analysis", icon: BarChart3, prefix: "Analisis secara mendalam: " },
  { label: "Research", icon: Search, prefix: "Riset dan rangkum temuan tentang: " },
  { label: "Summarize", icon: FileText, prefix: "Ringkas poin pentingnya: " },
  { label: "Code", icon: Code2, prefix: "Tulis kode untuk: " },
];

interface LiveJob {
  id: string;
  text: string;
  status: string;
  detail?: string;
}

export function ChatView({ chatId }: { chatId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const agents = useAgents();
  const { draftModel, setDraftModel } = useUi();
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [live, setLive] = useState<LiveJob | null>(null);
  const [draftAgent, setDraftAgent] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
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
            await Promise.all([
              qc.invalidateQueries({ queryKey: ["messages", chatId] }),
              qc.invalidateQueries({ queryKey: ["providers"] }),
              qc.invalidateQueries({ queryKey: ["usage"] }),
              qc.invalidateQueries({ queryKey: ["jobs-last", chatId] }),
            ]);
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
    if (!job) return;
    if (["queued", "running", "waiting_quota"].includes(job.status))
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

  async function send() {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    try {
      let id = chatId;
      if (!id) {
        const created = await post<Chat>("/chats", { default_model: model, agent_id: draftAgent });
        id = created.id;
      }
      const res = await post<{ job_id: string }>(`/chats/${id}/messages`, {
        content,
        model,
        idempotency_key: crypto.randomUUID(),
      });
      setInput("");
      qc.invalidateQueries({ queryKey: ["chats"] });
      if (!chatId) {
        router.push(`/chat/${id}`);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["messages", chatId] });
      follow(res.job_id);
    } catch (e) {
      toast.error(e);
    } finally {
      setSending(false);
    }
  }

  async function stop() {
    if (!live) return;
    await post(`/jobs/${live.id}/cancel`).catch(toast.error);
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

  const initials = (me.data?.email ?? "?").slice(0, 2).toUpperCase();
  const items = messages.data?.items ?? [];

  return (
    <div className="grid h-[calc(100vh-6.5rem)] grid-cols-1 gap-4 md:grid-cols-[14rem_1fr] xl:grid-cols-[14rem_1fr_20rem]">
      <aside className="hidden md:block">
        <ChatList />
      </aside>

      <section className="flex min-h-0 flex-col gap-3">
        <details className="rounded-2xl border border-border bg-surface/70 p-2 md:hidden">
          <summary className="cursor-pointer px-1 text-sm font-medium">Daftar chat</summary>
          <div className="mt-2 max-h-72">
            <ChatList />
          </div>
        </details>
        <div className="hero-gradient relative overflow-hidden rounded-2xl border border-accent/50 p-4 text-white neon-border">
          <p className="flex items-center gap-1.5 text-sm text-white/80">
            <Sparkles size={14} /> AI Gateway
          </p>
          <h2 className="mt-1 truncate text-lg font-semibold sm:text-xl">
            {chat.data?.title ?? "Percakapan baru"}
          </h2>
          <p className="mt-1 text-sm text-white/75">
            Model:{" "}
            <span className="font-medium text-white">
              {model === "auto" ? "Auto (Smart Routing)" : model}
            </span>
            {live && <span className="ml-2">· {STATUS_LABEL[live.status] ?? live.status}</span>}
          </p>
        </div>

        <div
          className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-border bg-surface/40 p-3 sm:p-5"
          aria-live="polite"
        >
          <div className="flex flex-col gap-5">
            {chatId && messages.isLoading && [0, 1].map((i) => <Skeleton key={i} className="h-20" />)}
            {!chatId && (
              <EmptyState icon={<Sparkles />} title="Mulai percakapan">
                Pilih model atau biarkan <b>Auto</b> memilihkan. Jawaban tetap diproses di server walau tab
                ditutup.
              </EmptyState>
            )}
            {chatId && !messages.isLoading && items.length === 0 && !live && (
              <EmptyState title="Belum ada pesan" />
            )}
            {items.map((m) => (
              <MessageBubble
                key={m.id}
                role={m.role}
                content={m.content}
                createdAt={m.created_at}
                modelUsed={m.model_used}
                tokensSaved={m.tokens_saved}
                cached={m.cached}
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
              <div className="flex items-center gap-3 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm">
                <Badge tone="danger">{STATUS_LABEL[lastFailed.status]}</Badge>
                <span className="flex-1">{lastFailed.error ?? "Jawaban dihentikan."}</span>
                <Button size="sm" variant="outline" onClick={retry}>
                  <RotateCcw size={14} /> Retry
                </Button>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <form
          className="rounded-2xl border border-border bg-surface/80 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <label htmlFor="composer" className="sr-only">
            Tulis pesan
          </label>
          <textarea
            id="composer"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            maxLength={20000}
            placeholder="Tulis pesan atau minta analisis lebih lanjut..."
            className="w-full resize-none bg-transparent text-[15px] placeholder:text-muted focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {QUICK.map(({ label, icon: Icon, prefix }) => (
              <button
                key={label}
                type="button"
                onClick={() => setInput((v) => (v.startsWith(prefix) ? v : prefix + v))}
                className="hidden items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-text sm:flex"
              >
                <Icon size={13} /> {label}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <label htmlFor="agent-select" className="sr-only">
                Pilih agent
              </label>
              <select
                id="agent-select"
                value={agentId ?? ""}
                onChange={(e) => setAgent(e.target.value || null)}
                className="h-10 max-w-[9rem] rounded-xl border border-border bg-surface-2 pl-2 pr-6 text-sm xl:hidden"
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
              <ModelSelect value={model} onChange={setModel} />
              {live ? (
                <Button type="button" variant="danger" onClick={stop} aria-label="Hentikan jawaban">
                  <Square size={16} /> Stop
                </Button>
              ) : (
                <Button type="submit" disabled={!input.trim() || sending} aria-label="Kirim pesan">
                  {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </Button>
              )}
            </div>
          </div>
        </form>
      </section>

      <aside className="hidden flex-col gap-4 overflow-y-auto xl:flex">
        <ModelPanel value={model} onChange={setModel} />
        <AgentPanel value={agentId} onChange={setAgent} />
        <div className="rounded-2xl border border-border bg-surface/70 p-3 text-sm">
          <p className="font-semibold text-success">● Multi-Provider Active</p>
          <p className="mt-1 text-xs text-muted">
            Key otomatis dirotasi saat limit. Jika semua habis, job menunggu kuota lalu lanjut sendiri.
          </p>
        </div>
      </aside>
    </div>
  );
}
