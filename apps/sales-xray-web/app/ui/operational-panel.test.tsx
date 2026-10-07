// @vitest-environment happy-dom
import { FolderOpen } from "lucide-react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { OperationalEmpty, OperationalPanel } from "./operational-panel";

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

it("renders panel title with caller-supplied heading level and accessible label", async () => {
  await act(async () => {
    root.render(
      <OperationalPanel
        id="test-panel"
        title="Last 30 days"
        headingLevel="h2"
        sub="Calls analysed each day"
      >
        <p>Panel content</p>
      </OperationalPanel>,
    );
  });

  const heading = host.querySelector("h2#test-panel-title");
  expect(heading).not.toBeNull();
  expect(heading?.textContent).toBe("Last 30 days");

  const section = host.querySelector("section#test-panel");
  expect(section?.getAttribute("aria-labelledby")).toBe("test-panel-title");
  expect(host.textContent).toContain("Calls analysed each day");
  expect(host.textContent).toContain("Panel content");
});

it("renders tools and action link with icon", async () => {
  await act(async () => {
    root.render(
      <OperationalPanel
        title="Recent calls"
        action={{
          href: "/analysis/calls",
          label: "View all calls",
          badge: "+5",
        }}
        tools={<button type="button">Filter</button>}
      >
        <div>Content</div>
      </OperationalPanel>,
    );
  });

  const link = host.querySelector('a[href="/analysis/calls"]');
  expect(link).not.toBeNull();
  expect(link?.textContent).toContain("View all calls");
  expect(link?.textContent).toContain("+5");

  const button = host.querySelector("button");
  expect(button?.textContent).toBe("Filter");
});

it("renders foot content when provided", async () => {
  await act(async () => {
    root.render(
      <OperationalPanel title="Summary" foot={<span>India Standard Time</span>}>
        <div>Body</div>
      </OperationalPanel>,
    );
  });

  expect(host.textContent).toContain("India Standard Time");
});

it("renders OperationalEmpty with accessible elements and action", async () => {
  await act(async () => {
    root.render(
      <OperationalEmpty
        icon={FolderOpen}
        title="No calls yet"
        description="Upload a sales call to start your analysis."
        action={<button type="button">New analysis</button>}
      />,
    );
  });

  expect(host.textContent).toContain("No calls yet");
  expect(host.textContent).toContain(
    "Upload a sales call to start your analysis.",
  );
  expect(host.querySelector("button")?.textContent).toBe("New analysis");
});
