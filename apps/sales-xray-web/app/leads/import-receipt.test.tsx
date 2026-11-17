import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it } from "vitest";

import { phoneSummary, summaryLines } from "./import-assign";
import { ImportReceipt } from "./import-receipt";
import type { RowView } from "./import-rows";
import type { ImportPreview, ImportResult } from "./leads-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Lead import I4 (owner's picks, 17 Nov 2026): "When you import" line by line (I4-A,
// more colourful) and the receipt with Undo (I4-B). Made-up people only.
let root: Root | undefined;
let host: HTMLDivElement | undefined;

afterEach(async () => {
  const mounted = root;
  if (mounted) await act(async () => mounted.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
});

const row = (outcome: RowView["outcome"], index: number): RowView => ({
  row: index,
  outcome,
  name: "",
  phone: "",
  city: "",
  stage: "",
  leadName: null,
  sameAs: null,
});

it("says what Import does, each line with its own tone", () => {
  const lines = summaryLines({
    rows: [
      row("new", 0),
      row("new", 1),
      row("known", 2),
      row("repeat", 3),
      row("blank", 4),
    ],
    fresh: 2,
    side: "cold",
    owners: "Farah Shaikh 1",
    whoLine: "Asha Example 1.",
    stageLine: "Stages from your file",
    keptWords: "left as it is",
  });
  expect(lines.map((line) => [line.key, line.tone])).toEqual([
    ["new", "good"],
    ["who", "info"],
    ["stage", "action"],
    ["known", "muted"],
    ["repeat", "muted"],
    ["cant", "problem"],
  ]);
  expect(lines[1].text).toBe("From your file: Farah Shaikh 1");
  expect(lines[1].sub).toBe("The rest: Asha Example 1.");
  expect(lines[3].text).toBe("1 already a lead · left as it is");
  expect(lines[5].text).toBe("1 row can't be added");
  expect(phoneSummary(9, 2, 3)).toBe(
    "9 new leads · 2 sellers · 3 not imported",
  );
  expect(phoneSummary(1, 0, 0)).toBe("1 new lead");
});

it("shows the receipt: who got them, what wasn't imported, and Undo", async () => {
  const preview: ImportPreview = {
    file_name: "expo.csv",
    headers: ["Name", "Phone"],
    rows: [
      { Name: "Asha Example", Phone: "98760 75001" },
      { Name: "Ravi Sample", Phone: "98760 75002" },
      { Name: "Meera Demo", Phone: "98760 75001" },
    ],
    total_rows: 3,
    truncated: false,
    mapping: { name: "Name", phone: "Phone" },
    with_phone: 3,
    repeats_in_file: 1,
  };
  const result: ImportResult = {
    created: 2,
    repeats: 1,
    skipped: 0,
    assigned: 2,
    waiting: 0,
    side: "cold",
    owned: 1,
    staged: 2,
    given: [{ person_id: "p1", name: "Farah Shaikh", leads: 1 }],
    skipped_rows: [{ row: 2, reason: "Repeated in the file" }],
    import_id: "i1",
    undo_until: "2026-11-19T10:00:00Z",
  };
  const div = document.createElement("div");
  host = div;
  document.body.append(div);
  const made = createRoot(div);
  root = made;
  await act(async () =>
    made.render(
      <ImportReceipt
        result={result}
        preview={preview}
        duplicates="skip"
        stageFromFile
        onUndone={() => undefined}
      />,
    ),
  );
  expect(div.querySelector("h3")?.textContent).toBe("2 leads imported");
  expect(div.textContent).toContain("From expo.csv · just now · in Cold Leads");
  expect(
    [...div.querySelectorAll('[aria-label="Who got them"] li')].map(
      (line) => line.textContent,
    ),
  ).toEqual([
    "Farah Shaikh· 1 lead",
    "Owners from your file· 1 lead",
    "Stage· from your file (2)",
  ]);
  expect(div.querySelector("#import-not")?.textContent).toBe(
    "1 row not imported",
  );
  expect(div.querySelector('[data-not="repeat"]')?.textContent).toBe(
    "1 repeated in your file",
  );
  expect(div.textContent).toContain("Download rows not added (1, with reason)");
  expect(div.textContent).toContain(
    "Removes the 2 new leads, never changes to leads already here. Available for 48 hours in Recent imports.",
  );
});
