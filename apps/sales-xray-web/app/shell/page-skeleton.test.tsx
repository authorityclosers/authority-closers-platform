import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { CallOpeningSkeletonContent } from "./call-opening-skeleton";
import { PageSkeleton } from "./page-skeleton";

it("opens a saved call in the Report's outline, not the analysis panel's", () => {
  const markup = renderToStaticMarkup(<CallOpeningSkeletonContent />);
  expect(markup).toContain('data-variant="report"');
  expect(markup).toContain("Opening your saved call");
  expect(markup).toContain('aria-busy="true"');
  // Title, the first pillar's heading, the Big Picture card, then a pair.
  const report = renderToStaticMarkup(<PageSkeleton variant="report" />);
  expect(report.match(/reportCard/g)?.length).toBe(4);
  expect(report).toContain("pillarHead");
  expect(report).toContain('aria-hidden="true"');
  // Taking over from the same outline: no fade-in, so no blank moment.
  expect(
    renderToStaticMarkup(<PageSkeleton variant="report" instant />),
  ).toContain("data-instant");
  expect(report).not.toContain("data-instant");
  // A prospect still opens with the call outline it had.
  expect(renderToStaticMarkup(<PageSkeleton variant="call" />)).toContain(
    'data-variant="call"',
  );
});
