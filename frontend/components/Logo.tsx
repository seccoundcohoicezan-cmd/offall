import Link from "next/link";
import { cn } from "@/lib/cn";

/** Official OFALL mark (from the brand PNG) + live wordmark so it works in light & dark. */
export function Logo({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link
      href="/chat"
      className={cn("flex shrink-0 items-center gap-2.5", className)}
      aria-label="OFALL beranda"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/logo-mark-wide.png"
        alt=""
        width={64}
        height={32}
        className="h-8 w-auto drop-shadow-[0_0_12px_rgba(139,92,246,0.55)] sm:h-9"
      />
      {!compact && (
        <span className="text-[22px] font-extrabold tracking-tight sm:text-2xl">
          <span className="bg-gradient-to-r from-text via-text to-accent-2 bg-clip-text text-transparent">
            OFALL
          </span>
          <span className="text-accent-2">.</span>
        </span>
      )}
    </Link>
  );
}
