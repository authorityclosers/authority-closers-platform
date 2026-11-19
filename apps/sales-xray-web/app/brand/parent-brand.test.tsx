import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  PARENT_ART,
  PARENT_LOGO,
  PARENT_MARK,
  PARENT_NAME,
  ParentEndorsement,
  ParentLogo,
} from "./parent-brand";

describe("ParentEndorsement", () => {
  it("shows the Point endorsement art under one name (owner's order, 19 Nov 2026)", () => {
    expect(PARENT_MARK).toBe("point");
    const html = renderToStaticMarkup(<ParentEndorsement />);
    expect(html).toContain(`aria-label="${PARENT_NAME}"`);
    expect(html).toContain(PARENT_ART.light.replace(/&/g, "&amp;"));
    expect(html).toContain(PARENT_ART.dark.replace(/&/g, "&amp;"));
    expect(html.match(/alt=""/g)).toHaveLength(2);
    // The kit's own endorsement file, shown in part, never a redrawn mark.
    expect(PARENT_ART.light).toMatch(
      /^\/brand\/authority-closers\/endorse-sales-x-ray-light\.svg#svgView\(viewBox\(/,
    );
  });

  it("swaps back to the words with one switch", () => {
    const html = renderToStaticMarkup(
      <ParentEndorsement mark="text" className="by" />,
    );
    expect(html).toBe('<span class="by">by Authority Closers</span>');
  });
});

describe("ParentLogo", () => {
  it("places the Point horizontal lockup files, or the name as words", () => {
    const html = renderToStaticMarkup(<ParentLogo />);
    expect(html).toContain('aria-label="Authority Closers"');
    expect(html).toContain(`src="${PARENT_LOGO.light}"`);
    expect(html).toContain(`src="${PARENT_LOGO.dark}"`);
    expect(renderToStaticMarkup(<ParentLogo mark="text" />)).toBe(
      "<span>Authority Closers</span>",
    );
  });
});
