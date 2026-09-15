import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { LiveDataBanner } from "./live-data-banner";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("makes live production mutation scope explicit", async () => {
  await act(async () => root.render(<LiveDataBanner />));
  expect(container.textContent).toContain("live AC data");
  expect(container.textContent).toContain("affects real data");
  expect(container.querySelector('[role="note"]')).not.toBeNull();
});
