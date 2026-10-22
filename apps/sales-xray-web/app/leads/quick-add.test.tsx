// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: vi.fn() }));

import { QuickAddBar } from "./quick-add";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Quick add (owner P0, 23 Oct 2026): a name, Tab, a number, Enter, and the
// lead is in; the line empties for the next one.
let host: HTMLDivElement;
let root: Root;
let posted: unknown[];
let known: boolean;

beforeEach(() => {
  posted = [];
  known = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/leads/match"))
        return Response.json(
          known
            ? {
                found: true,
                lead_id: "00000000-0000-4000-8000-000000000001",
                name: "ravi sample",
                stage_label: "Interested",
              }
            : { found: false },
        );
      if (url.endsWith("/v1/lead-desk/leads") && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return Response.json({}, { status: 201 });
      }
      return Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const box = (label: string) =>
  host.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
const type = async (input: HTMLInputElement, value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const press = async (input: HTMLInputElement, key: string) =>
  act(async () => {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });
const settle = async () =>
  act(async () => {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  });

it("adds a lead on Enter, to the pipeline in view, and empties the line", async () => {
  const onAdded = vi.fn();
  await act(async () =>
    root.render(<QuickAddBar pipeline="partner_outreach" onAdded={onAdded} />),
  );
  await type(box("New lead's name"), "  asha example ");
  await type(box("New lead's phone"), "98765 43210");
  await press(box("New lead's phone"), "Enter");
  await settle();
  expect(posted).toHaveLength(1);
  expect(posted[0]).toMatchObject({
    source: "manual",
    name: "asha example",
    phone: "98765 43210",
    assign: "rules",
    pipeline: "partner_outreach",
  });
  expect(onAdded).toHaveBeenCalledTimes(1);
  expect(box("New lead's name").value).toBe("");
  expect(box("New lead's phone").value).toBe("");
});

it("needs a name, and Escape clears the line", async () => {
  await act(async () =>
    root.render(<QuickAddBar pipeline={null} onAdded={() => undefined} />),
  );
  await type(box("New lead's phone"), "98765 43210");
  await press(box("New lead's phone"), "Enter");
  await settle();
  expect(posted).toHaveLength(0);
  await type(box("New lead's name"), "asha");
  await press(box("New lead's name"), "Escape");
  expect(box("New lead's name").value).toBe("");
  expect(box("New lead's phone").value).toBe("");
});

it("says a number is already a lead, and doesn't add it again", async () => {
  vi.useFakeTimers();
  known = true;
  await act(async () =>
    root.render(<QuickAddBar pipeline={null} onAdded={() => undefined} />),
  );
  await type(box("New lead's name"), "ravi again");
  await type(box("New lead's phone"), "+91 98765 43210");
  await act(async () => vi.advanceTimersByTime(450));
  await settle();
  expect(host.textContent).toContain(
    "Already a lead: Ravi Sample · Interested",
  );
  const add = host.querySelector<HTMLButtonElement>("button")!;
  expect(add.disabled).toBe(true);
  await press(box("New lead's name"), "Enter");
  await settle();
  expect(posted).toHaveLength(0);
});

it("hands rows pasted from a sheet to the import, and keeps one name or number", async () => {
  const onPasteRows = vi.fn();
  await act(async () =>
    root.render(
      <QuickAddBar
        pipeline={null}
        onAdded={() => undefined}
        onPasteRows={onPasteRows}
      />,
    ),
  );
  const paste = async (input: HTMLInputElement, text: string) => {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { getData: () => text },
    });
    await act(async () => input.dispatchEvent(event));
    return event;
  };
  expect(box("New lead's name").placeholder).toBe(
    "New lead's name, or paste rows",
  );
  const rows = "Asha\t98765 43210\nRavi\t91234 56789";
  expect((await paste(box("New lead's name"), rows)).defaultPrevented).toBe(
    true,
  );
  expect(onPasteRows).toHaveBeenCalledWith(rows);
  expect(
    (await paste(box("New lead's phone"), "98765 43210")).defaultPrevented,
  ).toBe(false);
  expect(onPasteRows).toHaveBeenCalledTimes(1);
});
