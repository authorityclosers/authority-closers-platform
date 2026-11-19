import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ASK_DIPAK_LOCKUP, AskDipakLockup } from "./lockup";

describe("AskDipakLockup", () => {
  it("places the kit's two lockup files under one name", () => {
    const html = renderToStaticMarkup(<AskDipakLockup className="x" />);
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="Ask Dipak"');
    expect(html).toContain(`src="${ASK_DIPAK_LOCKUP.light}"`);
    expect(html).toContain(`src="${ASK_DIPAK_LOCKUP.dark}"`);
    // The pictures are the name's art only: screen readers hear the name once.
    expect(html.match(/alt=""/g)).toHaveLength(2);
  });
});
