import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FindingEvidence } from "./finding-evidence";
import { ReportReadingProvider } from "./report-reading-context";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it("keeps full quotations and immediate playback available when switching report views", async () => {
  const listen = vi.fn();
  const quote =
    "Receivables were corrected from 20 to 15 lakh; no payment was confirmed. ".repeat(
      8,
    );
  const render = (reading: boolean) =>
    root.render(
      <ReportReadingProvider reading={reading}>
        <FindingEvidence count={1}>
          <blockquote>{quote}</blockquote>
          <button type="button" onClick={listen}>
            Listen with context
          </button>
        </FindingEvidence>
      </ReportReadingProvider>,
    );

  await act(async () => render(true));
  for (const reading of [true, false, true]) {
    await act(async () => render(reading));
    const evidence = container.querySelector('[role="group"]')!;
    expect(evidence.textContent).toContain(quote);
    expect(evidence.textContent).toContain("1 moment");
    expect(evidence.closest("details,[hidden]")).toBeNull();
    expect(evidence.querySelector("details,summary,[hidden]")).toBeNull();
    expect(
      container.querySelector(
        `#${CSS.escape(evidence.getAttribute("aria-labelledby")!)}`,
      )?.textContent,
    ).toContain("Evidence from this call");
    await act(async () => container.querySelector("button")!.click());
  }
  expect(listen).toHaveBeenCalledTimes(3);
  await act(async () => window.dispatchEvent(new Event("beforeprint")));
  await act(async () => window.dispatchEvent(new Event("afterprint")));
  expect(container.querySelector("blockquote")?.textContent).toBe(quote);
});

it("labels multiple evidence groups independently and omits empty groups", async () => {
  await act(async () =>
    root.render(
      <>
        <FindingEvidence count={0}>
          <p>No evidence should leak here.</p>
        </FindingEvidence>
        <FindingEvidence count={2}>
          <blockquote>First finding evidence.</blockquote>
        </FindingEvidence>
        <FindingEvidence count={1}>
          <blockquote>Second finding evidence.</blockquote>
        </FindingEvidence>
      </>,
    ),
  );
  const groups = [...container.querySelectorAll('[role="group"]')];
  expect(groups).toHaveLength(2);
  const ids = groups.map((group) => group.getAttribute("aria-labelledby"));
  expect(new Set(ids).size).toBe(2);
  expect(container.textContent).not.toContain("No evidence should leak here.");
  expect(groups[0].textContent).toContain("2 moments");
});
