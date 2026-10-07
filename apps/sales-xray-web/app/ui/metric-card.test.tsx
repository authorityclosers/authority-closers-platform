// @vitest-environment happy-dom
import { FolderOpen } from "lucide-react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { MetricBand, MetricCard, MetricDelta } from "./metric-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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
});

it("renders metric value, unit, label and explicit context", async () => {
  await act(async () => {
    root.render(
      <MetricCard
        label="Calls analysed"
        value={42}
        unit="calls"
        context="Last 30 days"
        source="Verified audio uploads"
        icon={FolderOpen}
        iconTone="teal"
      />,
    );
  });

  expect(host.textContent).toContain("42");
  expect(host.textContent).toContain("calls");
  expect(host.textContent).toContain("Calls analysed");
  expect(host.textContent).toContain("Last 30 days");
  expect(host.textContent).toContain("Verified audio uploads");
});

it("renders '—' for unknown/null values distinct from zero", async () => {
  await act(async () => {
    root.render(
      <MetricCard
        label="Reports ready"
        value={null}
        context="Not available yet"
      />,
    );
  });

  expect(host.textContent).toContain("—");
  expect(host.textContent).not.toContain("0");
  expect(host.textContent).toContain("Not available yet");
});

it("renders '0' distinctly when value is zero", async () => {
  await act(async () => {
    root.render(
      <MetricCard label="Needs attention" value={0} context="Calls to check" />,
    );
  });

  expect(host.textContent).toContain("0");
  expect(host.textContent).not.toContain("—");
});

it("renders loading skeleton with accessible aria-label", async () => {
  await act(async () => {
    root.render(
      <MetricCard label="Calls analysed" value={null} status="loading" />,
    );
  });

  const skeleton = host.querySelector('[aria-label="Loading"]');
  expect(skeleton).not.toBeNull();
});

it("renders MetricDelta with accessible arrow, percentage, and screen reader text", async () => {
  await act(async () => {
    root.render(
      <div>
        <MetricDelta value={15} previous={10} label="vs prior 30d" />
        <MetricDelta value={5} previous={10} label="vs prior 30d" />
        <MetricDelta value={10} previous={10} />
        <MetricDelta value={5} previous={0} />
        <MetricDelta value={0} previous={0} />
      </div>,
    );
  });

  // +50%
  expect(host.textContent).toContain("50%");
  expect(host.textContent).toContain("increase: ");

  // -50%
  expect(host.textContent).toContain("decrease: ");

  // flat
  expect(host.textContent).toContain("0%");

  // new
  expect(host.textContent).toContain("new");
});

it("renders MetricBand as an accessible labelled container", async () => {
  await act(async () => {
    root.render(
      <MetricBand label="Sales Xray key numbers" columns={4}>
        <MetricCard label="Card 1" value={1} />
        <MetricCard label="Card 2" value={2} />
      </MetricBand>,
    );
  });

  const band = host.querySelector(
    'section[aria-label="Sales Xray key numbers"]',
  );
  expect(band).not.toBeNull();
  expect(band?.getAttribute("data-columns")).toBe("4");
});
