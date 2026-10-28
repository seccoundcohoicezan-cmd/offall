import { afterEach, describe, expect, it, vi } from "vitest";
import { uuid } from "@/lib/uuid";

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("uuid", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("works when randomUUID is missing (plain HTTP pages)", () => {
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(7) });
    expect(uuid()).toMatch(V4);
  });

  it("works with no crypto at all", () => {
    vi.stubGlobal("crypto", undefined);
    const a = uuid();
    expect(a).toMatch(V4);
    expect(uuid()).not.toBe(a);
  });

  it("uses randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
    expect(uuid()).toBe("11111111-1111-4111-8111-111111111111");
  });
});
