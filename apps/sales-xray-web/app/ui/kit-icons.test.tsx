import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import * as Lucide from "lucide-react";
import * as Inline from "@ac/ui/kit/icons";

const names = [
  "ArrowDownRight",
  "ArrowUpRight",
  "ChevronLeft",
  "ChevronRight",
  "Info",
  "Minus",
  "Pencil",
  "X",
  "BellRing",
  "Siren",
] as const;

it.each(names)(
  "keeps %s SVG markup identical to Sales X-Ray's Lucide icon",
  (name) => {
    for (const props of [
      { size: 18 },
      { size: 13, strokeWidth: 1.75, "aria-hidden": "true" as const },
      { size: 28, className: "existing-class", "aria-label": "Action" },
    ]) {
      // Attribute order has no effect on DOM. Every attribute and child must match.
      const dom = (markup: string) => {
        const host = document.createElement("div");
        host.innerHTML = markup;
        const visit = (element: Element): unknown => ({
          tag: element.tagName,
          attributes: Object.fromEntries(
            [...element.attributes]
              .map(({ name, value }) => [name, value])
              .sort(),
          ),
          children: [...element.children].map(visit),
        });
        return visit(host.firstElementChild!);
      };
      expect(
        dom(renderToStaticMarkup(createElement(Inline[name], props))),
      ).toEqual(dom(renderToStaticMarkup(createElement(Lucide[name], props))));
    }
  },
);
