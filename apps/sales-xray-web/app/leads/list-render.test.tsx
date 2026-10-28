// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import type { ServerLeads } from "./leads-seed";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ListView } from "./list-view";
import { readLeads, type LeadRow } from "./leads-client";
import { LeadLine } from "./desk-view";

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));
vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  readLeads: vi.fn(),
}));
vi.mock("./desk-view", async (original) => ({
  ...(await original<typeof import("./desk-view")>()),
  LeadLine: vi.fn(
    ({ row, onOpen, actions }: Parameters<typeof LeadLine>[0]) => (
      <li data-lead-row="">
        <button onClick={() => onOpen(row.lead_id)}>Open {row.name}</button>
        {actions?.onTap ? (
          <button onClick={() => actions.onTap?.(row, "email")}>
            Email {row.name}
          </button>
        ) : null}
      </li>
    ),
  ),
}));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const row = (n: number): LeadRow => ({
  lead_id: `fictional-${n}`,
  revision: 1,
  name: `Fictional prospect ${n}`,
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: null,
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
  test_data: true,
});
const rows = Array.from({ length: 50 }, (_, n) => row(n));
beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  vi.mocked(LeadLine).mockClear();
  vi.mocked(readLeads).mockResolvedValue({
    leads: rows,
    total: 100,
    next_offset: 50,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.clearAllMocks();
});
const render = (
  onOpen: (id: string) => void,
  onTap?: (row: LeadRow, channel: "call" | "email" | "whatsapp") => void,
) =>
  act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="open"
        stageLabel="All leads"
        scope="mine"
        query=""
        version={0}
        onOpen={onOpen}
        actions={onTap ? { onTap } : undefined}
      />,
    ),
  );
const reveal = async () => {
  for (let n = 0; n < 4; n++)
    await act(async () => vi.advanceTimersByTimeAsync(100));
};

it("reuses loaded rows when callbacks change and sends the next tap to the latest handlers", async () => {
  const originalOpen = vi.fn(),
    latestOpen = vi.fn(),
    originalTap = vi.fn(),
    latestTap = vi.fn();
  await render(originalOpen, originalTap);
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(8);
  await reveal();
  expect(vi.mocked(LeadLine)).toHaveBeenCalledTimes(50);
  await render(latestOpen, latestTap);
  expect(vi.mocked(LeadLine)).toHaveBeenCalledTimes(50);
  const buttons = host.querySelectorAll<HTMLButtonElement>("li button");
  await act(async () => {
    buttons[0].click();
    buttons[1].click();
  });
  expect(latestOpen).toHaveBeenCalledWith("fictional-0");
  expect(latestTap).toHaveBeenCalledWith(rows[0], "email");
  expect(originalOpen).not.toHaveBeenCalled();
  expect(originalTap).not.toHaveBeenCalled();
});

it("adding another page renders its new rows without rebuilding the first page", async () => {
  await render(vi.fn());
  await reveal();
  vi.mocked(readLeads).mockResolvedValueOnce({
    leads: Array.from({ length: 50 }, (_, n) => row(n + 50)),
    total: 100,
    next_offset: null,
  });
  const more = Array.from(
    host.querySelectorAll<HTMLButtonElement>("button"),
  ).find((b) => b.textContent?.startsWith("Show more"))!;
  await act(async () => more.click());
  await reveal();
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(100);
  expect(vi.mocked(LeadLine)).toHaveBeenCalledTimes(100);
});

it("preserves the absence of quick actions, then enables them when offered", async () => {
  await render(vi.fn());
  expect(host.textContent).not.toContain("Email Fictional");
  const tap = vi.fn();
  await render(vi.fn(), tap);
  expect(host.textContent).toContain("Email Fictional");
});

it("hydrates the server's first rows without replacing them with a loading outline, and rejects a changed identity", async () => {
  vi.mocked(readLeads).mockReturnValue(new Promise(() => {}));
  const identity = JSON.stringify([
    "fictional-person",
    "fictional-session",
    "fictional-workspace",
  ]);
  const initial = {
    identity,
    desk: {},
    firstPage: {
      scope: "mine",
      page: { leads: rows, total: 2000, next_offset: 50 },
    },
  } as unknown as ServerLeads;
  const component = (cacheIdentity: string) => (
    <ListView
      initial={initial}
      cacheIdentity={cacheIdentity}
      canManage={false}
      stage="open"
      stageLabel="All leads"
      scope="mine"
      query=""
      version={0}
      onOpen={() => {}}
    />
  );
  const markup = renderToString(component(identity));
  expect(markup).toContain("Fictional prospect 0");
  expect(markup).not.toContain("leadRowSkeleton");
  await act(async () => root.unmount());
  host.innerHTML = markup;
  const errors: unknown[] = [];
  await act(async () => {
    root = hydrateRoot(host, component(identity), {
      onRecoverableError: (error) => errors.push(error),
    });
  });
  expect(errors).toEqual([]);
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(8);
  expect(host.textContent).toContain("Syncing");
  await act(async () =>
    root.render(
      component(
        JSON.stringify([
          "fictional-person",
          "fictional-session",
          "other-workspace",
        ]),
      ),
    ),
  );
  expect(host.querySelectorAll("[data-lead-row]")).toHaveLength(0);
});
