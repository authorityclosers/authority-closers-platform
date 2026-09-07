import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ACADEMY_ARTWORK } from "@ac/ui";

import { CourseArtwork, InstructorPortrait } from "./course-artwork";

describe("trusted academy artwork primitives", () => {
  it.each(Object.keys(ACADEMY_ARTWORK) as Array<keyof typeof ACADEMY_ARTWORK>)(
    "%s is decorative intrinsic artwork, never a player, earned badge or title",
    (artwork) => {
      const html = renderToStaticMarkup(<CourseArtwork artwork={artwork} />);
      expect(html).toContain('aria-hidden="true"');
      expect(html).toContain('alt=""');
      expect(html).toContain('width="960"');
      expect(html).toContain('height="840"');
      expect(html).toContain(encodeURIComponent(ACADEMY_ARTWORK[artwork].src));
      expect(html).not.toMatch(
        /<video|<iframe|<button|<a\s|<h[1-6]|progress|completed/i,
      );
      expect(html).toContain('data-presentation-only="true"');
    },
  );

  it("gives compact rows an explicit small image selection", () => {
    const html = renderToStaticMarkup(<CourseArtwork compact />);
    expect(html).toContain("academy-artwork--compact");
    expect(html).toContain('sizes="64px"');
  });

  it("names the verified portrait only when it contributes editorial identity", () => {
    const html = renderToStaticMarkup(<InstructorPortrait priority />);
    expect(html).toContain(
      'alt="Dipak Vishwakarma, your guide at Closers Academy"',
    );
    expect(html).toContain('width="3074"');
    expect(html).toContain('height="3864"');
    expect(html).toContain("instructor-v2%2Ffront-facing.jpeg");
    expect(html).toContain("/_next/image?");
    expect(html).toContain("srcSet=");
    const decorative = renderToStaticMarkup(
      <InstructorPortrait decorative fill />,
    );
    expect(decorative).toContain('alt=""');
    expect(decorative).not.toContain("your guide");
  });
});
