"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Bell,
  Bot,
  Boxes,
  ChevronDown,
  Database,
  ListChecks,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  X,
} from "lucide-react";
import { useChats, useMe } from "@/lib/hooks";
import { get, post } from "@/lib/api";
import { useUi } from "@/lib/store";
import { cn } from "@/lib/cn";
import { formatTokens } from "@/lib/format";
import type { Job, Page, UsageSummary } from "@/lib/types";
import { ConnectedAccounts } from "./ConnectedAccounts";
import { Logo } from "./Logo";
import { Skeleton } from "./ui";

const NAV = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/providers", label: "Multi-Provider", icon: Boxes },
  { href: "/models", label: "Models", icon: Database },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/usage", label: "Analytics", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];
const ADMIN_NAV = { href: "/admin", label: "Users", icon: Users };
const MOBILE_TABS = [NAV[0], NAV[1], NAV[2], NAV[5]];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Nav({ admin, onNavigate }: { admin: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const chats = useChats();
  const items = admin ? [...NAV, ADMIN_NAV] : NAV;
  return (
    <nav aria-label="Navigasi utama" className="flex flex-col gap-1.5">
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3.5 rounded-2xl px-4 py-3 text-[15px] transition",
              active
                ? "bg-gradient-to-r from-accent to-accent-2/80 font-medium text-white shadow-lg shadow-accent/30"
                : "text-muted hover:bg-surface-2 hover:text-text",
            )}
          >
            <Icon size={21} strokeWidth={1.8} />
            <span className="flex-1">{label}</span>
            {href === "/chat" && !!chats.data?.total && (
              <span
                className={cn("rounded-full px-2 text-xs", active ? "bg-white/25" : "bg-accent/25 text-text")}
              >
                {chats.data.total}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function UserMenu({ email, role, onLogout }: { email: string; role: string; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useUi();
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const initials = email.slice(0, 2).toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Menu akun"
        className="flex items-center gap-1.5 rounded-full p-0.5 hover:bg-surface-2"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-sm font-bold text-white shadow-lg shadow-accent/40">
          {initials}
        </span>
        <ChevronDown size={16} className="hidden text-muted sm:block" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-12 z-40 w-64 rounded-2xl border border-border bg-surface p-2 shadow-2xl"
        >
          <div className="border-b border-border px-3 pb-2 pt-1">
            <p className="truncate text-sm font-medium">{email}</p>
            <p className="flex items-center gap-1 text-xs text-muted">
              {role === "admin" && <ShieldCheck size={12} className="text-accent-2" />}
              {role === "admin" ? "Admin" : "Member"}
            </p>
          </div>
          <Link
            href="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="mt-1 flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-surface-2"
          >
            <Settings size={16} /> Pengaturan
          </Link>
          {role === "admin" && (
            <Link
              href="/admin"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-surface-2"
            >
              <Users size={16} /> Manajemen user
            </Link>
          )}
          <button
            role="menuitem"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-surface-2"
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}{" "}
            {theme === "dark" ? "Mode terang" : "Mode gelap"}
          </button>
          <button
            role="menuitem"
            onClick={onLogout}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-danger hover:bg-danger/10"
          >
            <LogOut size={16} /> Keluar
          </button>
        </div>
      )}
    </div>
  );
}

function JobBell() {
  const jobs = useQuery({
    queryKey: ["jobs-active-count"],
    queryFn: () => get<Page<Job>>("/jobs?active=true&limit=1"),
    refetchInterval: 15_000,
  });
  const n = jobs.data?.total ?? 0;
  return (
    <Link
      href="/jobs"
      aria-label={n ? `${n} job berjalan` : "Jobs"}
      className="relative rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text"
    >
      <Bell size={20} />
      {n > 0 && (
        <span className="absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-danger ring-2 ring-bg" />
      )}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
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

  if (me.isLoading || me.isError || !me.data) {
    return (
      <div className="flex h-dvh items-center justify-center" aria-busy>
        <Skeleton className="h-10 w-48" />
      </div>
    );
  }

  const admin = me.data.role === "admin";
  const today = (usage.data?.total.tokens_in ?? 0) + (usage.data?.total.tokens_out ?? 0);
  const saved = usage.data?.total.tokens_saved ?? 0;

  const sidebar = (
    <div className="flex h-full flex-col gap-5">
      <Nav admin={admin} onNavigate={() => setNavOpen(false)} />
      <ConnectedAccounts />
    </div>
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="z-30 flex h-16 shrink-0 items-center gap-3 border-b border-border bg-bg/80 px-3 backdrop-blur sm:h-[72px] sm:px-5">
        <button
          className="rounded-xl p-2 lg:hidden"
          onClick={() => setNavOpen(!navOpen)}
          aria-label="Buka menu"
          aria-expanded={navOpen}
        >
          {navOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
        <Logo />
        <span className="ml-3 hidden text-[15px] text-muted xl:inline">
          AI Gateway & Agent Multi-Provider
        </span>
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <div
            className="mr-1 hidden rounded-xl border border-border bg-surface px-3 py-1.5 text-xs md:block"
            title="Token hari ini / token dihemat"
          >
            <span className="font-semibold">{formatTokens(today)}</span> token hari ini ·{" "}
            <span className="text-success">{formatTokens(saved)} hemat</span>
          </div>
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Mode terang" : "Mode gelap"}
            className="hidden rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-text sm:block"
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <JobBell />
          <UserMenu email={me.data.email} role={me.data.role} onLogout={logout} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[300px] shrink-0 overflow-y-auto border-r border-border p-4 lg:block">
          {sidebar}
        </aside>
        {navOpen && (
          <div className="fixed inset-0 top-16 z-40 lg:hidden" role="dialog" aria-label="Menu">
            <button
              className="absolute inset-0 bg-black/60"
              aria-label="Tutup menu"
              onClick={() => setNavOpen(false)}
            />
            <div className="relative h-full w-[85%] max-w-xs overflow-y-auto border-r border-border bg-bg p-4">
              {sidebar}
            </div>
          </div>
        )}
        <main className="min-w-0 flex-1 overflow-y-auto p-3 pb-24 sm:p-5 lg:pb-5">{children}</main>
      </div>

      <nav
        aria-label="Navigasi bawah"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {MOBILE_TABS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={isActive(pathname, href) ? "page" : undefined}
            className={cn(
              "flex flex-col items-center gap-0.5 py-2 text-[11px]",
              isActive(pathname, href) ? "text-accent-2" : "text-muted",
            )}
          >
            <Icon size={21} />
            {label === "Multi-Provider" ? "Provider" : label}
          </Link>
        ))}
        <button
          onClick={() => setNavOpen(true)}
          className="flex flex-col items-center gap-0.5 py-2 text-[11px] text-muted"
        >
          <Menu size={21} /> Lainnya
        </button>
      </nav>
    </div>
  );
}
