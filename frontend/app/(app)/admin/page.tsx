"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Search, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { del, get, patch, post } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { AdminUser, Page } from "@/lib/types";
import { formatTokens, timeAgo } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
  Switch,
} from "@/components/ui";
import { toast } from "@/components/ui/toast";

const PAGE = 50;

export default function AdminPage() {
  const me = useMe();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState({ email: "", password: "", display_name: "", role: "user" });
  const [busy, setBusy] = useState(false);
  const isAdmin = me.data?.role === "admin";

  const users = useQuery({
    queryKey: ["admin-users", q, offset],
    queryFn: () =>
      get<Page<AdminUser>>(`/admin/users?limit=${PAGE}&offset=${offset}&q=${encodeURIComponent(q)}`),
    enabled: isAdmin,
  });
  const instance = useQuery({
    queryKey: ["admin-settings"],
    queryFn: () => get<{ registration_open: boolean }>("/admin/settings"),
    enabled: isAdmin,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-users"] });

  if (me.data && !isAdmin) {
    return (
      <EmptyState icon={<ShieldCheck />} title="Khusus admin">
        Halaman ini hanya untuk pemilik/admin OFALL.
      </EmptyState>
    );
  }

  async function run(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      if (done) toast.success(done);
      refresh();
    } catch (e) {
      toast.error(e);
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await run(() => post("/admin/users", form), `Akun ${form.email} dibuat`);
    setForm({ email: "", password: "", display_name: "", role: "user" });
    setBusy(false);
  }

  function resetPassword(u: AdminUser) {
    const pw = prompt(`Password baru untuk ${u.email} (min. 8 karakter)`);
    if (!pw) return;
    if (pw.length < 8) return toast.error("Password minimal 8 karakter.");
    run(() => patch(`/admin/users/${u.id}`, { password: pw }), "Password diganti, sesi lama user dicabut");
  }

  async function toggleRegistration(open: boolean) {
    try {
      await patch("/admin/settings", { registration_open: open });
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
      toast.success(open ? "Pendaftaran dibuka" : "Pendaftaran ditutup, hanya admin yang bisa membuat akun");
    } catch (e) {
      toast.error(e);
    }
  }

  const list = users.data?.items ?? [];
  const active = list.filter((u) => u.is_active).length;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Manajemen User"
        subtitle="Hanya kamu (admin) yang menentukan siapa boleh memakai OFALL."
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Card>
          <p className="text-xs text-muted">Total user</p>
          <p className="text-2xl font-bold">{users.data?.total ?? "–"}</p>
        </Card>
        <Card>
          <p className="text-xs text-muted">Aktif (halaman ini)</p>
          <p className="text-2xl font-bold">{users.data ? active : "–"}</p>
        </Card>
        <Card className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium">Pendaftaran mandiri</p>
            <p className="text-xs text-muted">
              {instance.data?.registration_open ? "Siapa pun bisa daftar" : "Tertutup — akun dibuat admin"}
            </p>
          </div>
          {instance.data && (
            <Switch
              label="Pendaftaran mandiri"
              checked={instance.data.registration_open}
              onChange={toggleRegistration}
            />
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card>
          <form onSubmit={create} className="flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-semibold">
              <UserPlus size={18} /> Tambah user
            </h2>
            <div>
              <Label htmlFor="new-email">Email</Label>
              <Input
                id="new-email"
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="new-name" hint="(opsional)">
                Nama
              </Label>
              <Input
                id="new-name"
                maxLength={80}
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="new-pass" hint="(min. 8)">
                Password awal
              </Label>
              <Input
                id="new-pass"
                type="text"
                autoComplete="off"
                required
                minLength={8}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="new-role">Peran</Label>
              <Select
                id="new-role"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </Select>
            </div>
            <Button type="submit" disabled={busy}>
              <UserPlus size={16} /> Buat akun
            </Button>
            <p className="text-xs text-muted">
              Kirim email & password ke orangnya lewat jalur pribadi. Mereka bisa langsung login.
            </p>
          </form>
        </Card>

        <div className="flex min-w-0 flex-col gap-3">
          <label className="relative">
            <span className="sr-only">Cari user</span>
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <Input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
              placeholder="Cari email atau nama..."
              className="pl-9"
            />
          </label>
          <ErrorNote error={users.error} />
          {users.isLoading && <Skeleton className="h-40" />}
          {users.data && list.length === 0 && <EmptyState icon={<Users />} title="Tidak ada user" />}
          <ul className="flex flex-col gap-2">
            {list.map((u) => {
              const self = u.id === me.data?.id;
              return (
                <li
                  key={u.id}
                  className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface/70 p-3"
                  data-testid="user-row"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-xs font-bold text-white">
                    {u.email.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-[12rem] flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      <span className="truncate">{u.display_name || u.email}</span>
                      {u.role === "admin" && (
                        <Badge tone="accent">
                          <ShieldCheck size={11} /> Admin
                        </Badge>
                      )}
                      {!u.is_active && <Badge tone="danger">Nonaktif</Badge>}
                      {self && <Badge>Kamu</Badge>}
                    </p>
                    <p className="truncate text-xs text-muted">
                      {u.display_name ? `${u.email} · ` : ""}login {timeAgo(u.last_login_at)} · {u.chats} chat
                      · {u.providers} provider · {formatTokens(u.tokens_30d)} token/30h
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      aria-label={`Peran ${u.email}`}
                      className="h-9 w-28"
                      value={u.role}
                      onChange={(e) =>
                        run(() => patch(`/admin/users/${u.id}`, { role: e.target.value }), "Peran diperbarui")
                      }
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </Select>
                    <Switch
                      label={`Aktifkan ${u.email}`}
                      checked={u.is_active}
                      disabled={self}
                      onChange={(on) =>
                        run(
                          () => patch(`/admin/users/${u.id}`, { is_active: on }),
                          on ? "User diaktifkan" : "User dinonaktifkan & sesinya dicabut",
                        )
                      }
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => resetPassword(u)}
                      aria-label={`Reset password ${u.email}`}
                    >
                      <KeyRound size={15} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={self}
                      aria-label={`Hapus ${u.email}`}
                      onClick={() =>
                        confirm(
                          `Hapus ${u.email} beserta semua chat, key, dan agent-nya? Tidak bisa dibatalkan.`,
                        ) && run(() => del(`/admin/users/${u.id}`), "User dihapus")
                      }
                    >
                      <Trash2 size={15} />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
          {users.data && users.data.total > PAGE && (
            <div className="flex items-center justify-between text-sm">
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Sebelumnya
              </Button>
              <span className="text-muted">
                {offset + 1}–{Math.min(offset + PAGE, users.data.total)} dari {users.data.total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + PAGE >= users.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Berikutnya
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
