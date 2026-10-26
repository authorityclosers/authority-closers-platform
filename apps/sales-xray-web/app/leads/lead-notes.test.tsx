import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  addNote: vi.fn(async () => ({ lead: { lead_id: "l1" }, events: [] })),
}));
vi.mock("../ui/haptics", () => ({ haptic: vi.fn(), tick: vi.fn() }));

import { addNote } from "./leads-client";
import { NoteBox, wordCount } from "./lead-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, #30 (26 Oct 2026): a composer that grows, counts as you type, and
// whose send comes alive with text and says Saved.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.mocked(addNote).mockClear();
});

const type = (field: HTMLTextAreaElement, value: string) => {
  Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )!.set!.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
};

it("counts words as a person does", () => {
  expect(wordCount("")).toBe(0);
  expect(wordCount("   ")).toBe(0);
  expect(wordCount("  call   back tomorrow ")).toBe(3);
  expect(wordCount("one\nsecond line")).toBe(3);
});

it("comes alive with text, counts it, and says Saved once the note is on the lead", async () => {
  const onSaved = vi.fn();
  await act(async () => root.render(<NoteBox leadId="l1" onSaved={onSaved} />));
  const field = host.querySelector("textarea")!;
  const send = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Add note"]',
  )!;
  // No resize grip: the field grows instead.
  expect(field.getAttribute("rows")).toBe("2");
  expect(send.disabled).toBe(true);
  await act(async () => type(field, "Wants a site visit"));
  expect(send.disabled).toBe(false);
  expect(host.querySelector("[data-filled]")).not.toBeNull();
  expect(host.querySelector("#lead-note-count-l1")?.textContent).toBe(
    "4 words · 18/1000",
  );
  await act(async () => send.click());
  expect(addNote).toHaveBeenCalledWith("l1", "Wants a site visit");
  expect(onSaved).toHaveBeenCalledOnce();
  expect(field.value).toBe("");
  expect(host.querySelector('[role="status"]')?.textContent).toBe("Saved");
  expect(send.disabled).toBe(true);
});
