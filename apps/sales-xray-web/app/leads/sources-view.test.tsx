import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { googleLine, SourcesView, type GoogleAccount } from "./sources-view";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=sources&google=connected"),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const account = (extra: Partial<GoogleAccount> = {}): GoogleAccount => ({
  customerId: "1012223333",
  name: "Rao Solar",
  active: true,
  test: false,
  received: 3,
  lastPulledAt: null,
  forms: 2,
  sending: 2,
  other: 0,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { url: string; method: string }[];
let accounts: GoogleAccount[];
let configured: boolean;

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  calls = [];
  configured = true;
  accounts = [account({ active: false, forms: null, sending: null })];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.endsWith("/google/status")) return json({ configured, accounts });
      if (url.endsWith("/google/accounts/1012223333") && method === "POST") {
        accounts = [account()];
        return json({ account: accounts[0], imported: 3 });
      }
      if (url.endsWith("/meta/status"))
        return json({ configured: false, pages: [] });
      return json({ sources: [], meta: "not_configured" });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const render = async () => {
  await act(async () =>
    root.render(
      <SourcesView sandbox={false} onChanged={() => {}} onImport={() => {}} />,
    ),
  );
};

const google = () => host.querySelector('[data-brand="google"]') as HTMLElement;

it("says where an account's leads come from in one line", () => {
  expect(googleLine(account())).toBe("3 leads · 2 forms send here instantly");
  expect(
    googleLine(account({ received: 1, forms: 3, sending: 1, other: 2 })),
  ).toBe("1 lead · 1 of 3 forms send here instantly");
  expect(googleLine(account({ forms: 0, sending: 0 }))).toBe(
    "3 leads · no lead forms yet",
  );
  expect(googleLine(account({ active: false }))).toBe(
    "Switched off: no new leads come in",
  );
});

it("connects with Google and turns an account on in one tap", async () => {
  await render();
  const tile = google();
  expect(tile.textContent).toContain(
    "Connected. Turn on the accounts you want leads from.",
  );
  const connect = tile.querySelector("a") as HTMLAnchorElement;
  expect(connect.getAttribute("href")).toBe("/v1/lead-desk/google/connect");
  expect(connect.textContent).toContain("Add an account");

  const turnOn = [...tile.querySelectorAll("button")].find(
    (button) => button.textContent === "Turn on",
  ) as HTMLButtonElement;
  await act(async () => turnOn.click());

  expect(calls).toContainEqual({
    url: "/v1/lead-desk/google/accounts/1012223333",
    method: "POST",
  });
  expect(tile.textContent).toContain("3 leads from the last 30 days came in.");
  expect(tile.textContent).toContain("2 forms send here instantly");
  expect(tile.textContent).toContain("Check now");
});

it("stays 'Coming soon' until AC's Google Ads app is set up", async () => {
  configured = false;
  accounts = [];
  await render();
  expect(google().textContent).toContain("Coming soon");
  expect(google().querySelector("a")).toBeNull();
});

/** The app's SXPhone object: answers status (this app can open the browser) and openConnect. */
function fakePhone(sent: string[]) {
  const listeners: ((event: { data: unknown }) => void)[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (
      _: string,
      listener: (event: { data: unknown }) => void,
    ) => listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string; method: string };
      sent.push(message.method);
      const result =
        message.method === "status" ? { connect: true } : { opened: true };
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
}

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

it("in the Sales Xray app, Continue with Google opens in the phone's browser", async () => {
  const sent: string[] = [];
  fakePhone(sent);
  const plain = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/google/connect?")) {
        calls.push({ url: String(input), method: "GET" });
        return json({
          url: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        });
      }
      return plain(input, init);
    }),
  );
  await render();
  const link = google().querySelector("a") as HTMLAnchorElement;
  const click = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => {
    link.dispatchEvent(click);
  });
  await settle();

  expect(click.defaultPrevented).toBe(true);
  expect(sent).toEqual(["status", "openConnect"]);
  expect(
    calls.some((call) =>
      call.url.startsWith("/v1/lead-desk/google/connect?app_challenge="),
    ),
  ).toBe(true);
});

it("finishes a Google Connect the app brought back to this page", async () => {
  window.localStorage.setItem(
    "sx.appConnect",
    JSON.stringify({
      provider: "google",
      verifier: "v".repeat(64),
      at: Date.now(),
    }),
  );
  window.history.replaceState(
    null,
    "",
    `/leads?tab=sources#connect=google&handoff=${"H".repeat(40)}`,
  );
  const plain = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/google/app-complete")) {
        calls.push({ url: String(input), method: init?.method ?? "GET" });
        return json({ result: "noaccounts" });
      }
      return plain(input, init);
    }),
  );
  await render();
  await settle();

  expect(calls).toContainEqual({
    url: "/v1/lead-desk/google/app-complete",
    method: "POST",
  });
  expect(google().textContent).toContain(
    "That Google account has no Google Ads accounts.",
  );
  expect(window.location.hash).toBe("");
});
