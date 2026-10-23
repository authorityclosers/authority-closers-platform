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

// Delete account (Google Play, 23 Oct 2026): apps with sign-up need an in-app
// way to ask. It asks by email, as /data-deletion says; it deletes nothing.
let root: Root;
let host: HTMLDivElement;
let sent: { method: string; path: string }[];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  sent = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      sent.push({ method: init?.method ?? "GET", path });
      if (path === "/v1/me/sales-xray-profile")
        return json({
          name: "Asha Rao",
          email: "asha@example.invalid",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: false,
          revision: 1,
        });
      return json({}, 404);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("asks for the account's deletion by email from Security, and deletes nothing", async () => {
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
  await act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
  });
  const button = Array.from(host.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === "Delete account",
  )!;
  expect(button.getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelector("#delete-account-request")).toBeNull();
  await act(async () => button.click());
  expect(button.getAttribute("aria-expanded")).toBe("true");
  const region = host.querySelector("#delete-account-request")!;
  const links = Array.from(region.querySelectorAll("a"));
  const request = new URL(links[0].getAttribute("href")!);
  expect(links[0].textContent).toContain("Email the request");
  expect(request.protocol).toBe("mailto:");
  expect(request.pathname).toBe("admin@authorityclosers.com");
  expect(request.searchParams.get("subject")).toBe("Delete my data");
  expect(links[1].textContent).toBe("How deletion works");
  expect(links[1].getAttribute("href")).toBe("/data-deletion");
  // Asking deletes nothing: no request but reads went out.
  expect(sent.filter((item) => item.method !== "GET")).toEqual([]);
});
