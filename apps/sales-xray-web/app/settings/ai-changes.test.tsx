// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("../notice-center", () => notices);

import { AiWritesPanel, AppChangesPanel } from "./ai-changes";
import { accessWords, changeWords, parseAppChanges } from "./ai-apps-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CHANGE = {
  change_id: "c1",
  action: "note",
  lead_id: "l1",
  lead_name: "Fictional Lead",
  via: "ChatGPT",
  at: "2026-10-25T10:00:00Z",
  status: "applied",
  can_undo: true,
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.notify.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = () =>
  act(async () => new Promise((done) => setTimeout(done, 0)));

it("says what an app may add, and reads changes strictly", () => {
  expect(accessWords(["leads:read", "leads:write"])).toBe(
    "Reads leads · adds leads",
  );
  expect(accessWords(["leads:read", "leads:notes", "leads:tasks"])).toBe(
    "Reads leads · adds notes and tasks",
  );
  expect(accessWords(["leads:notes"])).toBe("Adds notes");
  expect(changeWords("task")).toBe("Added a task");
  expect(parseAppChanges({ changes: [CHANGE] })?.[0]).toMatchObject({
    id: "c1",
    leadName: "Fictional Lead",
    via: "ChatGPT",
    canUndo: true,
  });
  expect(
    parseAppChanges({ changes: [{ ...CHANGE, status: "deleted" }] }),
  ).toBeNull();
  expect(
    parseAppChanges({ changes: [{ ...CHANGE, lead_name: null }] })?.[0]
      .leadName,
  ).toBeNull();
});

it("lists changes from AI apps with Undo, and undoes one", async () => {
  const calls: { url: string; method: string }[] = [];
  let undone = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      if (url.endsWith("/undo")) {
        undone = true;
        return Response.json({ status: "undone" });
      }
      return Response.json({
        changes: [
          undone ? { ...CHANGE, status: "undone", can_undo: false } : CHANGE,
        ],
      });
    }),
  );
  await act(async () => root.render(<AppChangesPanel />));
  await settle();
  expect(host.textContent).toContain("Added a note · Fictional Lead");
  expect(host.textContent).toContain("via ChatGPT");
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Undo",
  )!;
  await act(async () => button.click());
  await settle();
  expect(calls.find((call) => call.url.endsWith("/undo"))).toMatchObject({
    url: "/v1/lead-desk/ai-changes/c1/undo",
    method: "POST",
  });
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "Undone" }),
  );
  expect(host.textContent).toContain("Undone");
});

it("shows nothing where there is no lead desk", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 403 })),
  );
  await act(async () => root.render(<AppChangesPanel />));
  await settle();
  expect(host.textContent).toBe("");
});

it("lets an owner pause changes from apps, and hides the switch from others", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        sent.push(body);
        return Response.json({ ...body, revision: 2 });
      }
      return Response.json({
        revision: 1,
        paused: false,
        note: true,
        task: true,
        outcome: true,
        can_change: true,
      });
    }),
  );
  await act(async () => root.render(<AiWritesPanel />));
  await settle();
  const master = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  expect(master.checked).toBe(true);
  await act(async () => master.click());
  await settle();
  expect(sent).toEqual([
    {
      expected_revision: 1,
      paused: true,
      note: true,
      task: true,
      outcome: true,
    },
  ]);

  await act(async () => root.unmount());
  root = createRoot(host);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        revision: 1,
        paused: false,
        note: true,
        task: true,
        outcome: true,
        can_change: false,
      }),
    ),
  );
  await act(async () => root.render(<AiWritesPanel />));
  await settle();
  expect(host.textContent).toBe("");
});
