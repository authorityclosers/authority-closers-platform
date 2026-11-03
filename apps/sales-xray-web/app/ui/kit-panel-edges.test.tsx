import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { Panel } from "./kit";

// Production reports 148 and 116 (3 Nov 2026): a kit card says it is one, so a
// part built for padded places (a switch row, the Calls setup check) keeps its
// icon and toggle off the card's edges.
it("marks a kit card so the parts inside can keep off its edges", () => {
  const html = renderToStaticMarkup(
    <Panel title="Sounds &amp; vibration">
      <p>Vibration</p>
    </Panel>,
  );
  expect(html).toMatch(/^<section[^>]* data-panel=""/);
});
