// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import { HANDOFF_VERIFIER_KEY } from "../../lib/cross-app-handoff";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
const router = { replace };
vi.mock("next/navigation", () => ({ useRouter: () => router }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  replace.mockReset();
  window.history.replaceState(
    { next: "retained" },
    "",
    "/auth/handoff#code=sealed-code",
  );
  sessionStorage.setItem(HANDOFF_VERIFIER_KEY, "a".repeat(43));
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function respond(data: unknown, status = 200) {
  return vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(data), { status }),
  );
}
it.each([
  ["success", "/activity/example", "/activity/example"],
  [
    "consent_required",
    "/learning?tab=mine",
    "/consent/renewal?return=%2Flearning%3Ftab%3Dmine",
  ],
  ["consent_update_required", "/home", "/consent/renewal?return=%2Fhome"],
])(
  "routes %s and clears fragment before redeem",
  async (result, return_path, expected) => {
    const fetch = respond({ result, return_path });
    fetch.mockImplementationOnce(async () => {
      expect(window.location.hash).toBe("");
      expect(window.history.state).toEqual({ next: "retained" });
      expect(sessionStorage.getItem(HANDOFF_VERIFIER_KEY)).toBe("a".repeat(43));
      return new Response(JSON.stringify({ result, return_path }));
    });
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <StrictMode>
          <Page />
        </StrictMode>,
      ),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      code: "sealed-code",
      verifier: "a".repeat(43),
    });
    expect(replace).toHaveBeenCalledExactlyOnceWith(expected);
    expect(sessionStorage.getItem(HANDOFF_VERIFIER_KEY)).toBeNull();
  },
);
it("retains the verifier until the single StrictMode request settles", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  await act(async () =>
    root.render(
      <StrictMode>
        <Page />
      </StrictMode>,
    ),
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(HANDOFF_VERIFIER_KEY)).toBe("a".repeat(43));
  expect(replace).not.toHaveBeenCalled();
  await act(async () =>
    resolve(
      new Response(JSON.stringify({ result: "success", return_path: "/home" })),
    ),
  );
  expect(sessionStorage.getItem(HANDOFF_VERIFIER_KEY)).toBeNull();
  expect(replace).toHaveBeenCalledExactlyOnceWith("/home");
});
it.each([
  [400, { detail: "expired" }],
  [200, { result: "other", return_path: "/home" }],
  [200, { result: "success", return_path: "//evil.test" }],
  [200, {}],
])(
  "routes failed or invalid response to the calm expiry card",
  async (status, body) => {
    vi.stubGlobal("fetch", respond(body, status));
    await act(async () =>
      root.render(
        <StrictMode>
          <Page />
        </StrictMode>,
      ),
    );
    expect(replace).toHaveBeenCalledExactlyOnceWith("/login?handoff=expired");
  },
);
it.each(["code", "verifier"])(
  "missing %s never makes a request",
  async (missing) => {
    if (missing === "code")
      window.history.replaceState({}, "", "/auth/handoff#untrusted=data");
    else sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    await act(async () =>
      root.render(
        <StrictMode>
          <Page />
        </StrictMode>,
      ),
    );
    expect(fetch).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
    expect(replace).toHaveBeenCalledExactlyOnceWith("/login?handoff=expired");
  },
);
it("network failure clears credentials and returns to sign-in", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("offline");
    }),
  );
  await act(async () =>
    root.render(
      <StrictMode>
        <Page />
      </StrictMode>,
    ),
  );
  expect(sessionStorage.getItem(HANDOFF_VERIFIER_KEY)).toBeNull();
  expect(replace).toHaveBeenCalledExactlyOnceWith("/login?handoff=expired");
});
