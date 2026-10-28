// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { readLeads, type LeadRow } from "./leads-client";
import { ListView } from "./list-view";
import { rememberLeadData, listQuestion } from "./list-cache";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  readLeads: vi.fn(),
}));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const row: LeadRow = {
  lead_id: "00000000-0000-4000-8000-000000000001",
  revision: 1,
  name: "Sample Lead",
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: "1234",
  has_email: true,
  stage: "new",
  stage_label: "New lead",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-28T00:00:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
};
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({})),
  );
  vi.mocked(readLeads).mockResolvedValue({
    leads: [row],
    total: 7,
    next_offset: null,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});
const render = async (stage = "open", canManage = true, onTap = vi.fn()) => {
  await act(async () =>
    root.render(
      <ListView
        canManage={canManage}
        stage={stage}
        stageLabel="All leads"
        scope="team"
        query=""
        version={0}
        onOpen={() => {}}
        layoutOwner="sample-workspace"
        tools={<button>Views</button>}
        actions={{ onTap }}
      />,
    ),
  );
};
const click = async (button: HTMLButtonElement) =>
  act(async () => button.click());

it("keeps the count, layout and Select together while preserving layout and selection", async () => {
  await render();
  const count = host.querySelector('[aria-live="polite"]')!;
  const header = count.parentElement!;
  expect(count.textContent).toBe("7 leads");
  expect(header.querySelector('[aria-label="Show leads as"]')).not.toBeNull();
  expect(header.querySelector('[aria-label="Select"]')).not.toBeNull();
  expect(header.textContent).toContain("Views");
  expect(host.textContent).toContain("Views");
  await click(
    Array.from(header.querySelectorAll("button")).find(
      (button) => button.textContent === "Table",
    )!,
  );
  await vi.waitFor(async () => {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(host.querySelector("table")).not.toBeNull();
  });
  expect(localStorage.getItem("sx:leads-layout:sample-workspace")).toBe(
    "table",
  );
  await click(header.querySelector('[aria-label="Select"]')!);
  expect(
    header.querySelector('[aria-label="Cancel"]')?.getAttribute("aria-pressed"),
  ).toBe("true");
  expect(host.querySelector('[aria-label="Show leads as"]')).toBeNull();
  await click(header.querySelector('[aria-label="Cancel"]')!);
  expect(host.querySelector('[aria-label="Show leads as"]')).not.toBeNull();
});

it("labels test totals and keeps Select restricted to managers", async () => {
  await render("test", false);
  expect(host.querySelector('[aria-live="polite"]')?.textContent).toBe(
    "7 test leads",
  );
  expect(host.querySelector('[aria-label="Select"]')).toBeNull();
  expect(readLeads).toHaveBeenCalledWith(
    expect.objectContaining({ test: true, stage: null }),
    expect.any(AbortSignal),
  );
});

it("keeps all three contact actions wired to the same lead", async () => {
  const onTap = vi.fn();
  await render("open", true, onTap);
  for (const [label, channel] of [
    ["Call", "call"],
    ["WhatsApp", "whatsapp"],
    ["Email", "email"],
  ]) {
    const button = host.querySelector<HTMLButtonElement>(
      `button[aria-label="${label} Sample Lead"]`,
    )!;
    expect(button.disabled).toBe(false);
    await click(button);
    expect(onTap).toHaveBeenLastCalledWith(row, channel);
  }
});

it("paints cached first rows while syncing, retains them on failure, and hides them on a workspace change", async () => {
  const cedar = JSON.stringify([
    "fictional-person",
    "fictional-session",
    "cedar",
  ]);
  const maple = JSON.stringify([
    "fictional-person",
    "fictional-session",
    "maple",
  ]);
  rememberLeadData(
    cedar,
    `list:${listQuestion({ scope: "team", stage: "open", test: false })}`,
    {
      leads: [row],
      total: 2000,
      next_offset: 50,
    },
  );
  let reject!: (error: Error) => void;
  vi.mocked(readLeads).mockReturnValueOnce(
    new Promise((_, fail) => {
      reject = fail;
    }),
  );
  const view = (identity: string) => (
    <ListView
      canManage
      stage="open"
      stageLabel="All leads"
      scope="team"
      query=""
      version={0}
      onOpen={() => {}}
      cacheIdentity={identity}
    />
  );
  await act(async () => root.render(view(cedar)));
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(1);
  expect(host.querySelector('[aria-label="Lead sync"]')?.textContent).toBe(
    "Syncing…",
  );
  await act(async () => reject(new Error("offline")));
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(1);
  expect(host.querySelector('[aria-label="Lead sync"]')?.textContent).toBe(
    "Sync paused",
  );
  vi.mocked(readLeads).mockReturnValueOnce(new Promise(() => {}));
  await act(async () => root.render(view(maple)));
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(0);
  expect(host.querySelector('[aria-label="Loading leads"]')).not.toBeNull();
});

it("keeps scrolled pages visible until a background refresh replaces the same window", async () => {
  const second = {
    ...row,
    lead_id: "00000000-0000-4000-8000-000000000002",
    name: "Second Fictional",
  };
  vi.mocked(readLeads).mockReset();
  vi.mocked(readLeads).mockResolvedValueOnce({
    leads: [row],
    total: 2,
    next_offset: 1,
  });
  const view = (version: number) => (
    <ListView
      canManage
      stage="open"
      stageLabel="All leads"
      scope="team"
      query=""
      version={version}
      onOpen={() => {}}
    />
  );
  await act(async () => root.render(view(0)));
  vi.mocked(readLeads).mockResolvedValueOnce({
    leads: [second],
    total: 2,
    next_offset: null,
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.startsWith("Show more"))!
      .click(),
  );
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(2);
  let finish!: (page: {
    leads: LeadRow[];
    total: number;
    next_offset: null;
  }) => void;
  vi.mocked(readLeads).mockResolvedValueOnce({
    leads: [{ ...row, name: "Updated Fictional" }],
    total: 2,
    next_offset: 1,
  });
  vi.mocked(readLeads).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  await act(async () => root.render(view(1)));
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(2);
  expect(host.textContent).toContain("Sample Lead");
  expect(host.querySelector('[aria-label="Lead sync"]')?.textContent).toBe(
    "Syncing…",
  );
  await act(async () =>
    finish({ leads: [second], total: 2, next_offset: null }),
  );
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(2);
  expect(host.textContent).toContain("Updated Fictional");
  // Quiet while all is well (owner, #73): no "Updated just now" on every list.
  expect(host.querySelector('[aria-label="Lead sync"]')?.textContent).toBe("");
  expect(readLeads).toHaveBeenLastCalledWith(
    expect.objectContaining({ offset: 1 }),
    expect.any(AbortSignal),
  );
});
