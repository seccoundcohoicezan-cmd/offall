import { refreshSession } from "./api";

export interface SseEvent {
  id?: string;
  event: string;
  data: string;
}

/** Incremental text/event-stream parser (handles chunks split mid-line). */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: SseEvent[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, sep);
      this.buffer = this.buffer.slice(sep + 2);
      const ev: SseEvent = { event: "message", data: "" };
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const idx = line.indexOf(":");
        const field = idx === -1 ? line : line.slice(0, idx);
        const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
        if (field === "id") ev.id = value;
        else if (field === "event") ev.event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length || ev.id) {
        ev.data = data.join("\n");
        events.push(ev);
      }
    }
    return events;
  }
}

export interface JobStreamHandlers {
  onDelta: (text: string) => void;
  onSnapshot: (text: string) => void;
  onStatus: (data: Record<string, unknown>) => void;
  onDone: (data: Record<string, unknown>) => void;
}

/**
 * Follows a job's SSE stream and reconnects with Last-Event-ID after drops, so a
 * closed tab or flaky network never loses output. Resolves when the job ends.
 */
export async function followJob(
  jobId: string,
  handlers: JobStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  let lastId: string | undefined;
  let attempt = 0;
  while (!signal.aborted) {
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}/stream`, {
        headers: lastId ? { "Last-Event-ID": lastId } : {},
        credentials: "same-origin",
        signal,
      });
      if (res.status === 401 && (await refreshSession())) continue;
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      attempt = 0;
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const ev of parser.push(value)) {
          if (ev.id) lastId = ev.id;
          const data = JSON.parse(ev.data || "{}") as Record<string, unknown>;
          if (ev.event === "delta") handlers.onDelta(String(data.text ?? ""));
          else if (ev.event === "snapshot") handlers.onSnapshot(String(data.text ?? ""));
          else if (ev.event === "status") handlers.onStatus(data);
          else if (ev.event === "done" || ev.event === "error") {
            handlers.onDone(data);
            return;
          }
        }
      }
    } catch (err) {
      if (signal.aborted) return;
      console.warn("job stream dropped, reconnecting", err);
    }
    attempt += 1;
    await new Promise((r) => setTimeout(r, Math.min(1000 * attempt, 8000)));
  }
}
