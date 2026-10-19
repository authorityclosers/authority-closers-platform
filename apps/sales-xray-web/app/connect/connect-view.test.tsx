import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ConnectView, readAsk } from "./connect-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const QUERY =
  "?client_id=sxc_abc&redirect_uri=https%3A%2F%2Fpartner.example.test%2Fcb&scope=leads%3Aread" +
  "&code_challenge=" +
  "a".repeat(43) +
  "&code_challenge_method=S256&response_type=code&state=s1&extra=ignored";

let root: Root;
let host: HTMLDivElement;
const posts: Array<{ url: string; body: unknown }> = [];

beforeEach(() => {
  posts.length = 0;
  window.history.replaceState(null, "", `/connect${QUERY}`);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
}

function stub(check: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      posts.push({ url, body: JSON.parse(String(init?.body ?? "null")) });
      if (url.endsWith("/check"))
        return new Response(JSON.stringify(check.body), {
          status: check.status,
        });
      return new Response(JSON.stringify({ redirect: "about:blank#denied" }), {
        status: 200,
      });
    }),
  );
}

it("reads only the OAuth fields from the address", () => {
  expect(readAsk(QUERY)).toEqual({
    client_id: "sxc_abc",
    redirect_uri: "https://partner.example.test/cb",
    scope: "leads:read",
    code_challenge: "a".repeat(43),
    code_challenge_method: "S256",
    response_type: "code",
    state: "s1",
  });
});

it("shows the app, the organisation and what it may do", async () => {
  stub({
    status: 200,
    body: {
      app: { name: "Partner CRM", client_id: "sxc_abc" },
      returns_to: "partner.example.test",
      organisation: { id: "t1", name: "Fictional Solar Co" },
      scopes: [{ key: "leads:read", label: "Read leads" }],
    },
  });
  await act(async () => root.render(<ConnectView />));
  await flush();
  expect(host.textContent).toContain("Connect Partner CRM to Sales X-Ray?");
  expect(host.textContent).toContain("Fictional Solar Co");
  expect(host.textContent).toContain("Read leads");
  expect(host.textContent).toContain("partner.example.test");
  const cancel = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "Cancel",
  );
  await act(async () => cancel?.click());
  await flush();
  expect(posts.at(-1)).toMatchObject({
    url: "/v1/oauth/authorize/decision",
    body: { client_id: "sxc_abc", state: "s1", approve: false },
  });
});

it("never redirects for an unknown app", async () => {
  stub({
    status: 400,
    body: { detail: "This app is not registered with Sales X-Ray." },
  });
  await act(async () => root.render(<ConnectView />));
  await flush();
  expect(host.textContent).toContain("This link can't be used");
  expect(host.textContent).toContain("not registered");
  expect(host.querySelector("button")).toBeNull();
});
