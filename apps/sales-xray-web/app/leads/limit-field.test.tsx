import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import {
  LimitField,
  limitDraft,
  openWords,
  overBy,
  readLimit,
  type LimitDraft,
} from "./limit-field";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let seen: LimitDraft | null;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  seen = null;
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function Harness({ start }: { start: number | null }) {
  const [draft, setDraft] = useState(limitDraft(start));
  return (
    <LimitField
      id="limit"
      label="Most open leads at once"
      hint="Organisation default"
      draft={draft}
      onChange={(next) => {
        seen = next;
        setDraft(next);
      }}
    />
  );
}

it("reads a limit as a number, No limit, or not valid", () => {
  expect(readLimit(limitDraft(50))).toBe(50);
  expect(readLimit(limitDraft(null))).toBeNull();
  expect(readLimit({ none: false, value: "0" })).toBeUndefined();
  expect(readLimit({ none: false, value: "1001" })).toBeUndefined();
  expect(readLimit({ none: false, value: "" })).toBeUndefined();
  expect(readLimit({ none: false, value: " 12 " })).toBe(12);
});

it("says open leads against the limit, and how far over it is", () => {
  expect(openWords(31, 50)).toBe("31/50");
  expect(openWords(168, null)).toBe("168");
  expect(overBy({ open_leads: 168, max_open: 50 })).toBe(118);
  expect(overBy({ open_leads: 168, max_open: null })).toBe(0);
  expect(overBy({ open_leads: 168, max_open: 50, over_capacity: 100 })).toBe(
    100,
  );
});

it("turns No limit on and off, keeping the number for later", async () => {
  await act(async () => root.render(<Harness start={40} />));
  const number = host.querySelector<HTMLInputElement>("#limit")!;
  const none = host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(host.querySelector("legend")?.textContent).toBe(
    "Most open leads at once",
  );
  expect(host.textContent).toContain("Organisation default");
  expect(number.value).toBe("40");
  await act(async () => none.click());
  expect(number.disabled).toBe(true);
  expect(number.value).toBe("");
  expect(seen).toEqual({ none: true, value: "40" });
  await act(async () => none.click());
  expect(number.value).toBe("40");
  expect(readLimit(seen!)).toBe(40);
});
