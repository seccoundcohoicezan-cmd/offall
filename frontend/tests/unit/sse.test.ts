import { describe, expect, it } from "vitest";
import { SseParser } from "@/lib/sse";
import { formatTokens, STATUS_LABEL } from "@/lib/format";

describe("SseParser", () => {
  it("parses events split across chunks", () => {
    const p = new SseParser();
    expect(p.push('id: 1-0\nevent: delta\ndata: {"text":"ha')).toEqual([]);
    const events = p.push('lo"}\n\nid: 1-1\nevent: done\ndata: {}\n\n');
    expect(events).toEqual([
      { id: "1-0", event: "delta", data: '{"text":"halo"}' },
      { id: "1-1", event: "done", data: "{}" },
    ]);
  });

  it("ignores keepalive comments and handles CRLF", () => {
    const p = new SseParser();
    expect(p.push(": keepalive\r\n\r\nevent: snapshot\r\ndata: {\"text\":\"x\"}\r\n\r\n")).toEqual([
      { event: "snapshot", data: '{"text":"x"}' },
    ]);
  });
});

describe("format", () => {
  it("formats token counts", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(12_500)).toBe("12.5rb");
    expect(formatTokens(2_000_000)).toBe("2.0jt");
  });
  it("labels every job status", () => {
    for (const s of ["queued", "running", "waiting_quota", "done", "failed", "cancelled"]) expect(STATUS_LABEL[s]).toBeTruthy();
  });
});
