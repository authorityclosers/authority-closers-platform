import { afterEach, expect, it, vi } from "vitest";

import {
  clearRecentErrors,
  installErrorRecorder,
  recentErrors,
  recordError,
} from "./recent-errors";
import { scrubRoute, scrubText } from "./scrub";
import { browserFrom, osFrom } from "./device";

afterEach(() => clearRecentErrors());

it("drops tokens, keys, contacts and long opaque strings from text", () => {
  const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXZhbHVl";
  expect(
    scrubText(
      `${jwt} Bearer abc.def-123456 ac_live_0123456789abcdef password: hunter22 ` +
        "mail asha@example.test call +91 98765-43210 sig " +
        "A".repeat(48) +
        " status 500 in 2 s",
      500,
    ),
  ).toBe(
    "[token] Bearer [token] [key] [secret] mail [email] call [phone] sig [long] status 500 in 2 s",
  );
  expect(scrubText("one two three", 7)).toBe("one two");
  expect(scrubText(42, 5)).toBe("");
});

it("keeps a route's screen and drops secret values and the fragment", () => {
  expect(scrubRoute("/leads?lead=8f0e&tab=stages#top")).toBe(
    "/leads?lead=8f0e&tab=stages",
  );
  expect(scrubRoute("/auth/complete?code=987654&state=xyz")).toBe(
    "/auth/complete?code=&state=",
  );
  expect(scrubRoute("https://elsewhere.example/x?phone=98765")).toBe(
    "/x?phone=",
  );
  expect(scrubRoute("")).toBe("/");
});

it("keeps the last twenty problems, scrubbed, one entry per repeating loop", () => {
  for (let n = 0; n < 25; n += 1) {
    recordError({ kind: "error", message: `boom ${n}` });
  }
  recordError({ kind: "error", message: "boom 24" });
  recordError({
    kind: "http",
    status: 500,
    method: "post",
    path: "/v1/lead-desk/leads?email=asha@example.test",
    message: "failed for asha@example.test",
    reference: "req-1234abcd",
  });
  recordError({ kind: "notice", message: "x", reference: "has spaces in it" });
  const kept = recentErrors();
  expect(kept).toHaveLength(20);
  expect(kept.filter((entry) => entry.message === "boom 24")).toHaveLength(1);
  expect(kept.at(-2)).toMatchObject({
    kind: "http",
    status: 500,
    method: "POST",
    path: "/v1/lead-desk/leads?email=",
    message: "failed for [email]",
    reference: "req-1234abcd",
  });
  expect(kept.at(-1)?.reference).toBeUndefined();
});

it("records script errors, rejections and console errors once installed", () => {
  const original = console.error;
  const quiet = vi.fn();
  console.error = quiet;
  const uninstall = installErrorRecorder();
  try {
    window.dispatchEvent(
      new ErrorEvent("error", {
        error: new TypeError("x is undefined"),
        message: "x is undefined",
        filename: "https://app.example/_next/static/chunk.js?token=abc",
        lineno: 3,
        colno: 9,
      }),
    );
    console.error("Warning: failed prop for asha@example.test", { lead: "x" });
    expect(quiet).toHaveBeenCalledTimes(1);
    const kept = recentErrors();
    expect(kept[0]).toMatchObject({
      kind: "error",
      message: "TypeError: x is undefined",
      source: "/_next/static/chunk.js:3:9",
    });
    expect(kept[1]).toMatchObject({
      kind: "console",
      message: "Warning: failed prop for [email]",
    });
  } finally {
    uninstall();
    console.error = original;
  }
});

it("names the system and browser without anything personal", () => {
  const redmi =
    "Mozilla/5.0 (Linux; Android 14; 23124RN87I Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36 SalesXrayApp/0.3";
  expect(osFrom(redmi)).toBe("Android 14");
  expect(browserFrom(redmi)).toBe("Android WebView 141");
  const mac =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15";
  expect(osFrom(mac)).toBe("macOS");
  expect(browserFrom(mac)).toBe("Safari 18");
  const edge =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0";
  expect(osFrom(edge)).toBe("Windows");
  expect(browserFrom(edge)).toBe("Edge 141");
});

// #15: "/analysis/calls/<uuid>" was "/[long]"; a route is its pattern now.
it("keeps a route's pattern, with ids taken out and personal data masked", () => {
  expect(
    scrubRoute("/analysis/calls/0f8e2a4c-5b6d-4e7f-8a9b-0c1d2e3f4a5b"),
  ).toBe("/analysis/calls/:id");
  expect(scrubRoute("/prospects/48213/notes")).toBe("/prospects/:id/notes");
  expect(
    scrubRoute("/leads?lead=0f8e2a4c-5b6d-4e7f-8a9b-0c1d2e3f4a5b&tab=stages"),
  ).toBe("/leads?lead=:id&tab=stages");
  expect(scrubRoute("/x/a.person@example.test?q=a.person@example.test")).toBe(
    "/x/[email]?q=[email]",
  );
  expect(scrubRoute("/auth/complete?code=987654")).toBe("/auth/complete?code=");
});
