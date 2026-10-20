// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Mail } from "lucide-react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BrandTile } from "./brand-tile";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  // No artwork in tests: the library falls back to its own placeholder.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 })),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("draws a library logo, a corner logo, or our own icon, on a decorative tile", async () => {
  await act(async () =>
    root.render(
      <>
        <BrandTile brands={["facebook", "instagram"]} size={40} />
        <BrandTile icon={Mail} />
        <BrandTile brands={["not-a-brand"]} icon={Mail} />
      </>,
    ),
  );
  const tiles = [...host.querySelectorAll<HTMLElement>("[data-kind]")];
  expect(tiles.map((tile) => [tile.dataset.kind, tile.dataset.brand])).toEqual([
    ["brand", "facebook"],
    ["icon", undefined],
    ["icon", undefined],
  ]);
  expect(
    tiles.every((tile) => tile.getAttribute("aria-hidden") === "true"),
  ).toBe(true);
  expect(tiles[0].style.getPropertyValue("--tile")).toBe("40px");
  expect(tiles[0].querySelector('[data-brand="instagram"]')).not.toBeNull();
  expect(tiles[1].querySelector("svg")).not.toBeNull();
});
