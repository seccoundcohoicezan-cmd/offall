"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Brain, Leaf, Zap } from "lucide-react";
import { clockTime } from "@/lib/format";
import { cn } from "@/lib/cn";

export interface BubbleProps {
  role: "user" | "assistant" | "system";
  content: string;
  createdAt?: string;
  modelUsed?: string | null;
  tokensSaved?: number;
  cached?: boolean;
  memoriesUsed?: number;
  streaming?: boolean;
  initials: string;
}

export function MessageBubble({
  role,
  content,
  createdAt,
  modelUsed,
  tokensSaved,
  cached,
  memoriesUsed,
  streaming,
  initials,
}: BubbleProps) {
  const isUser = role === "user";
  return (
    <article
      className={cn("flex gap-3", isUser && "flex-row-reverse sm:flex-row")}
      aria-label={isUser ? "Pesan kamu" : "Jawaban AI"}
    >
      <span
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold",
          isUser ? "bg-surface-2" : "bg-gradient-to-br from-accent to-accent-2 text-white",
        )}
      >
        {isUser ? initials : "AI"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold">{isUser ? "You" : "OFALL Agent"}</span>
          {!isUser && modelUsed && (
            <span className="rounded-md bg-accent/15 px-1.5 text-xs text-accent-2" data-testid="model-badge">
              {modelUsed}
            </span>
          )}
          {!isUser && !!tokensSaved && (
            <span
              className="flex items-center gap-1 rounded-md bg-success/15 px-1.5 text-xs text-success"
              title="Token dihemat oleh Token Saver"
            >
              <Leaf size={11} /> {tokensSaved} token dihemat
            </span>
          )}
          {!isUser && !!memoriesUsed && (
            <span
              className="flex items-center gap-1 rounded-md bg-accent/15 px-1.5 text-xs text-accent-2"
              title="Jawaban memakai memori tentang kamu"
            >
              <Brain size={11} /> {memoriesUsed} memori
            </span>
          )}
          {cached && (
            <span className="flex items-center gap-1 rounded-md bg-warning/15 px-1.5 text-xs text-warning">
              <Zap size={11} /> cache
            </span>
          )}
          {createdAt && <span className="text-xs text-muted">{clockTime(createdAt)}</span>}
        </div>
        <div
          className={cn(
            "prose-chat rounded-2xl border px-4 py-3 text-[15px] leading-relaxed break-words",
            isUser ? "border-border bg-surface-2/70" : "border-border bg-surface/80",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{content}</p>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {content || (streaming ? "…" : "")}
            </ReactMarkdown>
          )}
          {streaming && (
            <span className="ml-0.5 inline-block h-4 w-2 animate-pulse rounded-sm bg-accent-2 align-middle" />
          )}
        </div>
      </div>
    </article>
  );
}
