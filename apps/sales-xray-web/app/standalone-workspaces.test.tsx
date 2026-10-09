import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StandaloneStudio } from "./standalone-studio";
import { useWorkspaceAccess } from "./workspace-access";
import { getShellState, updateShellState } from "./shell/shell-store";
import type { SalesXrayWorkspaceChoices } from "./sales-xray-workspaces";

vi.mock("next/navigation", () => ({
  usePathname: () => "/analysis/new",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("./profile-menu", () => ({ ProfileMenu: () => null }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, host: HTMLDivElement;
let directory: SalesXrayWorkspaceChoices;
let selectionStatus: number;
let fetcher: ReturnType<typeof vi.fn>;
const personal = {
  tenant_id: "personal-id",
  kind: "personal",
  name: "Personal",
  role: null,
  sales_xray_enabled: true,
} as const;
// This name used to be incorrectly classified as Personal by the name heuristic.
const organisation = {
  tenant_id: "org-id",
  kind: "organisation",
  name: "Closers Academy",
  role: "owner",
  sales_xray_enabled: true,
} as const;

function UploadProbe() {
  const access = useWorkspaceAccess();
  return (
    <div data-upload data-tenant={access?.context?.tenantId}>
      Upload a call
    </div>
  );
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  selectionStatus = 200;
  directory = {
    selected_tenant_id: "personal-id",
    workspaces: [personal, organisation],
  };
  updateShellState({
    selectedTenantId: null,
    selectedTenantAccountKey: null,
    recentCalls: [],
    recentCallsContextKey: null,
  });
  fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/v1/me/workspaces")
      return Response.json({
        person_id: "person-id",
        session_id: "session-id",
        selected_tenant_id: "operations-id",
        workspaces: [{ tenant_id: "operations-id", name: "Authority Closers" }],
      });
    if (path === "/v1/me/sales-xray-workspaces")
      return Response.json(directory);
    if (path === "/v1/context") {
      const tenantId = JSON.parse(init!.body as string).tenant_id;
      if (selectionStatus === 200)
        directory = { ...directory, selected_tenant_id: tenantId };
      return Response.json(
        { tenant_id: tenantId },
        { status: selectionStatus },
      );
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
async function mount() {
  await act(async () =>
    root.render(
      <StandaloneStudio>
        <UploadProbe />
      </StandaloneStudio>,
    ),
  );
}
async function remount() {
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount();
}
const button = (label: string) =>
  host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;

it("shows Personal and an organisation using server kinds; operations is absent", async () => {
  await mount();
  await act(async () => button("Current workspace: Personal").click());
  expect(host.querySelectorAll('[role="menuitemradio"]')).toHaveLength(2);
  expect(host.textContent).toContain("Closers Academy");
  expect(host.querySelector('[role="menu"]')?.textContent).not.toContain(
    "Authority Closers",
  );
  expect(host.querySelector('[data-kind="organisation"]')).not.toBeNull();
  expect(host.querySelector("[data-upload]")?.getAttribute("data-tenant")).toBe(
    "personal-id",
  );
  expect(
    fetcher.mock.calls.filter(([path]) => path === "/v1/context"),
  ).toHaveLength(0);
});

it("selects Personal with POST /v1/context when the directory selection is null", async () => {
  directory = {
    ...directory,
    selected_tenant_id: null,
    workspaces: [organisation, personal],
  };
  await mount();
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/context",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ tenant_id: "personal-id" }),
    }),
  );
  expect(host.querySelector("[data-upload]")?.getAttribute("data-tenant")).toBe(
    "personal-id",
  );
});

it("keeps upload hidden if automatic Personal selection fails", async () => {
  directory = { ...directory, selected_tenant_id: null };
  selectionStatus = 403;
  await mount();
  expect(host.querySelector("[data-upload]")).toBeNull();
  expect(host.textContent).toContain("Workspace access could not be checked");
});

it("shows the off message and suppresses Recents and upload for a disabled workspace", async () => {
  vi.stubEnv("NODE_ENV", "development");
  directory = {
    selected_tenant_id: "org-id",
    workspaces: [personal, { ...organisation, sales_xray_enabled: false }],
  };
  await mount();
  expect(host.textContent).toContain(
    "Sales Xray isn't on for this workspace yet",
  );
  expect(host.textContent).not.toContain("Recents");
  expect(host.querySelector("[data-upload]")).toBeNull();
  expect(
    fetcher.mock.calls.some(([path]) => path.startsWith("/v1/conversation/")),
  ).toBe(false);
  await act(async () => button("Current workspace: Closers Academy").click());
  expect(host.querySelectorAll('[role="menuitemradio"]')).toHaveLength(2);
});

it.each([true, false])(
  "keeps the confirmed organisation on same-session remount (enabled: %s)",
  async (enabled) => {
    vi.stubEnv("NODE_ENV", "development");
    directory = {
      selected_tenant_id: "org-id",
      workspaces: [personal, { ...organisation, sales_xray_enabled: enabled }],
    };
    await mount();
    expect(getShellState().selectedTenantId).toBe("org-id");
    await remount();
    expect(button("Current workspace: Closers Academy")).not.toBeNull();
    expect(host.textContent?.includes("Recents")).toBe(enabled);
    expect(host.querySelector("[data-upload]") !== null).toBe(enabled);
    if (enabled) {
      expect(
        host.querySelector("[data-upload]")?.getAttribute("data-tenant"),
      ).toBe("org-id");
    } else {
      expect(host.textContent).toContain(
        "Sales Xray isn't on for this workspace yet",
      );
      expect(
        fetcher.mock.calls.some(([path]) =>
          path.startsWith("/v1/conversation/"),
        ),
      ).toBe(false);
    }
    await act(async () => button("Current workspace: Closers Academy").click());
    const selected = host.querySelector(
      '[role="menuitemradio"][aria-checked="true"]',
    );
    expect(selected?.textContent).toContain("Closers Academy");
  },
);

it("switches both ways and clears the previous workspace's cached Recents", async () => {
  await mount();
  for (const [from, to, name] of [
    ["Personal", "org-id", "Closers Academy"],
    ["Closers Academy", "personal-id", "Personal"],
  ]) {
    updateShellState({
      recentCalls: [
        { id: "previous-call", name: "Previous workspace call", date: "Oct 2" },
      ],
      recentCallsContextKey: "old",
    });
    await act(async () => button(`Current workspace: ${from}`).click());
    const item = [
      ...host.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'),
    ].find((el) => el.textContent?.includes(name))!;
    await act(async () => item.click());
    expect(getShellState().selectedTenantId).toBe(to);
    expect(getShellState().recentCalls).toEqual([]);
    expect(getShellState().recentCallsContextKey).toBeNull();
    await remount();
    expect(button(`Current workspace: ${name}`)).not.toBeNull();
  }
});

it("uses a selected server bootstrap without browser identity reads or selection writes", async () => {
  await act(async () =>
    root.render(
      <StandaloneStudio
        initial={{
          view: {
            kind: "ready",
            choices: {
              person_id: "person-id",
              session_id: "session-id",
              selected_tenant_id: "org-id",
              workspaces: [organisation],
              salesXrayWorkspaces: [organisation],
            },
          },
          profile: null,
        }}
      >
        <UploadProbe />
      </StandaloneStudio>,
    ),
  );
  expect(host.querySelector("[data-upload]")?.getAttribute("data-tenant")).toBe(
    "org-id",
  );
  expect(
    fetcher.mock.calls.filter(([path]) =>
      [
        "/v1/me/workspaces",
        "/v1/me/sales-xray-workspaces",
        "/v1/context",
      ].includes(path),
    ),
  ).toHaveLength(0);
});
