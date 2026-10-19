// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import type { DetailObject } from "./call-detail-data";
import { ObjectsTable } from "./objects-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const object = (
  id: string,
  state: DetailObject["state"],
  basis: string | null,
  display: string,
): DetailObject => ({
  objectId: id,
  type: "need",
  category: "Needs and goals",
  display,
  confidence: 0.9,
  basis,
  pipeline: "deep",
  version: "deep/1",
  runId: null,
  supersedesId: null,
  state,
  createdAt: null,
  decisions: [],
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("says whose word each object is and shows current objects first", async () => {
  await act(async () =>
    root.render(
      <ObjectsTable
        objects={[
          object("a", "current", "confirmed", "Wants site visits"),
          object("b", "current", "inferred", "Worried about scope"),
          object("d", "current", "person", "Budget is fixed"),
          object("c", "erased", "observed", ""),
        ]}
      />,
    ),
  );
  const rows = () =>
    [...host.querySelectorAll("tbody tr")].map((row) => row.textContent);
  expect(rows()).toHaveLength(3);
  expect(rows()[0]).toContain("Person · confirmed");
  expect(rows()[1]).toContain("AI · inferred");
  expect(rows()[2]).toContain("Person");
  expect(rows()[2]).not.toContain("Person · person");
  expect(rows()[0]).toContain("90%");
  const erased = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith("Erased"),
  )!;
  await act(async () => erased.click());
  expect(rows()).toEqual([expect.stringContaining("Erased")]);
  expect(host.textContent).toContain("1 shown");
});
