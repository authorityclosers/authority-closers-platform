// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_COMPLETE_MESSAGE } from "../../account-auth-client";
import { AuthCompleteClient } from "./auth-complete-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

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

it("posts only a flow-bound signal to the exact opener origin", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  await act(async () =>
    root.render(<AuthCompleteClient flow={flow} result="success" />),
  );
  await act(async () => Promise.resolve());
  expect(opener.postMessage).toHaveBeenCalledWith(
    { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "success" },
    window.location.origin,
  );
  expect(JSON.stringify(opener.postMessage.mock.calls)).not.toContain("token");
  expect(host.textContent).toContain("Return to the Sales X-Ray window");
  expect(fetcher).not.toHaveBeenCalled();
});

it("sends nothing for an invalid callback flow or result", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  await act(async () =>
    root.render(
      <AuthCompleteClient flow="//another-origin" result="success" />,
    ),
  );
  await act(async () =>
    root.render(
      <AuthCompleteClient
        flow="eaed7960-d4d0-4675-bd34-5b6a7d9c598d"
        result={null}
      />,
    ),
  );
  expect(opener.postMessage).not.toHaveBeenCalled();
});

it("forwards failure and review results without requiring a success receipt", async () => {
  const opener = { postMessage: vi.fn() };
  vi.stubGlobal("opener", opener);
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  for (const result of ["failed", "review_terms", "unavailable"] as const) {
    await act(async () =>
      root.render(
        <AuthCompleteClient key={result} flow={flow} result={result} />,
      ),
    );
  }
  expect(
    opener.postMessage.mock.calls.map(([message]) => message.auth_result),
  ).toEqual(["failed", "review_terms", "unavailable"]);
  expect(fetcher).not.toHaveBeenCalled();
});

describe("after a full-page sign-in (no sign-in window)", () => {
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  const session = {
    person_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    session_id: "7f2b0c1e-3a4d-4e5f-8a9b-0c1d2e3f4a5b",
    selected_tenant_id: null,
    workspaces: [],
  };
  let replace: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    window.sessionStorage.clear();
    vi.stubGlobal("opener", null);
    replace = vi.spyOn(window.location, "replace").mockImplementation(() => {});
  });
  afterEach(() => replace.mockRestore());

  function started(returnTo: string, at = Date.now()) {
    window.sessionStorage.setItem(
      "sx.signIn.redirect",
      JSON.stringify({ flow, provider: "google", returnTo, at }),
    );
  }

  async function settle() {
    await act(async () => {
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
  }

  it("returns to the starting page once this flow's receipt and session match", async () => {
    started("/login?next=/leads");
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        if (url === "/v1/auth/google/completion")
          return Response.json({ matched: true });
        if (url === "/v1/me/workspaces") return Response.json(session);
        throw new Error(`Unexpected ${url}`);
      }),
    );
    await act(async () =>
      root.render(<AuthCompleteClient flow={flow} result="success" />),
    );
    await settle();
    expect(calls).toEqual(["/v1/auth/google/completion", "/v1/me/workspaces"]);
    expect(replace).toHaveBeenCalledWith("/login?next=/leads");
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.result")!),
    ).toMatchObject({ result: "success", provider: "google" });
    expect(window.sessionStorage.getItem("sx.signIn.redirect")).toBeNull();
    expect(host.textContent).toContain("Signing you in");
  });

  it("keeps the starting page through React's double effect run in development", async () => {
    started("/login?next=/calls");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/v1/auth/google/completion"
          ? Response.json({ matched: true })
          : Response.json(session),
      ),
    );
    await act(async () =>
      root.render(
        <StrictMode>
          <AuthCompleteClient flow={flow} result="success" />
        </StrictMode>,
      ),
    );
    await settle();
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/login?next=/calls");
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.result")!),
    ).toMatchObject({ result: "success" });
  });

  it("an unmatched receipt goes back as a failure, never as signed in", async () => {
    started("/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ matched: false })),
    );
    await act(async () =>
      root.render(<AuthCompleteClient flow={flow} result="success" />),
    );
    await settle();
    expect(replace).toHaveBeenCalledWith("/");
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.result")!),
    ).toMatchObject({ result: "failed" });
  });

  it("carries a refusal back without reading the session", async () => {
    started("/login");
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await act(async () =>
      root.render(<AuthCompleteClient flow={flow} result="review_terms" />),
    );
    await settle();
    expect(fetcher).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/login");
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.result")!),
    ).toMatchObject({ result: "review_terms", provider: "google" });
  });

  it("ignores another flow's or an unsafe starting page", async () => {
    window.sessionStorage.setItem(
      "sx.signIn.redirect",
      JSON.stringify({
        flow: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
        provider: "google",
        returnTo: "/leads",
        at: Date.now(),
      }),
    );
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await act(async () =>
      root.render(<AuthCompleteClient flow={flow} result="failed" />),
    );
    await settle();
    expect(replace).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
    started("//attacker.example/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/v1/auth/google/completion"
          ? Response.json({ matched: true })
          : Response.json(session),
      ),
    );
    await act(async () =>
      root.render(
        <AuthCompleteClient key="second" flow={flow} result="success" />,
      ),
    );
    await settle();
    expect(replace).toHaveBeenCalledWith("/");
  });
});
