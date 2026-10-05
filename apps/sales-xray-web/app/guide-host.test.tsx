import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FirstCallGuide, GuideEngine } from "./guide-host";
import { GuideProgressStore } from "./guide-progress";
import { FIRST_CALL_GUIDE } from "./guide-registry";
import { useFirstCallGuideSwitch } from "./guide-toggle";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "./workspace-access";

vi.mock("next/navigation", () => ({ usePathname: () => "/analysis/new" }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let page: HTMLDivElement;
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  page = document.createElement("div");
  document.body.append(host, page);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  page.remove();
  vi.restoreAllMocks();
});
const step = () =>
  document.querySelector("[data-guide-step]")?.getAttribute("data-guide-step");
const button = (text: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent === text,
  )!;
async function click(text: string) {
  await act(async () => button(text).click());
}
async function show() {
  await act(async () => root.render(<GuideEngine userId="fictional-a" />));
}
async function setPage(markup: string) {
  await act(async () => {
    page.innerHTML = markup;
    for (const element of page.querySelectorAll<HTMLElement>("*")) {
      vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
        left: 40,
        top: 100,
        right: 240,
        bottom: 180,
        width: 200,
        height: 80,
        x: 40,
        y: 100,
        toJSON: () => ({}),
      });
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

it("shows one frame at a time, preserves page focus and lets Escape skip and restart", async () => {
  page.innerHTML = '<button id="page-action">Page action</button>';
  const action = page.querySelector<HTMLButtonElement>("button")!;
  action.focus();
  await show();
  expect(document.activeElement).toBe(action);
  expect(document.querySelectorAll("[data-guide-step]")).toHaveLength(1);
  expect(document.querySelector('[aria-modal="true"]')).toBeNull();
  await click("Next");
  expect(step()).toBe("listen");
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(step()).toBeUndefined();
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("skipped");
  // The account menu switch restarts it; there is no floating launcher.
  expect(document.querySelector("[data-guide-launcher]")).toBeNull();
  await act(async () =>
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).update({
      stepId: "welcome",
      status: "active",
    }),
  );
  expect(step()).toBe("welcome");
});

it("releases focus from the closed card when Escape dismisses a focused guide", async () => {
  await show();
  const skip = button("Skip guide");
  skip.focus();
  expect(document.activeElement).toBe(skip);
  await act(async () =>
    skip.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(step()).toBeUndefined();
  expect(document.activeElement).toBe(document.body);
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("skipped");
});

it("preserves outside focus when Escape dismisses the guide", async () => {
  page.innerHTML = '<button id="page-action">Page action</button>';
  await show();
  const action = page.querySelector<HTMLButtonElement>("button")!;
  action.focus();
  await act(async () =>
    action.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(step()).toBeUndefined();
  expect(document.activeElement).toBe(action);
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("skipped");
});

it("follows upload → processing → report, even when processing finishes between visits", async () => {
  const store = new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE);
  store.update({ stepId: "upload", status: "active" });
  await show();
  await setPage(
    '<div role="group" aria-label="Add sales call audio files"><button>Choose a file</button></div>',
  );
  expect(step()).toBe("upload");
  expect(document.querySelector("[data-guide-coach]")).not.toBeNull();
  expect(button("Next")).toBeUndefined();
  await setPage(
    '<section aria-label="Analysis progress">Checking status</section>',
  );
  expect(step()).toBe("progress");
  await setPage(
    "<div data-report-modes><nav data-report-sections>Report</nav></div>",
  );
  expect(step()).toBe("report");
  await click("Next");
  expect(step()).toBe("moments");
  await click("Finish");
  expect(step()).toBeUndefined();
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("completed");
});

it("switches storage immediately when the account or guide version changes", async () => {
  await show();
  await click("Next");
  expect(step()).toBe("listen");
  await act(async () => root.render(<GuideEngine userId="fictional-b" />));
  expect(step()).toBe("welcome");
  await click("Skip guide");
  await act(async () => root.render(<GuideEngine userId="fictional-a" />));
  expect(step()).toBe("listen");
  await act(async () =>
    root.render(
      <GuideEngine
        userId="fictional-a"
        guide={{ ...FIRST_CALL_GUIDE, version: "2" }}
      />,
    ),
  );
  expect(step()).toBe("welcome");
});

it("does not treat a hidden report as ready; a missing target keeps a safe route", async () => {
  new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).update({
    stepId: "upload",
    status: "active",
  });
  await show();
  await setPage("<div hidden><div data-report-modes>Hidden report</div></div>");
  expect(step()).toBe("upload");
  expect(
    document
      .querySelector<HTMLAnchorElement>("[data-guide-card] a")
      ?.getAttribute("href"),
  ).toBe("/analysis/new");
  await setPage("<div data-report-modes>Report ready</div>");
  expect(step()).toBe("report");
});

it("hides for an existing modal, lets its Escape pass, and restores after close", async () => {
  await show();
  await setPage("<dialog open>Existing checks</dialog>");
  expect(step()).toBeUndefined();
  await act(async () =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("active");
  await setPage("");
  expect(step()).toBe("welcome");
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-label="Close guide"]')!
      .click(),
  );
  expect(step()).toBeUndefined();
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("skipped");
});

