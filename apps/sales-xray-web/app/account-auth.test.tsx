// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountAuth } from "./account-auth";
import { AUTH_COMPLETE_MESSAGE } from "./account-auth-client";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const file = { name: "Selected call.wav", size: 128 };
const config = { enabled: true, consent_version: "terms-v1", google_enabled: true, expires_in_seconds: 600, resend_after_seconds: 60 };
const identity = { authenticated: true, person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d", account_created: false, profile_complete: false };
const session = { person_id: identity.person_id, session_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45", selected_tenant_id: null, workspaces: [] };

async function flush() {
  await act(async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); });
}

async function changeInput(selector: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(selector)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(text: string) {
  const button = Array.from(host.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Missing button: ${text}`);
  await act(async () => button.click());
  await flush();
}

async function submit(selector = "form") {
  await act(async () => {
    host.querySelector<HTMLFormElement>(selector)!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  await flush();
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
  vi.restoreAllMocks();
});

it("renders all three local preview states without auth traffic or success callbacks", async () => {
  const fetcher = vi.fn();
  const onAuthenticated = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  for (const previewState of ["auth.email", "auth.code", "auth.error"] as const) {
    await act(async () => root.render(
      <AccountAuth key={previewState} selectedFile={file} onAuthenticated={onAuthenticated} previewState={previewState} />,
    ));
    await flush();
    expect(host.textContent).toContain(file.name);
    expect(host.textContent).toContain("not uploaded yet");
    if (previewState === "auth.code") expect(host.textContent).toContain("Check your email.");
    if (previewState === "auth.error") expect(host.textContent).toContain("temporarily unavailable");
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect(onAuthenticated).not.toHaveBeenCalled();
});

it("keeps the local file through explicit consent, neutral code request and verified account", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    if (url.includes("/config")) return Response.json(config);
    if (url.includes("/request")) return Response.json({ accepted: true, expires_in_seconds: 600, resend_after_seconds: 60 }, { status: 202 });
    if (url.includes("/verify")) return Response.json(identity);
    if (url === "/v1/me/workspaces") return Response.json(session);
    throw new Error(`Unexpected ${url}`);
  }));
  const onAuthenticated = vi.fn();
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />));
  await flush();
  expect(host.textContent).toContain(file.name);
  await changeInput("#account-email", "first@example.test");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await submit();
  expect(host.textContent).toContain("Check your email.");
  expect(host.textContent).toContain("If this address can receive a sign-in code");
  expect(host.textContent).toContain(file.name);
  const request = calls.find(({ url }) => url.endsWith("/request"))!;
  expect(JSON.parse(String(request.init.body))).toEqual({
    email: "first@example.test", consent: true, consent_version: "terms-v1",
    surface: "sales_xray", return_path: "/",
  });
  expect(onAuthenticated).not.toHaveBeenCalled();
  await changeInput("#account-code", "123 456");
  expect(host.querySelector<HTMLInputElement>("#account-code")?.value).toBe("123456");
  await submit();
  expect(onAuthenticated).toHaveBeenCalledOnce();
  expect(calls.map(({ url }) => url).slice(-2)).toEqual([
    "/v1/auth/email-code/verify", "/v1/me/workspaces",
  ]);
  expect(host.textContent).toContain(file.name);
});

it("rechecks a verified code's session without reposting or losing the file", async () => {
  let sessionReads = 0;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) return Response.json(config);
    if (url.endsWith("/request")) return Response.json({ accepted: true, expires_in_seconds: 600, resend_after_seconds: 60 }, { status: 202 });
    if (url.endsWith("/verify")) return Response.json(identity);
    if (url === "/v1/me/workspaces") {
      sessionReads += 1;
      return sessionReads === 1
        ? new Response(null, { status: 503 })
        : Response.json(session);
    }
    throw new Error(`Unexpected ${url}`);
  }));
  const onAuthenticated = vi.fn();
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />));
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await submit();
  await changeInput("#account-code", "123456");
  await submit();
  expect(onAuthenticated).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Check sign-in status");
  expect(host.textContent).toContain(file.name);
  await click("Check sign-in status");
  expect(onAuthenticated).toHaveBeenCalledOnce();
  expect(calls.filter((url) => url.endsWith("/verify"))).toHaveLength(1);
  expect(sessionReads).toBe(2);
});

it("refreshes changed consent and returns to email without losing the file or sending a code", async () => {
  let configs = 0;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) {
      configs += 1;
      return Response.json({ ...config, consent_version: configs === 1 ? "terms-v1" : "terms-v2" });
    }
    throw new Error(`Unexpected mutation: ${url}`);
  }));
  const onAuthenticated = vi.fn();
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />));
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await submit();
  expect(calls.filter((url) => url.endsWith("/request"))).toHaveLength(0);
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(false);
  expect(onAuthenticated).not.toHaveBeenCalled();
});

it("recovers when consent changes after preflight and the code request is rejected", async () => {
  let configs = 0;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) {
      configs += 1;
      return Response.json({ ...config, consent_version: configs < 3 ? "terms-v1" : "terms-v2" });
    }
    if (url.endsWith("/request")) return new Response(null, { status: 409 });
    throw new Error(`Unexpected ${url}`);
  }));
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />));
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await submit();
  expect(calls.filter((url) => url.includes("/config?"))).toHaveLength(3);
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(false);
});

it("keeps Google in a blank popup until fresh consent policy is confirmed", async () => {
  let configs = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/config")) {
      configs += 1;
      return Response.json({ ...config, consent_version: configs === 1 ? "terms-v1" : "terms-v2" });
    }
    throw new Error(`Unexpected ${url}`);
  }));
  const assign = vi.fn();
  const close = vi.fn();
  vi.stubGlobal("open", vi.fn().mockReturnValue({ close, location: { assign } }));
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />));
  await flush();
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await click("Continue with Google");
  expect(assign).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalled();
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(false);
});

it("signs an existing account in with a password in the same document", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) return Response.json(config);
    if (url === "/v1/auth/password/login") return Response.json({ authenticated: true });
    if (url === "/v1/me/workspaces") return Response.json(session);
    throw new Error(`Unexpected ${url}`);
  }));
  const onAuthenticated = vi.fn();
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />));
  await flush();
  await click("Use my existing password");
  await changeInput("#account-password-email", "existing@example.test");
  await changeInput("#account-password", "synthetic-password");
  await submit();
  expect(calls).toEqual(["/v1/auth/email-code/config?surface=sales_xray", "/v1/auth/password/login", "/v1/me/workspaces"]);
  expect(onAuthenticated).toHaveBeenCalledOnce();
  expect(host.textContent).toContain(file.name);
});

it("requires popup origin, source and flow before checking the canonical session", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.includes("/config")) return Response.json(config);
    if (url === "/v1/me/workspaces") return Response.json(session);
    throw new Error(`Unexpected ${url}`);
  }));
  const assign = vi.fn();
  const child = { close: vi.fn(), closed: false, location: { assign } } as unknown as Window;
  const open = vi.fn().mockReturnValue(child);
  vi.stubGlobal("open", open);
  const onAuthenticated = vi.fn();
  await act(async () => root.render(<AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />));
  await flush();
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await click("Continue with Google");
  expect(open.mock.calls[0][0]).toBe("about:blank");
  const url = new URL(assign.mock.calls[0][0], window.location.origin);
  const flow = new URLSearchParams(url.searchParams.get("return_path")?.split("?")[1]).get("flow")!;
  const send = async (origin: string, source: Window, candidate: string) => {
    await act(async () => window.dispatchEvent(new MessageEvent("message", {
      origin, source, data: { type: AUTH_COMPLETE_MESSAGE, flow: candidate },
    })));
    await flush();
  };
  await send("https://attacker.example", child, flow);
  await send(window.location.origin, window, flow);
  await send(window.location.origin, child, "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45");
  expect(calls).toEqual([
    "/v1/auth/email-code/config?surface=sales_xray",
    "/v1/auth/email-code/config?surface=sales_xray",
  ]);
  await send(window.location.origin, child, flow);
  expect(calls).toContain("/v1/me/workspaces");
  expect(onAuthenticated).toHaveBeenCalledOnce();
});
