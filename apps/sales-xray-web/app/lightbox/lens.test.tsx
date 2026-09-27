import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Lens, lensStates } from "./lens";

function render(markup: string) {
  const host = document.createElement("div");
  host.innerHTML = markup;
  return host;
}

// The HTML parser may or may not restore SVG attribute case (viewBox).
function attr(element: Element, name: string) {
  return (
    [...element.attributes].find(
      (attribute) => attribute.name.toLowerCase() === name.toLowerCase(),
    )?.value ?? null
  );
}

function references(svg: Element) {
  return [...svg.querySelectorAll("*")].flatMap((element) =>
    [...element.attributes].flatMap((attribute) =>
      [...attribute.value.matchAll(/url\(#([^)]+)\)/g)].map(
        (match) => match[1],
      ),
    ),
  );
}

describe("Lens", () => {
  it.each(lensStates)("renders the %s pose as decorative SVG", (state) => {
    const svg = render(
      renderToStaticMarkup(<Lens state={state} />),
    ).firstElementChild!;
    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(attr(svg, "aria-hidden")).toBe("true");
    expect(attr(svg, "focusable")).toBe("false");
    expect(attr(svg, "data-lens-state")).toBe(state);
    expect(attr(svg, "viewBox")).toBe(
      state === "writing" ? "0 0 120 140" : "0 0 120 120",
    );
    expect(svg.querySelector("title, text")).toBeNull();
  });

  it("gives every instance unique SVG ids and keeps references local", () => {
    const host = render(
      renderToStaticMarkup(
        <>
          {lensStates.map((state) => (
            <Lens key={`a-${state}`} state={state} />
          ))}
          {lensStates.map((state) => (
            <Lens key={`b-${state}`} state={state} />
          ))}
        </>,
      ),
    );
    const svgs = [...host.querySelectorAll("svg")];
    expect(svgs).toHaveLength(lensStates.length * 2);
    const ids = [...host.querySelectorAll("[id]")].map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
    for (const svg of svgs) {
      const local = new Set(
        [...svg.querySelectorAll("[id]")].map((element) => element.id),
      );
      const used = references(svg);
      expect(used.length).toBeGreaterThan(0);
      for (const id of used) expect(local.has(id)).toBe(true);
    }
  });

  it("scales the tall writing pose without distortion", () => {
    const svg = render(
      renderToStaticMarkup(<Lens state="writing" size={120} />),
    ).firstElementChild!;
    expect(attr(svg, "width")).toBe("120");
    expect(attr(svg, "height")).toBe("140");
  });

  it("uses tokens instead of the source asset colours, and freezes under reduced motion", () => {
    const markup = lensStates
      .map((state) => renderToStaticMarkup(<Lens state={state} />))
      .join("");
    expect(markup).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    const css = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "lens.module.css"),
      "utf8",
    );
    const reduced = css.slice(
      css.indexOf("@media (prefers-reduced-motion: reduce)"),
    );
    expect(reduced).toMatch(/\.lens \*\s*\{\s*animation: none !important;/);
    expect(css).toMatch(/\[data-motion-suspended="true"\]\) \.lens \*/);
  });
});
