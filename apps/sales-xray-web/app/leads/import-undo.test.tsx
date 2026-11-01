// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { resetBackCloseForTests } from "../ui/back-close";
import { ImportHistory, UndoImportButton, undoneWords } from "./import-undo";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Competitor teardown 22 (1 Nov 2026): Undo import, owners and admins, for 48
// hours, from the import's result and from Recent imports.
const IMPORT = "11111111-1111-4111-8111-111111111111";
const KEPT = "22222222-2222-4222-8222-222222222222";
let host: HTMLDivElement;
let root: Root;
let posted: string[] = [];
beforeEach(() => {
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith(`/imports/${IMPORT}/undo`)) {
        posted.push(String(init?.body));
        return Response.json({
          schema: "lead-desk/1",
          removed: 8,
          kept: [{ lead_id: KEPT, name: "Ravi Fictional", why: "Has a note" }],
        });
      }
      if (url.endsWith("/imports"))
        return Response.json({
          schema: "lead-desk/1",
          imports: [
            {
              import_id: IMPORT,
              file_name: "fictional-list.csv",
              at: new Date(Date.now() - 2 * 3600_000).toISOString(),
              by_name: "Asha Fictional",
              leads: 9,
              undone: false,
              undo_until: new Date(Date.now() + 46 * 3600_000).toISOString(),
            },
          ],
        });
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
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}
const button = (label: string) =>
  [...document.querySelectorAll("button")].filter(
    (item) => item.textContent?.trim() === label,
  );

it("says what an undo did, kept leads included", () => {
  expect(undoneWords({ removed: 8, kept: [] })).toBe("8 leads removed.");
  expect(
    undoneWords({
      removed: 1,
      kept: [{ lead_id: KEPT, name: "Ravi Fictional", why: "Has a note" }],
    }),
  ).toBe("1 lead removed. 1 kept: a seller already worked it.");
  expect(undoneWords({ removed: 0, kept: [] })).toBe("Nothing removed.");
});

it("undoes after one confirm and names each lead it kept, with why", async () => {
  const onUndone = vi.fn();
  await act(async () =>
    root.render(<UndoImportButton importId={IMPORT} onUndone={onUndone} />),
  );
  await act(async () => button("Undo import")[0].click());
  expect(document.body.textContent).toContain("Undo this import?");
  // The confirm's own Undo import, in the sheet.
  const confirm = button("Undo import").at(-1)!;
  await act(async () => confirm.click());
  await flush();
  expect(posted).toHaveLength(1);
  expect(onUndone).toHaveBeenCalledWith(
    expect.objectContaining({ removed: 8 }),
  );
  const text = document.body.textContent ?? "";
  expect(text).toContain("Import undone");
  expect(text).toContain(
    "8 leads removed. 1 kept: a seller already worked it.",
  );
  expect(text).toContain("Ravi Fictional");
  expect(text).toContain("Has a note");
});

it("lists the last imports with their Undo", async () => {
  await act(async () =>
    root.render(<ImportHistory onChanged={() => undefined} />),
  );
  await flush();
  const text = host.textContent ?? "";
  expect(text).toContain("Recent imports");
  expect(text).toContain("fictional-list.csv");
  expect(text).toContain("9 leads · Asha Fictional");
  expect(button("Undo import")).toHaveLength(1);
});
