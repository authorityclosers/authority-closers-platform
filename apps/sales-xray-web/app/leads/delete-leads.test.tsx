import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { notify } from "../notice-center";
import { DeleteLeadsSheet, deletedWords, deleteTitle } from "./delete-leads";
import type { LeadRow } from "./leads-client";
import { ListView } from "./list-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));

const NAMES = [
  "Asha Fictional",
  "Ravi Fictional",
  "Meera Fictional",
  "Karan Fictional",
  "Neha Fictional",
  "Test Lead One",
  "Test Lead Two",
];
const id = (index: number) =>
  `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
const doomed = NAMES.map((name, index) => ({ lead_id: id(index), name }));

const row = (index: number, extra: Partial<LeadRow> = {}): LeadRow => ({
  lead_id: id(index),
  revision: 1,
  name: NAMES[index],
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New lead",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-21T05:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(notify).mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (text: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === text,
  );

it("names the leads, says it can't be undone, and deletes on one confirm", async () => {
  const fetchMock = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(json({ detail: "Sales Xray is busy." }, 503))
    .mockResolvedValueOnce(
      json({
        deleted: 7,
        lead_ids: doomed.map((x) => x.lead_id),
        not_found: 0,
      }),
    );
  vi.stubGlobal("fetch", fetchMock);
  const onDeleted = vi.fn();
  await act(async () =>
    root.render(
      <DeleteLeadsSheet
        open
        leads={doomed}
        onClose={() => undefined}
        onDeleted={onDeleted}
      />,
    ),
  );
  const text = document.body.textContent ?? "";
  expect(text).toContain("Delete 7 leads?");
  expect(text).toContain("This can't be undone.");
  for (const name of NAMES.slice(0, 5)) expect(text).toContain(name);
  expect(text).not.toContain("Test Lead One");
  expect(text).toContain("and 2 more");
  expect(text).toContain("Calls recorded with them stay in Calls.");

  // A problem is a corner card; the sheet stays, and Delete again sends the same command.
  await act(async () => button("Delete 7 leads")!.click());
  expect(onDeleted).not.toHaveBeenCalled();
  expect(notify).toHaveBeenLastCalledWith(
    expect.objectContaining({
      tone: "error",
      title: "The leads weren't deleted",
      message: "Sales Xray is busy.",
    }),
  );
  await act(async () => button("Delete 7 leads")!.click());
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toBe("/v1/lead-desk/leads/delete");
  const first = JSON.parse(init?.body as string);
  const second = JSON.parse(fetchMock.mock.calls[1][1]?.body as string);
  expect(first.lead_ids).toEqual(doomed.map((x) => x.lead_id));
  expect(second.command_id).toBe(first.command_id);
  expect(onDeleted).toHaveBeenCalledWith(
    expect.objectContaining({ deleted: 7 }),
  );
  expect(notify).toHaveBeenLastCalledWith(
    expect.objectContaining({ tone: "success", title: "7 leads deleted." }),
  );
});

it("speaks of one lead by name", () => {
  expect(deleteTitle([doomed[0]])).toBe("Delete Asha Fictional?");
  expect(
    deletedWords({ deleted: 1, lead_ids: [id(0)], not_found: 0 }, [doomed[0]]),
  ).toBe("Asha Fictional deleted.");
  expect(
    deletedWords({ deleted: 0, lead_ids: [], not_found: 1 }, [doomed[0]]),
  ).toBe("This lead was already deleted.");
});

it("lets an owner pick test leads and delete them", async () => {
  const page = {
    schema: "lead-desk/1",
    leads: [row(0), row(5, { test_data: true }), row(6, { test_data: true })],
    total: 3,
    next_offset: null,
  };
  const fetchMock = vi.fn<typeof fetch>(async (input) =>
    String(input).includes("/leads/delete")
      ? json({ deleted: 2, lead_ids: [id(5), id(6)], not_found: 0 })
      : json(page),
  );
  vi.stubGlobal("fetch", fetchMock);
  const onChanged = vi.fn();
  await act(async () =>
    root.render(
      <ListView
        canManage
        stage="test"
        stageLabel="Test leads"
        scope="team"
        query=""
        onOpen={() => undefined}
        version={0}
        onChanged={onChanged}
      />,
    ),
  );
  const listUrl = String(fetchMock.mock.calls.at(-1)?.[0]);
  expect(listUrl).toContain("test=only");
  expect(listUrl).not.toContain("stage=");

  await act(async () => button("Select")!.click());
  const boxes = [...host.querySelectorAll('[role="checkbox"]')];
  expect(boxes).toHaveLength(3);
  expect(host.textContent).toContain(
    "Tick the leads to change, then choose what to do",
  );
  await act(async () => (boxes[1] as HTMLButtonElement).click());
  await act(async () => (boxes[2] as HTMLButtonElement).click());
  expect(boxes[1].getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain("2 selected");

  await act(async () => button("Delete")!.click());
  expect(document.body.textContent).toContain("Delete 2 leads?");
  await act(async () => button("Delete 2 leads")!.click());
  const [url, init] = fetchMock.mock.calls.find(([input]) =>
    String(input).includes("/leads/delete"),
  )!;
  expect(String(url)).toBe("/v1/lead-desk/leads/delete");
  expect(JSON.parse(init?.body as string).lead_ids).toEqual([id(5), id(6)]);
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(host.querySelectorAll('[role="checkbox"]')).toHaveLength(0);
  const list = host.querySelector('ul[aria-label="Leads"]')?.textContent;
  expect(list).toContain(NAMES[0]);
  expect(list).not.toContain("Test Lead One");
  expect(host.textContent).toContain("1 lead");
});

it("offers no Select to a seller", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () =>
      json({
        schema: "lead-desk/1",
        leads: [row(0)],
        total: 1,
        next_offset: null,
      }),
    ),
  );
  await act(async () =>
    root.render(
      <ListView
        canManage={false}
        stage="open"
        stageLabel="Open"
        scope="mine"
        query=""
        onOpen={() => undefined}
        version={0}
      />,
    ),
  );
  expect(host.textContent).toContain("1 lead");
  expect(button("Select")).toBeUndefined();
});
