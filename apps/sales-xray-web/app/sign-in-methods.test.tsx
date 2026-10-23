// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const seen = vi.hoisted(() => ({
  notices: [] as unknown[],
  trips: [] as string[],
}));
vi.mock("./notice-center", () => ({
  notify: (notice: unknown) => seen.notices.push(notice),
}));
// Logos load their artwork with fetch; these tests count the account's own calls.
vi.mock("./ui/brand-tile", () => ({ BrandTile: () => null }));
vi.mock("./sign-in-connect", () => ({
  goToProvider: (url: string) => seen.trips.push(url),
}));

import {
  connectReturnNotice,
  parseSignInMethods,
  SignInMethods,
} from "./sign-in-methods";

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
  seen.notices = [];
  seen.trips = [];
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

const WITH_CONNECT = {
  ...LISTING,
  available: [
    { kind: "google", label: "Google", connected: true },
    { kind: "facebook", label: "Facebook", connected: false },
  ],
};

it("offers Connect only for providers this environment has and the account lacks", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(WITH_CONNECT)),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  expect(host.querySelector('[data-connect="facebook"]')).not.toBeNull();
  expect(host.querySelector('[data-connect="google"]')).toBeNull();
  expect(host.querySelector('[data-connect="apple"]')).toBeNull();
  expect(
    Array.from(host.querySelectorAll("button")).filter(
      (item) => item.textContent === "Connect",
    ),
  ).toHaveLength(1);
  expect(host.textContent).toContain(
    "Not connected. Sign in with your Facebook account too.",
  );
});

it("connects Facebook by a full-page trip there and back to this section", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return url.endsWith("/connect")
        ? Response.json({
            redirect_url: "https://www.facebook.com/v21.0/dialog/oauth?state=x",
          })
        : Response.json(WITH_CONNECT);
    }),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  await act(async () => button("Connect")!.click());
  await flush();
  const post = calls.find((call) => call.url.endsWith("/connect"));
  expect(post?.url).toBe("/v1/me/sign-in-methods/facebook/connect");
  expect(post?.init?.method).toBe("POST");
  expect(JSON.parse(String(post?.init?.body))).toEqual({
    return_to: "/settings/security",
  });
  expect(seen.trips).toEqual([
    "https://www.facebook.com/v21.0/dialog/oauth?state=x",
  ]);
  expect(window.sessionStorage.getItem("sx.signInConnect")).toBe("facebook");
  window.sessionStorage.clear();
});

it("asks for a fresh sign-in before connecting when the session is too old", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("/connect")
        ? Response.json(
            { detail: "Sign in again first.", code: "fresh_sign_in" },
            { status: 403 },
          )
        : Response.json(WITH_CONNECT),
    ),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  await act(async () => button("Connect")!.click());
  await flush();
  expect(seen.trips).toEqual([]);
  expect(host.textContent).toContain(
    "sign out below and sign in again, then connect it within 10 minutes",
  );
  expect(seen.notices).toEqual([
    expect.objectContaining({ title: "Sign in again to connect" }),
  ]);
});

it("shows the server's words when a connect is refused", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("/connect")
        ? Response.json(
            { detail: "Facebook isn't offered here.", code: "not_configured" },
            { status: 404 },
          )
        : Response.json(WITH_CONNECT),
    ),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  await act(async () => button("Connect")!.click());
  await flush();
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "error",
      title: "Facebook wasn’t connected",
      message: "Facebook isn't offered here.",
    }),
  ]);
});

it("inside the phone app, says where to connect instead of offering it", async () => {
  vi.stubGlobal("SXPhone", {
    postMessage: () => undefined,
    addEventListener: () => undefined,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(WITH_CONNECT)),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  expect(button("Connect")).toBeUndefined();
  expect(host.textContent).toContain(
    "Connect Facebook from a computer or your phone’s browser.",
  );
});

it("says how the trip went once on the way back, then drops the query", async () => {
  window.history.replaceState(
    null,
    "",
    "/settings/security?connected=facebook&tab=x",
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(WITH_CONNECT)),
  );
  await act(async () => root.render(<SignInMethods active />));
  await flush();
  expect(seen.notices).toEqual([
    expect.objectContaining({
      tone: "success",
      title: "Facebook is connected",
    }),
  ]);
  expect(window.location.search).toBe("?tab=x");
  window.history.replaceState(null, "", "/");
});

it("words every way back from a provider", () => {
  expect(connectReturnNotice("", null)).toBeNull();
  expect(connectReturnNotice("?connect_error=in_use", "google")).toMatchObject({
    tone: "error",
    title: "That Google account is already used by another Sales X-Ray account",
  });
  expect(
    connectReturnNotice("?connect_error=cancelled", "apple"),
  ).toMatchObject({ tone: "info", title: "Apple wasn’t connected" });
  expect(connectReturnNotice("?connect_error=failed", null)).toMatchObject({
    tone: "error",
    title: "Couldn’t connect that account",
  });
  expect(connectReturnNotice("?connected=evil", "nope")).toMatchObject({
    title: "That account is connected",
  });
});

it("reads the Connect list, trusting the account's own methods", () => {
  const parsed = parseSignInMethods({
    ...LISTING,
    available: [
      { kind: "google", label: "Google", connected: false },
      { kind: "passkey", label: "Passkey", connected: false },
      { kind: "apple", connected: false },
    ],
  });
  expect(parsed?.available).toEqual([
    { kind: "google", label: "Google", connected: true },
    { kind: "apple", label: "Apple", connected: false },
  ]);
  expect(parseSignInMethods({ methods: [] })?.available).toEqual([]);
});
