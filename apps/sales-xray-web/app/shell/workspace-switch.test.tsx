import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));
// The page the switch starts from (no App Router in a unit test).
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  usePathname: () => "/calls",
}));
const felt = vi.fn();
vi.mock("../ui/haptics", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  haptic: (kind: string) => felt(kind),
  tick: () => felt("tap"),
}));
const notify = vi.fn();
vi.mock("../notice-center", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  notify: (notice: unknown) => notify(notice),
}));

import { AcquisitionShell } from "../acquisition-shell";
import { SELECT_WORKSPACE_EVENT } from "../call-ownership";
import { WorkspaceAccessProvider } from "../workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 25 Oct 2026 (Admin #17): switching organisation "feels slow". The
// tap answers at once; a switch that fails puts the old workspace back.

let root: Root;
let host: HTMLDivElement;
let contextReply: (value: Response | Error) => void = () => undefined;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: RequestInfo | URL) =>
      String(url) === "/v1/context"
        ? new Promise<Response>((resolve, reject) => {
            contextReply = (value) =>
              value instanceof Error ? reject(value) : resolve(value);
          })
        : // Every other read stays on its way: this test is about the switch.
          new Promise<Response>(() => undefined),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  felt.mockClear();
  notify.mockClear();
  sessionStorage.clear();
});

// The phone header's workspace line (as the shell's navigation test reads it).
const shown = () => host.querySelector("header [title] small")?.textContent;

const render = () =>
  act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: "org-one" },
          workspaces: [
            {
              tenant_id: "org-one",
              kind: "organisation",
              name: "Authority Closers",
              role: "owner",
              sales_xray_enabled: true,
            },
            {
              tenant_id: "org-two",
              kind: "organisation",
              name: "Fictional Traders",
              role: "owner",
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <AcquisitionShell authenticated active="calls">
          <p>Calls</p>
        </AcquisitionShell>
      </WorkspaceAccessProvider>,
    ),
  );

const choose = (tenantId: string) =>
  act(async () => {
    window.dispatchEvent(
      new CustomEvent(SELECT_WORKSPACE_EVENT, { detail: tenantId }),
    );
  });

it("answers a workspace tap at once: a haptic, the new name, the page's outline", async () => {
  await render();
  expect(shown()).toBe("Authority Closers");
  await choose("org-two");
  // Before the server has answered.
  expect(felt).toHaveBeenCalledWith("tap");
  expect(shown()).toBe("Fictional Traders");
  expect(host.querySelector("[data-standing-in]")).not.toBeNull();
  expect(fetch).toHaveBeenCalledWith(
    "/v1/context",
    expect.objectContaining({ method: "POST" }),
  );
});

it("puts the old workspace back when the switch fails, and says so", async () => {
  await render();
  await choose("org-two");
  await act(async () => contextReply(new Error("offline")));
  expect(shown()).toBe("Authority Closers");
  expect(host.querySelector("[data-standing-in]")).toBeNull();
  expect(felt).toHaveBeenLastCalledWith("error");
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "error",
      title: "Couldn’t switch workspace",
    }),
  );
  expect(sessionStorage.getItem("sx-switch-timing")).toBeNull();
});
