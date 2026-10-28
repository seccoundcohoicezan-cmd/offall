"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { Button, ErrorNote, Input, Label } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

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
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-2">
            <Sparkles className="text-white" />
          </span>
          <div>
            <h1 className="text-xl font-bold">{isLogin ? "Masuk ke OFALL" : "Daftar OFALL"}</h1>
            <p className="text-sm text-muted">1 Chat • Banyak AI</p>
          </div>
        </div>
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
          <Button type="submit" disabled={busy}>
            {busy ? "Memproses..." : isLogin ? "Masuk" : "Buat akun"}
          </Button>
          <p className="text-center text-sm text-muted">
            {isLogin ? "Belum punya akun? " : "Sudah punya akun? "}
            <Link href={isLogin ? "/register" : "/login"} className="text-accent-2 underline">
              {isLogin ? "Daftar" : "Masuk"}
            </Link>
          </p>
        </div>
      </form>
    </main>
  );
}
