export const nf = new Intl.NumberFormat("id-ID");

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}jt`;
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}rb`;
  return nf.format(n);
}

export function formatUsd(n: number): string {
  return `$${n < 1 ? n.toFixed(4) : n.toFixed(2)}`;
}

export function timeAgo(iso: string | null, now = Date.now()): string {
  if (!iso) return "-";
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat("id", { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(diff, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

export const STATUS_LABEL: Record<string, string> = {
  active: "Aktif",
  cooling_down: "Cooldown",
  exhausted: "Kuota habis",
  invalid: "Invalid",
  disabled: "Nonaktif",
  queued: "Antre",
  running: "Berjalan",
  waiting_quota: "Menunggu kuota",
  done: "Selesai",
  failed: "Gagal",
  cancelled: "Dibatalkan",
};
