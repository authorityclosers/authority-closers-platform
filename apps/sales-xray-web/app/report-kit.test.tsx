import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { Clip, Script } from "./report-kit";
import { RichText } from "./report-entities";
import type { ReportEvidence } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it("keeps generated narrative, source quotes, and scripts textual without prospect provenance", async () => {
  const evidence: ReportEvidence = {
    segment_id: "fictional-segment-1",
    quote: "My brother uses WhatsApp.",
    start_ms: 1_000,
    end_ms: 2_000,
  };
  await act(async () =>
    root.render(
      <>
        <p data-testid="narrative">
          <RichText text="The prospect mentioned WhatsApp." />
        </p>
        <Clip
          evidence={evidence}
          title="Fictional source quote"
          onPlay={() => {}}
        />
        <Script text="You can follow up with WhatsApp." />
      </>,
    ),
  );

  expect(
    container.querySelector('[data-testid="narrative"]')?.textContent,
  ).toBe("The prospect mentioned WhatsApp.");
  expect(container.textContent).toContain("My brother uses WhatsApp.");
  expect(container.textContent).toContain("You can follow up with WhatsApp.");
  expect(container.querySelectorAll('[data-kind="brand"]')).toHaveLength(0);
});
