// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  access: null as unknown,
  push: vi.fn(),
  handOver: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: calls.push }),
  usePathname: () => "/leads/notes",
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));
vi.mock("../../workspace-access", () => ({
  useWorkspaceAccess: () => calls.access,
}));
vi.mock("../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("../lead-handoff", () => ({ handOverLead: calls.handOver }));
vi.mock("../notes-view", () => ({
  NotesView: ({ onOpen }: { onOpen: (leadId: string, at: string) => void }) => (
    <button
      type="button"
      onClick={() => onOpen("lead-7", "2026-10-25T09:00:00Z")}
    >
      A note
    </button>
  ),
}));

import { NotesRoute } from "./notes-page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

it("asks to sign in when nobody is signed in", () => {
  calls.access = { authenticated: false, status: "ready", context: null };
  act(() => root.render(<NotesRoute />));
  expect(container.textContent).toContain("Sign in to see your notes");
});

it("opens the lead on Leads when a note is tapped", () => {
  calls.access = {
    authenticated: true,
    status: "ready",
    context: { personId: "p1", tenantId: "t1" },
  };
  act(() => root.render(<NotesRoute />));
  expect(container.querySelector("h1, h2")?.textContent ?? "").toContain(
    "Notes",
  );
  act(() => container.querySelector("button")?.click());
  expect(calls.handOver).toHaveBeenCalledWith("lead-7");
  expect(calls.push).toHaveBeenCalledWith("/leads");
});
