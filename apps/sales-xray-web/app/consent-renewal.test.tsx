// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ConsentRenewal } from "./consent-renewal";
import { dismissNotice, NoticeCenter } from "./notice-center";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const WORDS =
  "I confirm that I am 18 or older and accept the current Authority Closers Terms and Privacy notice for my Authority Closers account.";
const SERVER_VERSION = "ac-learner-terms-privacy-2099-01-01-v9";

function answer(
  status: "current" | "renewal_required" | "consent_required",
  version = SERVER_VERSION,
  words = WORDS,
) {
  return {
    status,
    current_version: version,
    recorded_version: status === "consent_required" ? null : "an-older-version",
    consented_at: status === "current" ? "2026-10-18T10:00:00Z" : null,
    replayed: false,
    document: {
      version,
      acknowledgement: words,
      terms_path: "/terms",
      privacy_path: "/privacy",
    },
  };
}

const signedIn: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: { personId: "p1", sessionId: "s1", tenantId: "t1" },
  retry: () => {},
};
const signedOut: WorkspaceAccessValue = {
  status: "unauthenticated",
  authenticated: false,
  context: null,
  retry: () => {},
};

let root: Root;
let host: HTMLDivElement;
let calls: { method: string; path: string; body: unknown }[];

/** Replies in order to the next requests; a missing reply is a lost network. */
function server(replies: (Response | Error | Promise<Response>)[]) {
  calls = [];
  const queue = [...replies];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push({
        method: init?.method ?? "GET",
        path,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      const next = queue.shift();
      if (!next || next instanceof Error) throw next ?? new Error("offline");
      return next;
    }),
  );
}
const json = (body: unknown, status = 200) => Response.json(body, { status });

async function mount(value: WorkspaceAccessValue = signedIn) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={value}>
        <ConsentRenewal />
        <NoticeCenter />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
const card = () => host.querySelector<HTMLElement>('[role="dialog"]');
const checkbox = () => host.querySelector<HTMLInputElement>("input")!;
const accept = () =>
  host.querySelector<HTMLButtonElement>('button[type="submit"]')!;
const corner = () => host.querySelector<HTMLElement>("[data-tone]");
const cornerButton = (label: string) =>
  Array.from(host.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
    b.textContent?.includes(label),
  );
async function tick(ms = 0) {
  await act(async () => {
    await new Promise((done) => setTimeout(done, ms));
  });
}
async function agreeAndAccept() {
  await act(async () => checkbox().click());
  await act(async () => accept().click());
  await tick();
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  dismissNotice("consent-read");
  dismissNotice("consent-save");
  vi.unstubAllGlobals();
});

it("asks a signed-in person whose consent needs renewing, in plain words", async () => {
  server([json(answer("renewal_required"))]);
  await mount();
  const dialog = card()!;
  expect(dialog).not.toBeNull();
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(dialog.querySelector("h2")?.textContent).toBe(
    "We've updated our terms",
  );
  expect(dialog.textContent).toContain(WORDS);
  const links = Array.from(dialog.querySelectorAll("a"));
  expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Terms", "/terms"],
    ["Privacy notice", "/privacy"],
  ]);
  expect(checkbox().checked).toBe(false);
  expect(accept().disabled).toBe(true);
  expect(calls).toEqual([
    { method: "GET", path: "/v1/me/consent", body: null },
  ]);
  expect(document.documentElement.hasAttribute("data-sx-consent")).toBe(true);
});

it("asks a person with no consent on record, with its own title", async () => {
  server([json(answer("consent_required"))]);
  await mount();
  expect(card()?.querySelector("h2")?.textContent).toBe(
    "Accept our terms to continue",
  );
  expect(card()?.getAttribute("data-consent-status")).toBe("consent_required");
});

it("shows nothing at all when consent is current", async () => {
  server([json(answer("current"))]);
  await mount();
  expect(card()).toBeNull();
  expect(corner()).toBeNull();
  expect(host.querySelector("input, form, h2")).toBeNull();
  expect(document.documentElement.hasAttribute("data-sx-consent")).toBe(false);
});

it("does not ask, or even read, before sign-in is confirmed", async () => {
  server([]);
  await mount(signedOut);
  expect(card()).toBeNull();
  expect(calls).toEqual([]);
});

it("stays quiet when the account cannot be asked (401, 403)", async () => {
  for (const status of [401, 403]) {
    server([json({ code: "no" }, status)]);
    await mount();
    expect(card()).toBeNull();
    expect(corner()).toBeNull();
    await act(async () => root.render(<></>));
  }
});

