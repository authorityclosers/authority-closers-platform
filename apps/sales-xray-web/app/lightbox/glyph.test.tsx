import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GLYPHS, Glyph, type GlyphName } from "./glyph";

const here = dirname(fileURLToPath(import.meta.url));
const assets = join(
  here,
  "../../../../docs/design/sales-xray-v02-lightbox-20260924/assets",
);
const publicLightbox = join(here, "../../public/lightbox");

// Git may check files out with CRLF on Windows; content, not line endings, matters.
const read = (path: string) =>
  readFileSync(path, "utf8").replace(/\r\n/g, "\n").trimEnd();

function attributes(element: Element, skip: string[] = []) {
  return Object.fromEntries(
    [...element.attributes]
      .filter((attribute) => !skip.includes(attribute.name.toLowerCase()))
      .map((attribute) => [attribute.name.toLowerCase(), attribute.value]),
  );
}

function lower(record: Readonly<Record<string, string>>) {
  return Object.fromEntries(
    Object.entries(record).map(([name, value]) => [name.toLowerCase(), value]),
  );
}

describe("Lightbox glyphs and public assets", () => {
  it("ships verbatim copies of the source sprite and illustrations", () => {
    for (const file of [
      "glyphs/lightbox-glyphs.svg",
      "illustrations/empty-calls.svg",
      "illustrations/offline.svg",
    ]) {
      const copy = file.replace(/^glyphs\//, "");
      expect(read(join(publicLightbox, copy))).toBe(read(join(assets, file)));
    }
  });

  it("matches every sprite symbol with the same inline geometry", () => {
    const host = document.createElement("div");
    host.innerHTML = read(join(assets, "glyphs/lightbox-glyphs.svg"));
    const symbols = [...host.querySelectorAll("symbol")];
    expect(
      new Set(symbols.map((symbol) => symbol.id.replace(/^lx-/, ""))),
    ).toEqual(new Set(Object.keys(GLYPHS)));
    for (const symbol of symbols) {
      const glyph = GLYPHS[symbol.id.replace(/^lx-/, "") as GlyphName];
      expect([symbol.id, attributes(symbol, ["id"])]).toEqual([
        symbol.id,
        lower(glyph.root),
      ]);
      const children = [...symbol.children].map((child) => ({
        tag: child.tagName.toLowerCase(),
        attrs: attributes(child),
      }));
      expect([symbol.id, children]).toEqual([
        symbol.id,
        glyph.nodes.map((node) => ({
          tag: node.tag,
          attrs: lower(node.attrs),
        })),
      ]);
    }
  });

  it("renders a decorative glyph by default and a named image only when labelled", () => {
    const host = document.createElement("div");
    host.innerHTML =
      renderToStaticMarkup(<Glyph name="focus" />) +
      renderToStaticMarkup(
        <Glyph name="skill-observed" label="Evidence found" />,
      );
    const [decorative, labelled] = [...host.querySelectorAll("svg")];
    expect(decorative.getAttribute("aria-hidden")).toBe("true");
    expect(decorative.getAttribute("role")).toBeNull();
    expect(decorative.getAttribute("stroke-width")).toBe("1.75");
    expect(decorative.children).toHaveLength(4);
    expect(labelled.getAttribute("role")).toBe("img");
    expect(labelled.getAttribute("aria-label")).toBe("Evidence found");
    expect(labelled.getAttribute("aria-hidden")).toBeNull();
  });
});
