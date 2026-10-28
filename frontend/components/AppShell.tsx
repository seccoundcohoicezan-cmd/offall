"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Bot,
  Boxes,
  FlaskConical,
  ListChecks,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Settings,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { useChats, useMe } from "@/lib/hooks";
import { get, post } from "@/lib/api";
import { useUi } from "@/lib/store";
import { cn } from "@/lib/cn";
import { formatTokens } from "@/lib/format";
import type { UsageSummary } from "@/lib/types";
import { ConnectedAccounts } from "./ConnectedAccounts";
import { Skeleton } from "./ui";

const NAV = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/providers", label: "Multi-Provider", icon: Boxes },
  { href: "/models", label: "Models", icon: FlaskConical },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/usage", label: "Analytics", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

function Logo() {
  return (
    <Link href="/chat" className="flex items-center gap-3">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-2 shadow-lg shadow-accent/40">
        <Sparkles size={20} className="text-white" />
      </span>
      <span className="text-xl font-extrabold tracking-tight">
        OFALL<span className="text-accent-2">.</span>
      </span>
      <span className="hidden text-sm text-muted xl:inline">AI Gateway & Agent Multi-Provider</span>
    </Link>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const chats = useChats();
  return (
    <nav aria-label="Navigasi utama" className="flex flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition",
              active
                ? "bg-gradient-to-r from-accent/40 to-accent/10 text-text neon-border"
                : "text-muted hover:bg-surface-2 hover:text-text",
            )}
          >
            <Icon size={20} />
            <span className="flex-1">{label}</span>
            {href === "/chat" && chats.data && (
              <span className="rounded-full bg-accent/30 px-2 text-xs text-text">{chats.data.total}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const { theme, setTheme, navOpen, setNavOpen } = useUi();
  const usage = useQuery({
    queryKey: ["usage", 1],
    queryFn: () => get<UsageSummary>("/usage/summary?days=1"),
    enabled: !!me.data,
  });

  useEffect(() => {
    if (me.isError) router.replace("/login");
  }, [me.isError, router]);

  async function logout() {
    await post("/auth/logout").catch(() => undefined);
    qc.clear();
    router.replace("/login");
  }

  if (me.isLoading || me.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy>
        <Skeleton className="h-10 w-48" />
      </div>
    );
  }

  const initials = (me.data?.email ?? "?").slice(0, 2).toUpperCase();
  const today = (usage.data?.total.tokens_in ?? 0) + (usage.data?.total.tokens_out ?? 0);
  const saved = usage.data?.total.tokens_saved ?? 0;

  const sidebar = (
    <div className="flex h-full flex-col gap-4">
      <Nav onNavigate={() => setNavOpen(false)} />
      <ConnectedAccounts />
      <div className="mt-auto flex items-center gap-3 rounded-2xl border border-border bg-surface/70 p-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-sm font-semibold">
          {initials}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{me.data?.email}</p>
          <p className="text-xs text-muted">{me.data?.role === "admin" ? "Admin" : "Member"}</p>
        </div>
        <button onClick={logout} aria-label="Keluar" className="text-muted hover:text-text">
          <LogOut size={18} />
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-bg/80 px-4 backdrop-blur">
        <button
          className="lg:hidden"
          onClick={() => setNavOpen(!navOpen)}
          aria-label="Buka menu"
          aria-expanded={navOpen}
        >
          {navOpen ? <X /> : <Menu />}
        </button>
        <Logo />
        <div className="mx-auto hidden items-center gap-3 rounded-2xl border border-accent/60 bg-gradient-to-r from-accent/25 to-accent-2/10 px-5 py-1.5 neon-border md:flex">
          <Sparkles size={18} className="text-accent-2" />
          <div className="leading-tight">
            <p className="text-sm font-semibold">1 Chat • Banyak AI</p>
            <p className="text-[11px] text-muted">
              Satu percakapan, akses berbagai model AI lewat AI Gateway.
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div
            className="hidden rounded-xl border border-border bg-surface px-3 py-1 text-xs sm:block"
            title="Token hari ini / token dihemat"
          >
            <span className="font-semibold">{formatTokens(today)}</span> token hari ini ·{" "}
            <span className="text-success">{formatTokens(saved)} hemat</span>
          </div>
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Mode terang" : "Mode gelap"}
            className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text"
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-xs font-bold text-white">
            {initials}
          </span>
        </div>
      </header>
      <div className="flex">
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-72 shrink-0 overflow-y-auto border-r border-border p-4 lg:block">
          {sidebar}
        </aside>
        {navOpen && (
          <div className="fixed inset-0 top-16 z-20 bg-bg/95 p-4 lg:hidden" role="dialog" aria-label="Menu">
            {sidebar}
          </div>
        )}
        <main className="min-w-0 flex-1 p-3 sm:p-5">{children}</main>
      </div>
    </div>
  );
}
