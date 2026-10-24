// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountAuth } from "./account-auth";
import { FACEBOOK_NOT_READY } from "./account-auth-client";
import { AUTH_COMPLETE_MESSAGE } from "./account-auth-client";
import { ThemeProvider } from "./lightbox/theme-provider";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
const file = { name: "Selected call.wav", size: 128 };
const config = {
  enabled: true,
  consent_version: "terms-v1",
  google_enabled: true,
  expires_in_seconds: 600,
  resend_after_seconds: 60,
};
const identity = {
  authenticated: true,
  person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
  account_created: false,
  profile_complete: false,
};
const session = {
  person_id: identity.person_id,
  session_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
  selected_tenant_id: null,
  workspaces: [],
};

async function flush() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}

async function changeInput(selector: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(selector)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(text: string) {
  const button = Array.from(host.querySelectorAll("button")).find((item) =>
    item.textContent?.includes(text),
  );
  if (!button) throw new Error(`Missing button: ${text}`);
  await act(async () => button.click());
  await flush();
}

async function submit(selector = "form") {
  await act(async () => {
    host
      .querySelector<HTMLFormElement>(selector)!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
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
  for (const previewState of [
    "auth.email",
    "auth.code",
    "auth.error",
  ] as const) {
    await act(async () =>
      root.render(
        <AccountAuth
          key={previewState}
          selectedFile={file}
          onAuthenticated={onAuthenticated}
          previewState={previewState}
        />,
      ),
    );
    await flush();
    expect(host.textContent).toContain(file.name);
    expect(host.textContent).toContain("not uploaded yet");
    if (previewState === "auth.code")
      expect(host.textContent).toContain("Check your email.");
    if (previewState === "auth.error")
      expect(host.textContent).toContain(
        "Email code sign-in isn’t available right now.",
      );
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect(onAuthenticated).not.toHaveBeenCalled();
});

// /review-fixture/sign-in: a provider press goes to the fixture, never to the
// provider, and the password step has its own still view.
it("hands a provider press to the review fixture and opens nothing", async () => {
  const fetcher = vi.fn(async () =>
    Response.json({ ...config, facebook_enabled: true }),
  );
  const open = vi.fn();
  const reviewProvider = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("open", open);
  await act(async () =>
    root.render(
      <AccountAuth onAuthenticated={vi.fn()} reviewProvider={reviewProvider} />,
    ),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Facebook");
  expect(reviewProvider).toHaveBeenCalledExactlyOnceWith("facebook");
  expect(open).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () =>
    root.render(
      <AccountAuth onAuthenticated={vi.fn()} previewState="auth.password" />,
    ),
  );
  await flush();
  expect(host.querySelector("#account-password")).not.toBeNull();
  expect(
    host.querySelector<HTMLInputElement>("#account-password-email")?.value,
  ).toBe("sample@example.test");
});

it("returns to the staged call with the same selected file and no navigation", async () => {
  const onCancel = vi.fn();
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <AccountAuth
        selectedFile={file}
        onAuthenticated={vi.fn()}
        onCancel={onCancel}
        previewState="auth.email"
      />,
    ),
  );
  await flush();
  const back = Array.from(host.querySelectorAll("button")).find((item) =>
    item.textContent?.includes("Back to your call"),
  );
  expect(back).toBeTruthy();
  expect(host.querySelector('a[aria-label="Sales Xray home"]')).toBeNull();
  await act(async () => back!.click());
  expect(onCancel).toHaveBeenCalledExactlyOnceWith(file);
  expect(host.textContent).toContain(file.name);
  expect(fetcher).not.toHaveBeenCalled();
});

it("keeps the theme switch in its own slot so phones can float it onto the banner", async () => {
  vi.stubGlobal("fetch", vi.fn());
  await act(async () =>
    root.render(
      <ThemeProvider controlEnabled>
        <AccountAuth
          selectedFile={file}
          onAuthenticated={vi.fn()}
          previewState="auth.email"
        />
      </ThemeProvider>,
    ),
  );
  await flush();
  const toggle = host.querySelector<HTMLButtonElement>(
    'button[aria-label^="Theme:"]',
  );
  expect(toggle).toBeTruthy();
  const slot = toggle!.parentElement!;
  expect(slot.tagName).toBe("SPAN");
  expect(slot.className).toContain("themeSlot");
  expect(slot.parentElement?.className).toContain("formBar");
});

it("keeps the local file through explicit consent, neutral code request and verified account", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (url.includes("/config")) return Response.json(config);
      if (url.includes("/request"))
        return Response.json(
          { accepted: true, expires_in_seconds: 600, resend_after_seconds: 60 },
          { status: 202 },
        );
      if (url.includes("/verify")) return Response.json(identity);
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  expect(host.textContent).toContain(file.name);
  expect(
    host
      .querySelector('label input[type="checkbox"]')
      ?.parentElement?.textContent?.replace(/\s+/g, " ")
      .trim(),
  ).toBe(
    "I confirm that I am 18 or older and accept the current Authority Closers Terms and Privacy notice for my Authority Closers account.",
  );
  await changeInput("#account-email", "first@example.test");
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await submit();
  expect(host.textContent).toContain("Check your email.");
  expect(host.textContent).toContain(
    "If this address can receive a sign-in code",
  );
  expect(host.textContent).toContain(file.name);
  const request = calls.find(({ url }) => url.endsWith("/request"))!;
  expect(JSON.parse(String(request.init.body))).toEqual({
    email: "first@example.test",
    consent: true,
    age_attested: true,
    consent_version: "terms-v1",
    surface: "sales_xray",
    return_path: "/",
  });
  expect(onAuthenticated).not.toHaveBeenCalled();
  // The sixth digit verifies by itself, once.
  await changeInput("#account-code", "123 456");
  await flush();
  expect(onAuthenticated).toHaveBeenCalledOnce();
  expect(calls.filter(({ url }) => url.endsWith("/verify"))).toHaveLength(1);
  expect(calls.map(({ url }) => url).slice(-2)).toEqual([
    "/v1/auth/email-code/verify",
    "/v1/me/workspaces",
  ]);
  expect(host.textContent).toContain(file.name);
});

