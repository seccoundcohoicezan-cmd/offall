import { PROVIDER_META } from "@/lib/providers";
import { cn } from "@/lib/cn";

export function ProviderIcon({
  provider,
  size = 36,
  className,
}: {
  provider: string;
  size?: number;
  className?: string;
}) {
  const meta = PROVIDER_META[provider] ?? {
    color: "#64748b",
    short: provider.slice(0, 1).toUpperCase(),
    label: provider,
  };
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-xl font-bold text-white",
        className,
      )}
      style={{ width: size, height: size, background: meta.color, fontSize: size * 0.42 }}
    >
      {meta.short}
    </span>
  );
}