function GuideSwitch() {
  const guide = useFirstCallGuideSwitch();
  return guide ? (
    <button type="button" data-switch onClick={() => guide.set(!guide.on)}>
      {guide.on ? "On" : "Off"}
    </button>
  ) : null;
}

it("closing keeps the guide off after reloads and new versions until the switch turns it on", async () => {
  const access: WorkspaceAccessValue = {
    status: "ready",
    authenticated: true,
    context: {
      personId: "fictional-a",
      sessionId: "session",
      tenantId: "workspace",
    },
    retry: () => {},
    workspaces: [
      {
        tenant_id: "workspace",
        kind: "personal",
        name: "Personal",
        role: null,
        sales_xray_enabled: true,
      },
    ],
  };
  const app = () => (
    <WorkspaceAccessContext.Provider value={access}>
      <FirstCallGuide />
      <GuideSwitch />
    </WorkspaceAccessContext.Provider>
  );
  const toggle = () =>
    document.querySelector<HTMLButtonElement>("[data-switch]")!;
  await act(async () => root.render(app()));
  expect(step()).toBe("welcome");
  expect(toggle().textContent).toBe("On");
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-label="Close guide"]')!
      .click(),
  );
  expect(step()).toBeUndefined();
  expect(document.querySelector("[data-guide-launcher]")).toBeNull();
  expect(toggle().textContent).toBe("Off");
  // A reload and a later guide version both keep it closed.
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(app()));
  expect(step()).toBeUndefined();
  await act(async () =>
    root.render(
      <GuideEngine
        userId="fictional-a"
        guide={{ ...FIRST_CALL_GUIDE, version: "2" }}
      />,
    ),
  );
  expect(step()).toBeUndefined();
  await act(async () => root.render(app()));
  await act(async () => toggle().click());
  expect(toggle().textContent).toBe("On");
  expect(step()).toBe("welcome");
});

it("does not auto-start for unknown, guest, or disabled workspace access", async () => {
  const value: WorkspaceAccessValue = {
    status: "ready",
    authenticated: true,
    context: {
      personId: "fictional-a",
      sessionId: "session",
      tenantId: "workspace",
    },
    retry: () => {},
    workspaces: [
      {
        tenant_id: "workspace",
        kind: "personal",
        name: "Personal",
        role: null,
        sales_xray_enabled: false,
      },
    ],
  };
  for (const access of [
    null,
    { ...value, status: "loading" as const, authenticated: null },
    { ...value, authenticated: false },
    value,
  ]) {
    await act(async () =>
      root.render(
        <WorkspaceAccessContext.Provider value={access}>
          <FirstCallGuide />
        </WorkspaceAccessContext.Provider>,
      ),
    );
    expect(step()).toBeUndefined();
  }
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          ...value,
          workspaces: [{ ...value.workspaces![0], sales_xray_enabled: true }],
        }}
      >
        <FirstCallGuide />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  expect(step()).toBe("welcome");
});

it("versioned What's new definitions use the same engine without sharing progress", async () => {
  const guide = {
    ...FIRST_CALL_GUIDE,
    id: "whats-new",
    version: "2026.10",
    label: "What’s new",
    steps: [{ ...FIRST_CALL_GUIDE.steps[0], title: "Check this next" }],
  };
  new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).update({
    stepId: "welcome",
    status: "skipped",
  });
  await act(async () =>
    root.render(<GuideEngine userId="fictional-a" guide={guide} />),
  );
  expect(document.querySelector("[data-guide-card]")?.textContent).toContain(
    "Check this next",
  );
  await click("Finish");
  expect(
    new GuideProgressStore("fictional-a", guide).getSnapshot().status,
  ).toBe("completed");
});