it("rechecks a verified code's session without reposting or losing the file", async () => {
  let sessionReads = 0;
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url.endsWith("/request"))
        return Response.json(
          { accepted: true, expires_in_seconds: 600, resend_after_seconds: 60 },
          { status: 202 },
        );
      if (url.endsWith("/verify")) return Response.json(identity);
      if (url === "/v1/me/workspaces") {
        sessionReads += 1;
        return sessionReads === 1
          ? new Response(null, { status: 503 })
          : Response.json(session);
      }
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
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
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) {
        configs += 1;
        return Response.json({
          ...config,
          consent_version: configs === 1 ? "terms-v1" : "terms-v2",
        });
      }
      throw new Error(`Unexpected mutation: ${url}`);
    }),
  );
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await submit();
  expect(calls.filter((url) => url.endsWith("/request"))).toHaveLength(0);
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked,
  ).toBe(false);
  expect(onAuthenticated).not.toHaveBeenCalled();
});

it("recovers when consent changes after preflight and the code request is rejected", async () => {
  let configs = 0;
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) {
        configs += 1;
        return Response.json({
          ...config,
          consent_version: configs < 3 ? "terms-v1" : "terms-v2",
        });
      }
      if (url.endsWith("/request")) return new Response(null, { status: 409 });
      throw new Error(`Unexpected ${url}`);
    }),
  );
  await act(async () =>
    root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />),
  );
  await flush();
  await changeInput("#account-email", "first@example.test");
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await submit();
  expect(calls.filter((url) => url.includes("/config?"))).toHaveLength(3);
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked,
  ).toBe(false);
});

it("keeps Google in a blank popup until fresh consent policy is confirmed", async () => {
  let configs = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/config")) {
        configs += 1;
        return Response.json({
          ...config,
          consent_version: configs === 1 ? "terms-v1" : "terms-v2",
        });
      }
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const assign = vi.fn();
  const close = vi.fn();
  const open = vi.fn().mockReturnValue({ close, location: { assign } });
  vi.stubGlobal("open", open);
  await act(async () =>
    root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />),
  );
  await flush();
  // Never greyed out (owner, 23 Oct 2026): pressing it before the box is
  // ticked points at the box and opens nothing.
  expect(
    Array.from(host.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Continue with Google"),
    )?.disabled,
  ).toBe(false);
  await click("Continue with Google");
  expect(open).not.toHaveBeenCalled();
  expect(host.querySelector("#account-consent-nudge")?.textContent).toBe(
    "Tick this box to continue.",
  );
  expect(
    host.querySelector('label[data-nudge="true"] input[type="checkbox"]'),
  ).toBeTruthy();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  expect(assign).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalled();
  expect(host.textContent).toContain("Terms or sign-in settings changed");
  expect(host.textContent).toContain(file.name);
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked,
  ).toBe(false);
});

