"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { patch, post } from "@/lib/api";
import { useSettings } from "@/lib/hooks";
import type { SaveMode, UserSettings } from "@/lib/types";
import {
  Button,
  Card,
  ErrorNote,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
  Switch,
  Textarea,
} from "@/components/ui";
import { toast } from "@/components/ui/toast";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const qc = useQueryClient();
  const [edited, setForm] = useState<UserSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const form = edited ?? data ?? null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const { vapid_public_key: _v, telegram_enabled: _t, ...body } = form;
      void _v;
      void _t;
      await patch("/settings", body);
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Pengaturan disimpan");
    } catch (err) {
      toast.error(err);
    } finally {
      setSaving(false);
    }
  }

  async function enablePush() {
    if (!form?.vapid_public_key) return toast.error("Web Push belum dikonfigurasi di server (VAPID).");
    if (!("serviceWorker" in navigator) || !("PushManager" in window))
      return toast.error("Browser ini tidak mendukung Web Push.");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return toast.error("Izin notifikasi ditolak.");
      const reg = await navigator.serviceWorker.register("/sw.js");
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(form.vapid_public_key),
      });
      const json = sub.toJSON();
      await post("/push/subscribe", { endpoint: json.endpoint, keys: json.keys });
      setForm({ ...form, notify_webpush: true });
      await patch("/settings", { notify_webpush: true });
      toast.success("Notifikasi browser aktif");
    } catch (err) {
      toast.error(err);
    }
  }

  if (isLoading || !form) return <Skeleton className="mx-auto h-96 max-w-3xl" />;
  const set = <K extends keyof UserSettings>(k: K, v: UserSettings[K]) => setForm({ ...form, [k]: v });

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Settings"
        subtitle="Mode hemat token, batas jawaban, fallback, notifikasi, dan system prompt default."
      />
      <ErrorNote error={error} />
      <form onSubmit={save} className="flex flex-col gap-4">
        <Card className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="save-mode">Mode hemat token</Label>
            <Select
              id="save-mode"
              value={form.save_mode}
              onChange={(e) => set("save_mode", e.target.value as SaveMode)}
            >
              <option value="off">Off — kirim history apa adanya</option>
              <option value="normal">Normal — rapikan, dedupe, 12 pesan terakhir + ringkasan</option>
              <option value="aggressive">Agresif — 6 pesan terakhir, buang basa-basi</option>
            </Select>
          </div>
          <div>
            <Label htmlFor="max-tokens">Max token jawaban</Label>
            <Input
              id="max-tokens"
              type="number"
              min={64}
              max={32000}
              value={form.max_tokens}
              onChange={(e) => set("max_tokens", Number(e.target.value))}
            />
          </div>
          <div className="flex items-center justify-between gap-3 sm:col-span-2">
            <div>
              <p className="text-sm font-medium">Izinkan fallback otomatis</p>
              <p className="text-xs text-muted">
                Jika model pilihanmu gagal / semua key habis, pindah ke model lain sesuai urutan di halaman
                Models.
              </p>
            </div>
            <Switch
              label="Izinkan fallback"
              checked={form.allow_fallback}
              onChange={(v) => set("allow_fallback", v)}
            />
          </div>
        </Card>
        <Card>
          <Label htmlFor="system-prompt" hint="(dipakai di semua chat)">
            System prompt default
          </Label>
          <Textarea
            id="system-prompt"
            rows={5}
            maxLength={8000}
            value={form.system_prompt}
            onChange={(e) => set("system_prompt", e.target.value)}
            placeholder="Jawab dalam Bahasa Indonesia yang ringkas."
          />
        </Card>
        <Card className="flex flex-col gap-4">
          <h2 className="flex items-center gap-2 font-semibold">
            <BellRing size={18} /> Notifikasi saat job selesai
          </h2>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Web Push (browser/PWA)</p>
              <p className="text-xs text-muted">
                {form.vapid_public_key
                  ? form.notify_webpush
                    ? "Aktif di perangkat ini."
                    : "Belum aktif."
                  : "Server belum mengisi VAPID key."}
              </p>
            </div>
            {form.notify_webpush ? (
              <Switch label="Web Push" checked onChange={(v) => set("notify_webpush", v)} />
            ) : (
              <Button type="button" variant="outline" onClick={enablePush} disabled={!form.vapid_public_key}>
                Aktifkan
              </Button>
            )}
          </div>
          <div>
            <Label
              htmlFor="tg-chat"
              hint={
                form.telegram_enabled
                  ? "(kirim /start ke bot, lalu isi chat id)"
                  : "(bot Telegram belum dikonfigurasi server)"
              }
            >
              Telegram chat ID
            </Label>
            <Input
              id="tg-chat"
              value={form.notify_telegram_chat_id}
              disabled={!form.telegram_enabled}
              onChange={(e) => set("notify_telegram_chat_id", e.target.value)}
              placeholder="123456789"
            />
          </div>
        </Card>
        <div>
          <Button type="submit" disabled={saving}>
            {saving ? "Menyimpan..." : "Simpan pengaturan"}
          </Button>
        </div>
      </form>
    </div>
  );
}
