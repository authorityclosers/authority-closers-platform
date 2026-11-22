// @vitest-environment happy-dom
// Tags on leads (picks 17 Nov 2026: M2-A "Add tag", the phone dock's Tag;
// migration 0165; v1.94): the Tag sheet for many leads (pick or make a tag,
// the preview, one bulk job with Undo), for one lead (only what changed is
// sent, ten at most), the chips, the list's tag filter and Manage tags.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Notice = {
  title?: string;
  tone?: string;
  action?: { label: string; run?: () => void };
};
const notices = vi.hoisted(() => [] as Notice[]);
vi.mock("../notice-center", () => ({
  notify: (notice: Notice) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { moreParams, type TagChip } from "./leads-client";
import { filterOf } from "./manage-bar";
import { ManageTagsSheet } from "./manage-tags";
import { TagChips } from "./tag-chips";
import { TagPick } from "./tag-pick";
import { forgetTags, TagSheet, tagPreview } from "./tag-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let sent: { url: string; body: Record<string, unknown> | undefined }[];
const HOT = "00000000-0000-4000-8000-0000000000a1";
const VIDEO = "00000000-0000-4000-8000-0000000000a2";
const LEAD = (n: number) => `00000000-0000-4000-8000-0000000001${10 + n}`;
let canChange = true;
let stale = false;
let listed: ReturnType<typeof tag>[] = [];
const tag = (tag_id: string, name: string, leads: number) => ({
  tag_id,
  name,
  colour: "mint",
  position: 0,
  revision: 1,
  leads,
  can_change: canChange,
});

beforeEach(() => {
  notices.length = 0;
  sent = [];
  canChange = true;
  stale = false;
  listed = [];
  forgetTags();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      sent.push({ url, body });
      if (url === "/v1/lead-desk/tags" && init?.method === "POST")
        return Response.json(tag(VIDEO, body.name, 0), { status: 201 });
      if (url === "/v1/lead-desk/tags")
        return Response.json({
          tags: listed.length ? listed : [tag(HOT, "Hot", 12)],
        });
      if (url === `/v1/lead-desk/tags/${HOT}` && init?.method === "PUT")
        return stale
          ? Response.json(
              {
                detail: "This tag changed since you opened it. Open it again.",
              },
              { status: 409 },
            )
          : Response.json({
              ...tag(HOT, body.name ?? "Hot", 12),
              colour: body.colour ?? "mint",
              revision: 2,
            });
      if (url === `/v1/lead-desk/tags/${HOT}/delete`)
        return Response.json({ tags: [] });
      if (url === "/v1/lead-desk/leads/bulk-jobs")
        return Response.json({
          job_id: "job-t",
          action: "tag",
          selection: "ids",
          selected: 3,
          changed: 3,
          unchanged: 0,
          not_found: 0,
          failed: [],
          lead_ids: [LEAD(1), LEAD(2), LEAD(3)],
          words: "3 leads tagged Hot, Nov video ad",
          by_person_id: null,
          at: "2026-11-18T06:00:00Z",
          undo_until: "2026-11-18T06:30:00Z",
          undoable: true,
          undone_at: null,
        });
      if (url === "/v1/lead-desk/leads/bulk-jobs/job-t/undo")
        return Response.json({ job_id: "job-t", restored: 3, skipped: 0 });
      if (url === `/v1/lead-desk/leads/${LEAD(1)}/tags`)
        return Response.json({
          lead_id: LEAD(1),
          tags: [{ tag_id: HOT, name: "Hot", colour: "mint" }],
          added: 1,
          removed: 1,
        });
      return Response.json({}, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

const button = (label: string) =>
  Array.from(document.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === label,
  );
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const type = async (input: HTMLInputElement, value: string) => {
  const set = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

it("says what a bulk tag change does, in plain words", () => {
  expect(tagPreview(12, ["Hot"], "add")).toBe("12 leads get Hot");
  expect(tagPreview(1, ["Hot"], "add")).toBe("1 lead gets Hot");
  expect(tagPreview(3, ["Hot", "Nov video ad"], "add")).toBe(
    "3 leads get Hot and Nov video ad",
  );
  expect(tagPreview(4, ["Hot"], "remove")).toBe("Hot comes off 4 leads");
  expect(tagPreview(4, [], "add")).toBe("Choose a tag");
});

it("keeps the tag in the list's address and in the bulk filter", () => {
  expect(moreParams({ side: "inbound", tag: HOT })).toEqual([
    ["side", "inbound"],
    ["tag", HOT],
  ]);
  expect(
    filterOf({ scope: "team", more: { view: "all", tag: HOT } }),
  ).toMatchObject({ scope: "team", view: "all", tag: HOT });
});

it("tags many leads: picks one, makes one, previews, runs one job with Undo", async () => {
  const onDone = vi.fn();
  const selection = { kind: "ids" as const, ids: [LEAD(1), LEAD(2), LEAD(3)] };
  await act(async () =>
    root.render(
      <TagSheet
        open
        target={{ kind: "many", selection }}
        onClose={() => undefined}
        onDone={onDone}
      />,
    ),
  );
  await settle();
  expect(document.body.textContent).toContain("Tag 3 leads");
  expect(document.body.textContent).toContain("Hot");
  const hot = document.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  await act(async () => hot.click());
  expect(document.body.textContent).toContain("3 leads get Hot");
  const find = document.querySelector<HTMLInputElement>(
    'input[aria-label="Find or make a tag"]',
  )!;
  await type(find, "Nov video ad");
  await act(async () => button("Make “Nov video ad”")?.click());
  await settle();
  expect(
    sent.find(
      (item) => item.url === "/v1/lead-desk/tags" && item.body !== undefined,
    )?.body,
  ).toMatchObject({ name: "Nov video ad" });
  expect(document.body.textContent).toContain(
    "3 leads get Hot and Nov video ad",
  );
  await act(async () => button("Tag 3 leads")?.click());
  await settle();
  const job = sent.find((item) => item.url === "/v1/lead-desk/leads/bulk-jobs");
  expect(job?.body).toMatchObject({
    action: "tag",
    lead_ids: [LEAD(1), LEAD(2), LEAD(3)],
    tag_ids: [HOT, VIDEO],
  });
  expect(onDone).toHaveBeenCalledOnce();
  const done = notices.at(-1)!;
  expect(done.title).toBe("3 leads tagged Hot, Nov video ad");
  expect(done.action?.label).toBe("Undo");
  await act(async () => {
    done.action?.run?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(
    sent.some(
      (item) => item.url === "/v1/lead-desk/leads/bulk-jobs/job-t/undo",
    ),
  ).toBe(true);
});

it("takes a tag off many leads with the same job", async () => {
  const selection = {
    kind: "filter" as const,
    filter: { scope: "team" as const, tag: HOT },
    total: 12,
  };
  await act(async () =>
    root.render(
      <TagSheet
        open
        target={{ kind: "many", selection }}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await settle();
  await act(async () => button("Take tags off")?.click());
  // The words follow the mode, and nothing is made while taking tags off.
  expect(document.body.textContent).toContain("Take tags off 12 leads");
  expect(document.body.textContent).toContain("Pick the tags to take off.");
  const find = document.querySelector<HTMLInputElement>(
    'input[aria-label="Find a tag"]',
  )!;
  await type(find, "Brand new");
  expect(document.body.textContent).not.toContain("Make “Brand new”");
  await type(find, "");
  await act(async () =>
    document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  expect(document.body.textContent).toContain("Hot comes off 12 leads");
  await act(async () => button("Take off 12 leads")?.click());
  await settle();
  expect(
    sent.find((item) => item.url === "/v1/lead-desk/leads/bulk-jobs")?.body,
  ).toMatchObject({
    action: "untag",
    filter: { scope: "team", tag: HOT },
    expected_total: 12,
    tag_ids: [HOT],
  });
});

it("one lead sends only the ticks it changed", async () => {
  const onDone = vi.fn();
  const now: TagChip[] = [
    { tag_id: VIDEO, name: "Nov video ad", colour: "sky" },
  ];
  await act(async () =>
    root.render(
      <TagSheet
        open
        target={{ kind: "one", leadId: LEAD(1), tags: now }}
        onClose={() => undefined}
        onDone={onDone}
      />,
    ),
  );
  await settle();
  expect(button("No change")?.disabled).toBe(true);
  // Hot is listed; the lead's own Nov video ad is ticked but not listed here,
  // so the change is Hot on.
  await act(async () =>
    document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await act(async () => button("Save tags")?.click());
  await settle();
  expect(
    sent.find((item) => item.url === `/v1/lead-desk/leads/${LEAD(1)}/tags`)
      ?.body,
  ).toMatchObject({ add: [HOT], remove: [] });
  expect(onDone).toHaveBeenCalledWith([
    { tag_id: HOT, name: "Hot", colour: "mint" },
  ]);
});

it("a row shows a few small chips and +N for the rest", async () => {
  const chips: TagChip[] = [
    { tag_id: "a", name: "Hot", colour: "rose" },
    { tag_id: "b", name: "Nov video ad", colour: "sky" },
    { tag_id: "c", name: "Solar", colour: "lime" },
  ];
  await act(async () => root.render(<TagChips tags={chips} max={1} />));
  expect(host.textContent).toBe("Hot+2");
  expect(host.querySelector("[title]")?.getAttribute("title")).toBe(
    "Hot, Nov video ad, Solar",
  );
  await act(async () => root.render(<TagChips tags={[]} />));
  expect(host.textContent).toBe("");
});

it("a lead with ten tags takes no eleventh: the rest wait and the note says why", async () => {
  listed = Array.from({ length: 11 }, (_, index) =>
    tag(`00000000-0000-4000-8000-0000000002${10 + index}`, `T${index}`, 1),
  );
  const ten: TagChip[] = listed
    .slice(0, 10)
    .map(({ tag_id, name }) => ({ tag_id, name, colour: "sky" }));
  await act(async () =>
    root.render(
      <TagSheet
        open
        target={{ kind: "one", leadId: LEAD(1), tags: ten }}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await settle();
  const boxes = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
  );
  expect(boxes).toHaveLength(11);
  expect(boxes[10].disabled).toBe(true);
  expect(document.body.textContent).toContain("Up to 10 tags on a lead");
  // Untick one: the eleventh can go on.
  await act(async () => boxes[0].click());
  expect(boxes[10].disabled).toBe(false);
});

it("Manage tags renames and recolours one tag by its revision", async () => {
  await act(async () =>
    root.render(<ManageTagsSheet open onClose={() => undefined} />),
  );
  await settle();
  expect(document.body.textContent).toContain("12 leads");
  await act(async () =>
    document.querySelector<HTMLButtonElement>("[aria-expanded]")!.click(),
  );
  expect(button("Save")?.disabled).toBe(true);
  const input = document.querySelector<HTMLInputElement>('input[type="text"]')!;
  await type(input, "Warm");
  await act(async () =>
    document.querySelector<HTMLButtonElement>('[aria-label="Violet"]')!.click(),
  );
  await act(async () => button("Save")?.click());
  await settle();
  expect(
    sent.find(
      (item) =>
        item.url === `/v1/lead-desk/tags/${HOT}` && item.body !== undefined,
    )?.body,
  ).toEqual({ expected_revision: 1, name: "Warm", colour: "violet" });
  expect(notices.at(-1)?.title).toBe("Saved “Warm”");
  expect(document.body.textContent).toContain("Warm");
});

it("Manage tags asks before deleting and says how many leads lose it", async () => {
  await act(async () =>
    root.render(<ManageTagsSheet open onClose={() => undefined} />),
  );
  await settle();
  await act(async () =>
    document.querySelector<HTMLButtonElement>("[aria-expanded]")!.click(),
  );
  await act(async () => button("Delete")?.click());
  expect(document.body.textContent).toContain(
    "Delete “Hot”? It comes off 12 leads; their history keeps it.",
  );
  expect(sent.some((item) => item.url.endsWith("/delete"))).toBe(false);
  await act(async () => button("Delete tag")?.click());
  await settle();
  expect(
    sent.find((item) => item.url === `/v1/lead-desk/tags/${HOT}/delete`)?.body,
  ).toEqual({ expected_revision: 1 });
  expect(notices.at(-1)?.title).toBe("Deleted “Hot”");
  expect(document.body.textContent).toContain("No tags yet");
});

it("a tag changed elsewhere says so and reads the tags again", async () => {
  stale = true;
  await act(async () =>
    root.render(<ManageTagsSheet open onClose={() => undefined} />),
  );
  await settle();
  const reads = () =>
    sent.filter((item) => item.url === "/v1/lead-desk/tags").length;
  const before = reads();
  await act(async () =>
    document.querySelector<HTMLButtonElement>("[aria-expanded]")!.click(),
  );
  await type(
    document.querySelector<HTMLInputElement>('input[type="text"]')!,
    "Cold",
  );
  await act(async () => button("Save")?.click());
  await settle();
  expect(notices.at(-1)).toMatchObject({
    tone: "error",
    title: "That tag wasn't saved",
  });
  expect(reads()).toBeGreaterThan(before);
});

it("the tag filter offers Manage tags to managers only", async () => {
  const onChange = vi.fn();
  await act(async () => root.render(<TagPick more={{}} onChange={onChange} />));
  await settle();
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-haspopup="listbox"]')!
      .click(),
  );
  expect(button("Manage tags")).toBeTruthy();
  await act(async () => button("Manage tags")!.click());
  await settle();
  expect(document.body.textContent).toContain(
    "Rename, recolour or delete your team's tags.",
  );
  act(() => root.unmount());
  root = createRoot(host);
  canChange = false;
  forgetTags();
  await act(async () => root.render(<TagPick more={{}} onChange={onChange} />));
  await settle();
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('[aria-haspopup="listbox"]')!
      .click(),
  );
  expect(document.body.textContent).toContain("Any tag");
  expect(button("Manage tags")).toBeUndefined();
});

it("a filter on a tag deleted since shows every lead again", async () => {
  const onChange = vi.fn();
  const GONE = "00000000-0000-4000-8000-0000000000ff";
  await act(async () =>
    root.render(<TagPick more={{ tag: GONE }} onChange={onChange} />),
  );
  await settle();
  expect(onChange).toHaveBeenCalledWith({ tag: null });
});

it("each chip wears its tag's own colour", async () => {
  const chips: TagChip[] = [
    { tag_id: "a", name: "Hot", colour: "rose" },
    { tag_id: "b", name: "Solar", colour: "lime" },
  ];
  await act(async () => root.render(<TagChips tags={chips} max={2} />));
  expect(
    Array.from(host.querySelectorAll("[data-colour]")).map((chip) =>
      chip.getAttribute("data-colour"),
    ),
  ).toEqual(["rose", "lime"]);
});