it("signs an existing account in with a password in the same document", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url === "/v1/auth/password/login")
        return Response.json({ authenticated: true });
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await click("Use my existing password");
  await changeInput("#account-password-email", "existing@example.test");
  await changeInput("#account-password", "synthetic-password");
  await submit();
  expect(calls).toEqual([
    "/v1/auth/email-code/config?surface=sales_xray",
    "/v1/auth/password/login",
    "/v1/me/workspaces",
  ]);
  expect(onAuthenticated).toHaveBeenCalledOnce();
  expect(host.textContent).toContain(file.name);
});

it("toggles password visibility accessibly without copying the secret into component state", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes("/config")) return Response.json(config);
    throw new Error(`Unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />),
  );
  await flush();
  await click("Use my existing password");
  const password = host.querySelector<HTMLInputElement>("#account-password")!;
  const toggle = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Show password"]',
  )!;
  expect(password.type).toBe("password");
  expect(toggle.getAttribute("aria-pressed")).toBe("false");
  await changeInput("#account-password", "synthetic-password");
  await act(async () => toggle.click());
  await flush();
  expect(password.type).toBe("text");
  expect(password.value).toBe("synthetic-password");
  expect(
    host
      .querySelector('button[aria-label="Hide password"]')
      ?.getAttribute("aria-pressed"),
  ).toBe("true");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label="Hide password"]')!
      .click(),
  );
  await flush();
  expect(password.type).toBe("password");
  expect(password.value).toBe("synthetic-password");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain("synthetic-password");
});

it("requires popup origin, source and flow before checking the canonical session", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url === "/v1/auth/google/completion")
        return Response.json({ matched: true });
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const assign = vi.fn();
  const child = {
    close: vi.fn(),
    closed: false,
    location: { assign },
  } as unknown as Window;
  const open = vi.fn().mockReturnValue(child);
  vi.stubGlobal("open", open);
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  expect(open.mock.calls[0][0]).toBe("about:blank");
  const url = new URL(assign.mock.calls[0][0], window.location.origin);
  const flow = new URLSearchParams(
    url.searchParams.get("return_path")?.split("?")[1],
  ).get("flow")!;
  expect(url.searchParams.get("consent")).toBe("true");
  expect(url.searchParams.get("age_attested")).toBe("true");
  expect(url.searchParams.get("consent_version")).toBe("terms-v1");
  expect(url.searchParams.get("action")).toBe("authenticate");
  const send = async (origin: string, source: Window, candidate: string) => {
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          origin,
          source,
          data: {
            type: AUTH_COMPLETE_MESSAGE,
            flow: candidate,
            auth_result: "success",
          },
        }),
      ),
    );
    await flush();
  };
  await send("https://attacker.example", child, flow);
  await send(window.location.origin, window, flow);
  await send(
    window.location.origin,
    child,
    "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
  );
  expect(calls).toEqual([
    "/v1/auth/email-code/config?surface=sales_xray",
    "/v1/auth/email-code/config?surface=sales_xray",
  ]);
  await send(window.location.origin, child, flow);
  expect(calls.slice(-2)).toEqual([
    "/v1/auth/google/completion",
    "/v1/me/workspaces",
  ]);
  expect(onAuthenticated).toHaveBeenCalledOnce();
});

it("keeps Google available when email codes are independently disabled", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config"))
        return Response.json({ ...config, enabled: false });
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const assign = vi.fn();
  vi.stubGlobal(
    "open",
    vi.fn().mockReturnValue({ close: vi.fn(), location: { assign } }),
  );
  await act(async () =>
    root.render(<AccountAuth selectedFile={file} onAuthenticated={vi.fn()} />),
  );
  await flush();
  expect(host.textContent).toContain(
    "Email code sign-in isn’t available right now.",
  );
  expect(host.textContent).toContain("Continue with Google");
  expect(host.textContent).toContain("Use my existing password");
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  expect(assign).toHaveBeenCalledOnce();
  expect(calls).not.toContain("/v1/auth/email-code/request");
});

it("does not complete Google from an old session when the receipt is unmatched", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url === "/v1/auth/google/completion")
        return Response.json({ matched: false });
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const child = {
    close: vi.fn(),
    location: { assign: vi.fn() },
  } as unknown as Window;
  vi.stubGlobal("open", vi.fn().mockReturnValue(child));
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  const started = new URL(
    vi.mocked(child.location.assign).mock.calls[0][0],
    window.location.origin,
  );
  const flow = new URLSearchParams(
    started.searchParams.get("return_path")!.split("?")[1],
  ).get("flow")!;
  await act(async () =>
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: child,
        data: { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "success" },
      }),
    ),
  );
  await flush();
  expect(calls).toContain("/v1/auth/google/completion");
  expect(calls).not.toContain("/v1/me/workspaces");
  expect(onAuthenticated).not.toHaveBeenCalled();
  expect(host.textContent).toContain("could not be confirmed");
});

it("treats review_terms as terminal and clears the acknowledgement without reading an old session", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const child = {
    close: vi.fn(),
    location: { assign: vi.fn() },
  } as unknown as Window;
  vi.stubGlobal("open", vi.fn().mockReturnValue(child));
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  const started = new URL(
    vi.mocked(child.location.assign).mock.calls[0][0],
    window.location.origin,
  );
  const flow = new URLSearchParams(
    started.searchParams.get("return_path")!.split("?")[1],
  ).get("flow")!;
  await act(async () =>
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: child,
        data: {
          type: AUTH_COMPLETE_MESSAGE,
          flow,
          auth_result: "review_terms",
        },
      }),
    ),
  );
  await flush();
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked,
  ).toBe(false);
  expect(host.textContent).toContain(
    "Review the current Terms and Privacy notice",
  );
  expect(calls).not.toContain("/v1/me/workspaces");
  expect(calls).not.toContain("/v1/auth/google/completion");
  expect(onAuthenticated).not.toHaveBeenCalled();
});

it("manual Google recovery waits for the exact callback and the matching receipt", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("/config")) return Response.json(config);
      if (url === "/v1/auth/google/completion")
        return Response.json({ matched: true });
      if (url === "/v1/me/workspaces") return Response.json(session);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const child = {
    close: vi.fn(),
    location: { href: "about:blank", assign: vi.fn() },
  };
  vi.stubGlobal("open", vi.fn().mockReturnValue(child));
  const onAuthenticated = vi.fn();
  await act(async () =>
    root.render(
      <AccountAuth selectedFile={file} onAuthenticated={onAuthenticated} />,
    ),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Continue with Google");
  const started = new URL(
    child.location.assign.mock.calls[0][0],
    window.location.origin,
  );
  const flow = new URLSearchParams(
    started.searchParams.get("return_path")!.split("?")[1],
  ).get("flow")!;
  await click("I finished Google sign-in");
  expect(calls).not.toContain("/v1/auth/google/completion");
  expect(calls).not.toContain("/v1/me/workspaces");
  expect(onAuthenticated).not.toHaveBeenCalled();
  child.location.href = `${window.location.origin}/auth/complete?flow=${flow}&auth_result=success`;
  await click("I finished Google sign-in");
  expect(calls.slice(-2)).toEqual([
    "/v1/auth/google/completion",
    "/v1/me/workspaces",
  ]);
  expect(onAuthenticated).toHaveBeenCalledOnce();
});

describe("when the sign-in window is blocked", () => {
  beforeEach(() => window.sessionStorage.clear());

  async function consentAndContinue() {
    await act(async () =>
      host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
    );
    await click("Continue with Google");
  }

  it("signs in on this page with the same click and remembers where it started", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/config")) return Response.json(config);
        throw new Error(`Unexpected ${url}`);
      }),
    );
    const open = vi.fn().mockReturnValue(null);
    vi.stubGlobal("open", open);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    window.history.replaceState(null, "", "/login?next=/leads");
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    await consentAndContinue();
    expect(open).toHaveBeenCalledOnce();
    const started = new URL(navigate.mock.calls[0][0] as string);
    expect(started.origin).toBe(window.location.origin);
    expect(started.pathname).toBe("/v1/auth/google/start");
    expect(started.searchParams.get("consent_version")).toBe("terms-v1");
    const flow = new URLSearchParams(
      started.searchParams.get("return_path")!.split("?")[1],
    ).get("flow")!;
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.redirect")!),
    ).toMatchObject({
      flow,
      provider: "google",
      returnTo: "/login?next=/leads",
    });
    expect(host.textContent).toContain("Opening Google sign-in…");
    expect(host.textContent).not.toContain("Allow the sign-in window");
  });

  it("never opens a window inside Facebook's or Instagram's in-app browser", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(config)),
    );
    vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(
      "Mozilla/5.0 (iPhone) AppleWebKit Mobile/15E148 Instagram 312.0.0.32.112",
    );
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    await consentAndContinue();
    expect(open).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledOnce();
  });

  it("finishes on return only after the account session reads back", async () => {
    window.sessionStorage.setItem(
      "sx.signIn.result",
      JSON.stringify({ result: "success", provider: "google", at: Date.now() }),
    );
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        if (url.includes("/config")) return Response.json(config);
        if (url === "/v1/me/workspaces") return Response.json(session);
        throw new Error(`Unexpected ${url}`);
      }),
    );
    const onAuthenticated = vi.fn();
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={onAuthenticated} />),
    );
    await flush();
    expect(calls).toContain("/v1/me/workspaces");
    expect(onAuthenticated).toHaveBeenCalledOnce();
    expect(window.sessionStorage.getItem("sx.signIn.result")).toBeNull();
  });

  it("shows a failed return as a corner card and reads no session", async () => {
    window.sessionStorage.setItem(
      "sx.signIn.result",
      JSON.stringify({ result: "failed", provider: "google", at: Date.now() }),
    );
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return Response.json(config);
      }),
    );
    const onAuthenticated = vi.fn();
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={onAuthenticated} />),
    );
    await flush();
    const card = host.querySelector('[role="alert"]')!;
    expect(card.textContent).toContain("Google sign-in could not be completed");
    expect(calls).not.toContain("/v1/me/workspaces");
    expect(onAuthenticated).not.toHaveBeenCalled();
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!
        .click(),
    );
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("Apple and Facebook next to Google", () => {
  const everything = { ...config, apple_enabled: true, facebook_enabled: true };

  beforeEach(() => window.sessionStorage.clear());
  afterEach(() => {
    delete (globalThis as { SXPhone?: unknown }).SXPhone;
  });

  function providerButtons() {
    return Array.from(host.querySelectorAll("button"))
      .map((button) => button.textContent?.trim() ?? "")
      .filter((text) => text.startsWith("Continue with"));
  }

  it("offers Google, Apple, Facebook in that order, each only when configured", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(everything)),
    );
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    expect(providerButtons()).toEqual([
      "Continue with Google",
      "Continue with Apple",
      "Continue with Facebook",
    ]);
    // Nothing waits behind a greyed-out button: no "tick the box" line yet.
    expect(host.querySelector("#account-consent-nudge")).toBeNull();
    const text = host.textContent ?? "";
    expect(text.indexOf("Continue with Facebook")).toBeLessThan(
      text.indexOf("or use email"),
    );
    await act(async () => root.unmount());
    root = createRoot(host);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ ...config, facebook_enabled: true })),
    );
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    expect(providerButtons()).toEqual([
      "Continue with Google",
      "Continue with Facebook",
    ]);
  });

  it("starts Facebook in the sign-in window on its own start path", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(everything)),
    );
    const assign = vi.fn();
    vi.stubGlobal(
      "open",
      vi.fn().mockReturnValue({
        close: vi.fn(),
        closed: false,
        location: { assign },
      }),
    );
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    await act(async () =>
      host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
    );
    await click("Continue with Facebook");
    const started = new URL(assign.mock.calls[0][0], window.location.origin);
    expect(started.pathname).toBe("/v1/auth/facebook/start");
    expect(started.searchParams.get("surface")).toBe("sales_xray");
    expect(host.textContent).toContain(
      "Finish sign-in in the Facebook window.",
    );
  });

  it("tells an older phone app to update before Apple or Facebook, and never opens a window", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(everything)),
    );
    const listeners: ((event: { data: unknown }) => void)[] = [];
    (globalThis as { SXPhone?: unknown }).SXPhone = {
      addEventListener: (
        _type: string,
        listener: (event: { data: unknown }) => void,
      ) => listeners.push(listener),
      postMessage: (raw: string) => {
        const message = JSON.parse(raw) as { id: string };
        queueMicrotask(() =>
          listeners.forEach((listener) =>
            listener({
              data: JSON.stringify({
                id: message.id,
                ok: true,
                result: { platform: "android", connect: true },
              }),
            }),
          ),
        );
      },
    };
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    await act(async () =>
      host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
    );
    await click("Continue with Apple");
    await flush();
    expect(open).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    expect(host.querySelector('p[role="alert"]')?.textContent).toContain(
      "Update the Sales X-Ray app to sign in with Apple",
    );
  });

  it("explains an email that already has an account, and a provider that shared none", async () => {
    for (const [result, provider, words] of [
      [
        "account_exists",
        "facebook",
        "This email already has an Authority Closers account",
      ],
      ["no_email", "facebook", "Facebook didn’t share your email address"],
      ["no_email", "apple", "Apple didn’t share your email address"],
    ] as const) {
      window.sessionStorage.setItem(
        "sx.signIn.result",
        JSON.stringify({ result, provider, at: Date.now() }),
      );
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => Response.json(everything)),
      );
      await act(async () =>
        root.render(
          <AccountAuth key={result + provider} onAuthenticated={vi.fn()} />,
        ),
      );
      await flush();
      expect(host.querySelector('p[role="alert"]')?.textContent).toContain(
        words,
      );
      // Staff never get email codes, so the card names no sign-in method.
      if (result === "account_exists")
        expect(
          host.querySelector('p[role="alert"]')?.textContent,
        ).not.toContain("email code");
    }
  });
});

it("keeps a full-page sign-in result through React's double effect run in development", async () => {
  window.sessionStorage.setItem(
    "sx.signIn.result",
    JSON.stringify({ result: "failed", provider: "google", at: Date.now() }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(config)),
  );
  await act(async () =>
    root.render(
      <StrictMode>
        <AccountAuth onAuthenticated={vi.fn()} />
      </StrictMode>,
    ),
  );
  await flush();
  expect(host.querySelector('p[role="alert"]')?.textContent).toContain(
    "Google sign-in could not be completed",
  );
  expect(window.sessionStorage.getItem("sx.signIn.result")).toBeNull();
});

describe("inside the Sales X-Ray phone app", () => {
  type PhoneMessage = {
    id: string;
    method: string;
    args: Record<string, unknown>;
  };

  function phoneApp(
    signIn: (args: Record<string, unknown>) => {
      ok: boolean;
      result?: unknown;
      error?: string;
    },
  ) {
    const listeners: ((event: { data: unknown }) => void)[] = [];
    const asked: PhoneMessage[] = [];
    vi.stubGlobal("SXPhone", {
      addEventListener: (
        _: string,
        listener: (event: { data: unknown }) => void,
      ) => listeners.push(listener),
      postMessage: (data: string) => {
        const message = JSON.parse(data) as PhoneMessage;
        asked.push(message);
        const answer =
          message.method === "status"
            ? {
                ok: true,
                result: { signIn: true, nativeSignIn: ["google", "facebook"] },
              }
            : signIn(message.args);
        queueMicrotask(() =>
          listeners.forEach((listener) =>
            listener({ data: JSON.stringify({ id: message.id, ...answer }) }),
          ),
        );
      },
    });
    return asked;
  }

  const STATE = "s".repeat(43);

  function server(start: Response | (() => Response)) {
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/config"))
        return Response.json({ ...config, facebook_enabled: true });
      if (url.includes("/native/start"))
        return typeof start === "function" ? start() : start.clone();
      throw new Error(`Unexpected ${url} ${init?.method}`);
    });
    vi.stubGlobal("fetch", fetcher);
    return fetcher;
  }

  async function signIn(provider: "Google" | "Facebook") {
    await act(async () =>
      root.render(<AccountAuth onAuthenticated={vi.fn()} />),
    );
    await flush();
    await act(async () =>
      host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
    );
    await click(`Continue with ${provider}`);
    await flush();
  }

  it("signs in with the phone's own Google sheet and posts its token, never a browser", async () => {
    const fetcher = server(
      Response.json({
        state: STATE,
        nonce: "nonce-1",
        client_id: "web-client-id",
      }),
    );
    const asked = phoneApp(() => ({
      ok: true,
      result: { token: "id.token.value" },
    }));
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    const posted: HTMLFormElement[] = [];
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(function (
      this: HTMLFormElement,
    ) {
      posted.push(this);
    });
    window.history.replaceState(null, "", "/login?next=/leads");

    await signIn("Google");

    expect(open).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    const [url, init] = fetcher.mock.calls.find(([called]) =>
      called.includes("/native/start"),
    )!;
    expect(url).toBe("/v1/auth/google/native/start");
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({
      action: "authenticate",
      consent: true,
      age_attested: true,
      consent_version: "terms-v1",
    });
    const flow = new URLSearchParams(body.return_path.split("?")[1]).get(
      "flow",
    );
    expect(
      asked.find((message) => message.method === "nativeSignIn")?.args,
    ).toEqual({
      provider: "google",
      nonce: "nonce-1",
      clientId: "web-client-id",
    });
    expect(posted).toHaveLength(1);
    expect(posted[0].method.toLowerCase()).toBe("post");
    expect(new URL(posted[0].action).pathname).toBe(
      "/v1/auth/google/native/finish",
    );
    expect(Object.fromEntries(new FormData(posted[0]))).toEqual({
      state: STATE,
      token: "id.token.value",
    });
    expect(
      JSON.parse(window.sessionStorage.getItem("sx.signIn.redirect")!),
    ).toMatchObject({
      flow,
      provider: "google",
      returnTo: "/login?next=/leads",
    });
  });

  it("starts the Facebook SDK with this environment's app id and client token", async () => {
    server(
      Response.json({
        state: STATE,
        nonce: "nonce-2",
        app_id: "1514054053884522",
        client_token: "client-token",
      }),
    );
    const asked = phoneApp(() => ({
      ok: true,
      result: { token: "EAAG-token" },
    }));
    const posted: HTMLFormElement[] = [];
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(function (
      this: HTMLFormElement,
    ) {
      posted.push(this);
    });

    await signIn("Facebook");

    expect(
      asked.find((message) => message.method === "nativeSignIn")?.args,
    ).toEqual({
      provider: "facebook",
      nonce: "nonce-2",
      appId: "1514054053884522",
      clientToken: "client-token",
    });
    expect(new URL(posted[0].action).pathname).toBe(
      "/v1/auth/facebook/native/finish",
    );
  });

  it("a closed sheet just lets the person choose again, with no message", async () => {
    server(Response.json({ state: STATE, nonce: "n", client_id: "c" }));
    phoneApp(() => ({ ok: false, error: "cancelled" }));
    const submit = vi
      .spyOn(HTMLFormElement.prototype, "submit")
      .mockImplementation(() => {});

    await signIn("Google");

    expect(submit).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')?.textContent ?? "").toBe("");
    const google = Array.from(host.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Continue with Google"),
    )!;
    expect(google.disabled).toBe(false);
  });

  it("says what to do when the phone has no Google account", async () => {
    server(Response.json({ state: STATE, nonce: "n", client_id: "c" }));
    phoneApp(() => ({ ok: false, error: "no_account" }));
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => {});

    await signIn("Google");

    expect(host.textContent).toContain("Add a Google account to this phone");
  });

  // Owner via the orchestrator, 24 Oct 2026: Facebook never jumps to Chrome.
  it("says Facebook isn't ready on this phone, and never opens the browser, when the server can't start it", async () => {
    server(() => new Response(null, { status: 503 }));
    const asked = phoneApp(() => ({ ok: true, result: { token: "unused" } }));
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});
    const open = vi.fn();
    vi.stubGlobal("open", open);

    await signIn("Facebook");

    expect(navigate).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(asked.some((message) => message.method === "nativeSignIn")).toBe(
      false,
    );
    expect(host.textContent).toContain(FACEBOOK_NOT_READY);
    const facebook = Array.from(host.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Continue with Facebook"),
    )!;
    expect(facebook.disabled).toBe(false);
  });

  it("says the same when the Facebook SDK can't start on the phone", async () => {
    server(
      Response.json({
        state: STATE,
        nonce: "n",
        app_id: "1514054053884522",
        client_token: "client-token",
      }),
    );
    phoneApp(() => ({ ok: false, error: "unavailable" }));
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});

    await signIn("Facebook");

    expect(navigate).not.toHaveBeenCalled();
    expect(host.textContent).toContain(FACEBOOK_NOT_READY);
  });

  it("uses the phone's browser as before where this environment can't sign in on the phone", async () => {
    server(() => new Response(null, { status: 503 }));
    const asked = phoneApp(() => ({ ok: true, result: { token: "unused" } }));
    const navigate = vi
      .spyOn(window.location, "assign")
      .mockImplementation(() => {});

    await signIn("Google");

    expect(asked.some((message) => message.method === "nativeSignIn")).toBe(
      false,
    );
    expect(new URL(navigate.mock.calls[0][0] as string).pathname).toBe(
      "/v1/auth/google/start",
    );
  });
});
