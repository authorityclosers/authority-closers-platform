// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("./processing-review-port", () =>
  import("./processing-review-port.dev"),
);
vi.mock("./profile-menu", () => ({
  ProfileMenu: () => null,
}));

import { StandaloneStudio } from "./standalone-studio";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  window.history.replaceState(
    null,
    "",
    "/?new=1&sx-fixture=processing.conversation",
  );
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("mounts the real static processing panel after local health with no operational request", async () => {
  const requests: string[] = [];
  let releaseHealth!: (value: Response) => void;
  const health = new Promise<Response>((resolve) => {
    releaseHealth = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      requests.push(path);
      if (path === "/health") return health;
      throw new Error(`Unexpected fixture request: ${path}`);
    }),
  );
  await act(async () =>
    root.render(
      <StandaloneStudio>
        <div data-testid="operational-studio">Operational studio</div>
      </StandaloneStudio>,
    ),
  );
  expect(container.querySelector('[data-testid="operational-studio"]')).toBeNull();
  expect(container.textContent).toContain("Opening local test state");
  await act(async () => {
    releaseHealth(
      new Response(JSON.stringify({ analysis_read_only: true }), {
        headers: { "content-type": "application/json" },
      }),
    );
    await health;
  });
  expect(container.querySelector('[data-fixture="true"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Example analysis progress"]')).not.toBeNull();
  expect(container.querySelector('[data-stage="C4"]')?.getAttribute("data-state")).toBe("running");
  expect(container.textContent).toContain("Example processing state");
  expect(container.textContent).toContain("No call was uploaded or analysed");
  expect(container.textContent).not.toContain("Check status");
  expect(container.querySelector('audio[src]')).toBeNull();
  expect(container.querySelector('a[href*="?call="]')).toBeNull();
  expect(container.querySelector('[data-testid="operational-studio"]')).toBeNull();
  expect(requests).toEqual(["/health"]);
});

it("keeps the operational studio unmounted when the read-only bridge is unavailable", async () => {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      requests.push(path);
      if (path === "/health")
        return new Response(JSON.stringify({ analysis_read_only: false }), {
          headers: { "content-type": "application/json" },
        });
      throw new Error(`Unexpected fixture request: ${path}`);
    }),
  );
  await act(async () =>
    root.render(
      <StandaloneStudio>
        <div data-testid="operational-studio">Operational studio</div>
      </StandaloneStudio>,
    ),
  );
  expect(container.querySelector('[data-testid="operational-studio"]')).toBeNull();
  expect(container.textContent).toContain("require the read-only review bridge");
  expect(container.querySelector('[data-fixture="true"]')).toBeNull();
  expect(requests).toEqual(["/health"]);
});
