import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import { SalesSkills } from "./sales-skills";
import type { ReportDimension } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const dimensions = fixture.report.dimensions as ReportDimension[];
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
function button(label: string) {
  const found = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find(
    (item) =>
      item.getAttribute("aria-label") === label ||
      item.textContent?.replace(/[←→]/g, "").trim() === label,
  );
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
}
it("renders every supplied topic without inventing grades or audio links", async () => {
  await act(async () => root.render(<SalesSkills dimensions={dimensions} />));
  expect(container.querySelectorAll("article")).toHaveLength(8);
  for (const dimension of dimensions)
    expect(container.textContent).toContain(dimension.label);
  expect(container.textContent).toContain("Draft observations, not scores.");
  expect(container.textContent).not.toMatch(/Strong|Weak|Listen|%/);
  expect(container.querySelectorAll('[data-page-visible="true"]')).toHaveLength(
    4,
  );
  await act(async () => button("Next skills").click());
  expect(
    container.querySelectorAll('[data-page-visible="true"]')[0].textContent,
  ).toContain(dimensions[4].label);
  expect(button("Next skills").disabled).toBe(true);
  await act(async () => button("Previous skills").click());
  expect(button("Previous skills").disabled).toBe(true);
});
it("opens complete notes, navigates all eight, and retains citations as plain references", async () => {
  await act(async () => root.render(<SalesSkills dimensions={dimensions} />));
  const opener = button(`Open notes: ${dimensions[0].label}`);
  opener.focus();
  await act(async () => opener.click());
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain(
    dimensions[0].observation,
  );
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain(
    "Doc-1",
  );
  expect(container.querySelector('[role="dialog"] a')).toBeNull();
  expect(button("Previous skill").disabled).toBe(true);
  for (let index = 1; index < dimensions.length; index++) {
    button("Next skill").focus();
    await act(async () => button("Next skill").click());
    expect(container.querySelector('[role="dialog"] h2')?.textContent).toBe(
      dimensions[index].label,
    );
    expect(document.activeElement).toBe(
      container.querySelector('[role="dialog"] h2'),
    );
  }
  expect(button("Next skill").disabled).toBe(true);
  await act(async () =>
    document.activeElement?.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(document.activeElement).toBe(button("Previous skill"));
  for (let index = dimensions.length - 2; index >= 0; index--) {
    await act(async () => button("Previous skill").click());
    expect(document.activeElement).toBe(
      container.querySelector('[role="dialog"] h2'),
    );
  }
  await act(async () =>
    document.activeElement?.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(document.activeElement).toBe(button("Next skill"));
  await act(async () =>
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(opener);
});
it("keeps mixed or missing evidence neutral and handles an empty report", async () => {
  await act(async () =>
    root.render(
      <SalesSkills
        dimensions={[
          {
            ...dimensions[0],
            status: "conflicted",
            observation: "Exact mixed source observation.",
          },
        ]}
      />,
    ),
  );
  expect(container.textContent).toContain("Mixed evidence");
  expect(container.textContent).toContain("Exact mixed source observation.");
  await act(async () => button(`Open notes: ${dimensions[0].label}`).click());
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain(
    "No recording excerpt was supplied for this skill.",
  );
  expect(container.querySelector('[role="dialog"] button[aria-label^="Listen"]')).toBeNull();
  await act(async () => root.render(<SalesSkills dimensions={[]} />));
  expect(container.textContent).toContain(
    "No skill observations were supplied",
  );
  expect(container.querySelector("article")).toBeNull();
});

it("shows exact skill excerpts and seeks their source, without using coaching citations as audio", async () => {
  const evidence = {
    segment_id: "segment-12",
    quote: "The prospect said the rollout would take two weeks.",
    start_ms: 72_000,
    end_ms: 79_000,
  };
  const onSelectEvidence = vi.fn();
  await act(async () =>
    root.render(
      <SalesSkills
        dimensions={[{ ...dimensions[0], evidence: [evidence] }]}
        onSelectEvidence={onSelectEvidence}
      />,
    ),
  );
  await act(async () => button(`Open notes: ${dimensions[0].label}`).click());
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog?.textContent).toContain(dimensions[0].observation);
  expect(dialog?.textContent).toContain(evidence.quote);
  expect(dialog?.textContent).toContain(
    "01:12.000–01:19.000 · Source segment segment-12",
  );
  expect(dialog?.textContent).toContain("Doc-1");
  expect(dialog?.querySelectorAll('[aria-label^="Listen to"]')).toHaveLength(1);
  await act(async () =>
    button(`Listen to ${dimensions[0].label} excerpt at 01:12.000`).click(),
  );
  expect(onSelectEvidence).toHaveBeenCalledExactlyOnceWith(evidence);
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});
