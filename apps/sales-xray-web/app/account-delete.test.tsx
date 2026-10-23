// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/settings/security",
}));
vi.mock("next/link", () => ({
  default: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} />
  ),
}));

import { AccountSettings } from "./account-settings";
import { UploadSessionProvider } from "./hooks/upload-session";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Delete account (Google Play, 23 Oct 2026): apps with sign-up must let people
// start deletion in the app. It says what happens, then asks one thing at a
// time; with DELETE typed the server closes the account and signs it out.
let root: Root;
let host: HTMLDivElement;
let sent: { method: string; path: string; body?: unknown }[];
let preview: Record<string, unknown>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

const ready = {
  confirm_word: "DELETE",
  fresh_sign_in: true,
  fresh_minutes: 10,
  staff: false,
  transfer_first: [],
  closes_with_account: [],
};

beforeEach(() => {
  sent = [];
  preview = { ...ready };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      sent.push({
        method,
        path,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (path === "/v1/me/sales-xray-profile")
        return json({
          name: "Asha Rao",
          email: "asha@example.invalid",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: false,
          revision: 1,
        });
      if (path === "/v1/me/account-deletion")
        return method === "POST"
          ? json({ closed: true, requested_at: "2026-10-23T15:05:00Z" })
          : json(preview);
      return json({}, 404);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
  });
}

async function openDelete() {
  await act(async () =>
    root.render(
      <UploadSessionProvider>
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            context: { personId: "p", sessionId: "s", tenantId: "t" },
            retry: () => {},
          }}
        >
          <AccountSettings only={["security"]} />
        </WorkspaceAccessProvider>
      </UploadSessionProvider>,
    ),
  );
  await settle();
  const button = Array.from(host.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === "Delete account",
  )!;
  expect(button.getAttribute("aria-expanded")).toBe("false");
  await act(async () => button.click());
  await settle();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  return host.querySelector<HTMLElement>(
    '[role="region"][aria-label="Delete account"]',
  )!;
}

function buttonNamed(scope: ParentNode, name: string) {
  return Array.from(scope.querySelectorAll("button")).find((item) =>
    item.textContent?.includes(name),
  );
}

it("says what is deleted, and deletes only once DELETE is typed", async () => {
  preview = {
    ...ready,
    closes_with_account: [{ id: "o1", name: "Solo Desk" }],
  };
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => undefined);
  const region = await openDelete();
  expect(region.textContent).toContain(
    "Your account closes at once and you’re signed out on every device.",
  );
  expect(region.textContent).toContain(
    "Your recordings, transcripts and reports",
  );
  expect(region.textContent).toContain("Solo Desk closes too");
  expect(region.querySelector('a[href="/data-deletion"]')?.textContent).toBe(
    "How deletion works",
  );

  const remove = buttonNamed(region, "Delete my account")!;
  expect(remove.disabled).toBe(true);
  const input = region.querySelector("input")!;
  expect(region.querySelector(`label[for="${input.id}"]`)?.textContent).toBe(
    "Type DELETE to confirm",
  );
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setValue.call(input, "delete");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(remove.disabled).toBe(false);
  // Nothing was written before the person confirmed.
  expect(sent.filter((item) => item.method !== "GET")).toEqual([]);

  await act(async () => remove.click());
  await settle();
  expect(sent.filter((item) => item.method === "POST")).toEqual([
    {
      method: "POST",
      path: "/v1/me/account-deletion",
      body: { confirm: "DELETE" },
    },
  ]);
  expect(assign).toHaveBeenCalledWith("/account-closed");
});

it("asks for a new owner first when the person's organisation has other members", async () => {
  preview = {
    ...ready,
    transfer_first: [{ id: "o2", name: "Bright Team", other_members: 3 }],
  };
  const region = await openDelete();
  expect(region.textContent).toContain("First, choose a new owner");
  expect(region.textContent).toContain("Bright Team");
  expect(region.textContent).toContain("3 other members");
  expect(
    region.querySelector('a[href="/organisation"]')?.textContent,
  ).toContain("Choose a new owner");
  expect(region.querySelector("input")).toBeNull();
  expect(buttonNamed(region, "Delete my account")).toBeUndefined();
});

it("asks for a fresh sign-in before an old session can delete", async () => {
  preview = { ...ready, fresh_sign_in: false };
  const region = await openDelete();
  expect(region.textContent).toContain("Sign in again first");
  expect(region.textContent).toContain("within 10 minutes");
  expect(buttonNamed(region, "Sign out to sign in again")).toBeDefined();
  expect(region.querySelector("input")).toBeNull();
});

it("sends staff to the owner", async () => {
  preview = { ...ready, staff: true };
  const region = await openDelete();
  expect(region.textContent).toContain("The owner closes staff accounts");
  expect(region.querySelector("input")).toBeNull();
});