it("never shows one person's card to the next person who signs in", async () => {
  server([
    json(answer("renewal_required")),
    new Promise<Response>(() => {}), // the next person's answer is still coming
  ]);
  await mount();
  expect(card()).not.toBeNull();
  await mount({
    ...signedIn,
    context: { personId: "p2", sessionId: "s2", tenantId: "t1" },
  });
  expect(card()).toBeNull();
  expect(document.documentElement.hasAttribute("data-sx-consent")).toBe(false);
});

it("accepts with the server's version, then returns to the page", async () => {
  server([
    json(answer("renewal_required")),
    json({ ...answer("current"), replayed: false }),
  ]);
  await mount();
  await act(async () => checkbox().click());
  expect(accept().disabled).toBe(false);
  await act(async () => accept().click());
  await tick();
  expect(calls[1]).toEqual({
    method: "POST",
    path: "/v1/me/consent/renew",
    body: { accepted: true, expected_version: SERVER_VERSION },
  });
  expect(card()).toBeNull();
  expect(document.documentElement.hasAttribute("data-sx-consent")).toBe(false);
  expect(calls).toHaveLength(2);
});

it("does not send an answer until the box is ticked", async () => {
  server([json(answer("renewal_required"))]);
  await mount();
  await act(async () => accept().click());
  await act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(calls).toHaveLength(1);
});

it("cannot be dismissed with Escape", async () => {
  server([json(answer("renewal_required"))]);
  await mount();
  const escape = new KeyboardEvent("keydown", {
    key: "Escape",
    bubbles: true,
    cancelable: true,
  });
  await act(async () => {
    card()!.dispatchEvent(escape);
  });
  expect(escape.defaultPrevented).toBe(true);
  expect(card()).not.toBeNull();
});

it("shows a failed save as a corner card, keeps the card, and retries", async () => {
  server([
    json(answer("renewal_required")),
    json({ code: "boom" }, 500),
    json(answer("current")),
  ]);
  await mount();
  await agreeAndAccept();
  expect(card()).not.toBeNull();
  const notice = corner()!;
  expect(notice.getAttribute("data-tone")).toBe("error");
  expect(notice.textContent).toContain("Couldn't save your answer");
  expect(card()!.contains(notice)).toBe(false);
  expect(accept().disabled).toBe(false);
  // The card is still ticked, and Try again sends the same version.
  expect(checkbox().checked).toBe(true);
  await act(async () => cornerButton("Try again")!.click());
  await tick();
  expect(calls.map((c) => c.method)).toEqual(["GET", "POST", "POST"]);
  expect(calls[2].body).toEqual({
    accepted: true,
    expected_version: SERVER_VERSION,
  });
  expect(card()).toBeNull();
  expect(corner()).toBeNull();
});

it("treats a lost connection like any failed save", async () => {
  server([json(answer("renewal_required")), new Error("offline")]);
  await mount();
  await agreeAndAccept();
  expect(corner()?.textContent).toContain("Couldn't save your answer");
  expect(card()).not.toBeNull();
});

it("shows the new words, unticked, when the version changed while reading", async () => {
  const NEWER = "ac-learner-terms-privacy-2099-02-02-v10";
  server([
    json(answer("renewal_required")),
    json({ code: "learner_consent_version_conflict" }, 409),
    json(answer("renewal_required", NEWER, "These are the newer words.")),
    json(answer("current", NEWER, "These are the newer words.")),
  ]);
  await mount();
  await agreeAndAccept();
  expect(card()?.textContent).toContain("These are the newer words.");
  expect(card()?.getAttribute("data-consent-version")).toBe(NEWER);
  expect(checkbox().checked).toBe(false);
  expect(corner()?.textContent).toContain("The Terms were just updated");
  await agreeAndAccept();
  expect(calls[3].body).toEqual({ accepted: true, expected_version: NEWER });
  expect(card()).toBeNull();
});

it("explains an account that cannot accept, without offering a retry", async () => {
  server([json(answer("renewal_required")), json({ code: "denied" }, 403)]);
  await mount();
  await agreeAndAccept();
  expect(corner()?.textContent).toContain("This account can't accept here");
  expect(cornerButton("Try again")).toBeUndefined();
});

it("shows a failed check as a corner card and shows the card when retried", async () => {
  server([json({ code: "boom" }, 500), json(answer("renewal_required"))]);
  await mount();
  expect(card()).toBeNull();
  expect(corner()?.textContent).toContain("Couldn't check the Terms");
  await act(async () => cornerButton("Try again")!.click());
  await tick();
  expect(card()).not.toBeNull();
  expect(corner()).toBeNull();
});
