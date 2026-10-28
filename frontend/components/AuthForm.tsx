"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import { Button, ErrorNote, Input, Label } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";
  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: () => get<{ registration_open: boolean }>("/auth/config"),
  });
  const closed = config.data?.registration_open === false;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post(`/auth/${mode}`, { email, password });
      qc.clear();
      router.replace("/chat");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-border bg-surface/80 p-6 neon-border backdrop-blur"
      >
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo-mark-wide.png"
            alt=""
            className="h-14 w-auto drop-shadow-[0_0_18px_rgba(139,92,246,0.6)]"
          />
          <p className="text-3xl font-extrabold tracking-tight">
            OFALL<span className="text-accent-2">.</span>
          </p>
          <p className="text-xs tracking-[0.25em] text-accent-2/80">AI GATEWAY · MULTI-PROVIDER</p>
          <h1 className="mt-2 text-lg font-semibold">{isLogin ? "Masuk ke akunmu" : "Buat akun baru"}</h1>
        </div>
        {!isLogin && closed && (
          <p
            role="alert"
            className="mb-4 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
          >
            Pendaftaran ditutup oleh admin. Minta akun ke admin OFALL.
          </p>
        )}
        <div className="flex flex-col gap-4">
          <div>
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="password" hint={isLogin ? undefined : "(min. 8 karakter)"}>
              Password
            </Label>
            <Input
              id="password"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <ErrorNote error={error} />
          <Button type="submit" disabled={busy || (!isLogin && closed)}>
            {busy ? "Memproses..." : isLogin ? "Masuk" : "Buat akun"}
          </Button>
          {!(isLogin && closed) && (
            <p className="text-center text-sm text-muted">
              {isLogin ? "Belum punya akun? " : "Sudah punya akun? "}
              <Link href={isLogin ? "/register" : "/login"} className="text-accent-2 underline">
                {isLogin ? "Daftar" : "Masuk"}
              </Link>
            </p>
          )}
        </div>
      </form>
    </main>
  );
}
