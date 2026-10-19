// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { parseSignInMethods, SignInMethods } from "./sign-in-methods";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const LISTING = {
  methods: [
    {
      kind: "email_code",
      added_at: null,
      last_used_at: null,
      removable: false,
    },
    {
      kind: "password",
      added_at: "2026-09-01T10:00:00+00:00",
      last_used_at: null,
      removable: false,
    },
    {
      kind: "google",
      added_at: "2026-10-01T10:00:00+00:00",
      last_used_at: "2026-10-18T09:00:00+00:00",
      removable: true,
    },
  ],
  fresh_sign_in: true,
  fresh_minutes: 10,
};

async function flush() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}

function button(text: string) {
  return Array.from(host.querySelectorAll("button")).find((item) =>
    item.textContent?.includes(text),
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("loads only once Security is open, then lists each way in", async () => {
  const fetcher = vi.fn(async () => Response.json(LISTING));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<SignInMethods active={false} />));
  await flush();
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/me/sign-in-methods",
    expect.anything(),
  );
  expect(host.textContent).toContain("Email code");
  expect(host.textContent).toContain("Password");
  expect(host.textContent).toContain("Added 1 Oct 2026, last used 18 Oct 2026");
  const removes = Array.from(host.querySelectorAll("button")).filter((item) =>
    item.textContent?.includes("Remove"),
  );
  expect(removes).toHaveLength(1);
});

it("removes Google only on the second click, then reads the list again", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/remove")) return Response.json({ removed: "google" });
      return Response.json(
        calls.length > 2
          ? { ...LISTING, methods: LISTING.methods.slice(0, 2) }
          : LISTING,
      );
    }),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  await act(async () => button("Remove")!.click());
  await flush();
  expect(calls).toEqual(["GET /v1/me/sign-in-methods"]);
  expect(button("Remove Google?")).toBeTruthy();
  await act(async () => button("Remove Google?")!.click());
  await flush();
  expect(calls).toEqual([
    "GET /v1/me/sign-in-methods",
    "POST /v1/me/sign-in-methods/google/remove",
    "GET /v1/me/sign-in-methods",
  ]);
  expect(host.textContent).not.toContain("Google");
});

it("asks for a fresh sign-in when the server says the session is too old", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("/remove")
        ? Response.json(
            { detail: { code: "fresh_sign_in", message: "Sign in again." } },
            { status: 409 },
          )
        : Response.json(LISTING),
    ),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  await act(async () => button("Remove")!.click());
  await act(async () => button("Remove Google?")!.click());
  await flush();
  expect(host.textContent).toContain(
    "sign out below and sign in again, then remove it within 10 minutes",
  );
});

it("reads only the methods it knows and never offers to remove email or password", () => {
  const parsed = parseSignInMethods({
    methods: [
      { kind: "password", removable: true },
      { kind: "passkey", removable: true },
      { kind: "facebook", removable: true },
    ],
  });
  expect(
    parsed?.methods.map((method) => [method.kind, method.removable]),
  ).toEqual([
    ["password", false],
    ["facebook", true],
  ]);
  expect(parsed?.freshMinutes).toBe(10);
  expect(parseSignInMethods(null)).toBeNull();
  expect(parseSignInMethods({ methods: "x" })).toBeNull();
});
