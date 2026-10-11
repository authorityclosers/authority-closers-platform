// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";

import { command } from "../lib/client-api";
import { REASON_PATTERN, activeMarks, normalizeMarks } from "./safety-data";

describe("safety marks", () => {
  it("keeps only marks nobody released", () => {
    const data = normalizeMarks({
      recording_id: "r1",
      transcript_revisions: [{ revision: "t1", segment_count: 40 }],
      marks: [
        {
          mark_id: "m1",
          segment_id: "s1",
          category: "SENSITIVE_LEGAL",
          action: "mark",
        },
        {
          mark_id: "m2",
          segment_id: "s2",
          category: "SENSITIVE_FINANCIAL",
          action: "mark",
        },
        {
          mark_id: "m3",
          segment_id: "s1",
          action: "release",
          supersedes_mark_id: "m1",
        },
      ],
    });
    expect(activeMarks(data.marks).map((mark) => mark.id)).toEqual(["m2"]);
    expect(data.revisions).toEqual([{ revision: "t1", segments: 40 }]);
    expect(REASON_PATTERN.test("AUT-1820 request")).toBe(true);
    expect(REASON_PATTERN.test("x")).toBe(false);
  });
});

describe("admin commands", () => {
  it("posts same-origin JSON with an idempotency key and reports problems plainly", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ok: 1 }));
    expect(await command("/v1/x/y", { a: 1 }, "key-1", fetcher)).toEqual({
      ok: true,
      data: { ok: 1 },
    });
    const [, init] = fetcher.mock.calls[0]!;
    expect(new Headers(init.headers).get("idempotency-key")).toBe("key-1");
    expect(init.credentials).toBe("same-origin");
    const refused = vi
      .fn()
      .mockResolvedValue(
        Response.json({ detail: "Already released." }, { status: 409 }),
      );
    expect(await command("/v1/x", {}, "k", refused)).toEqual({
      ok: false,
      status: 409,
      message: "Already released.",
    });
    expect(
      await command("https://evil.example/v1/x", {}, "k", fetcher),
    ).toMatchObject({ ok: false, status: 400 });
    const offline = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    expect(await command("/v1/x", {}, "k", offline)).toMatchObject({
      ok: false,
      status: 0,
    });
  });
});
