import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { AcquisitionShell } from "./acquisition-shell";

it("keeps the navigation, help, hero, and footer in the desktop shell", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionShell authenticated heroStage="welcome">
      <p>Workspace content</p>
    </AcquisitionShell>,
  );

  expect(markup).toContain('aria-label="Sales Xray navigation"');
  expect(markup).toContain("/brand/ac-v0.1/sales-xray-wordmark.svg");
  expect(markup).toContain("Need help?");
  expect(markup).toContain("Welcome back");
  expect(markup).toContain("Better");
  expect(markup).toContain('aria-label="Legal and support"');
  expect(markup).toContain("Turn conversations into closers");
  expect(markup).toContain('id="main-content"');
});

it("uses the same hero frame during processing and a neutral guest greeting", () => {
  const processing = renderToStaticMarkup(
    <AcquisitionShell authenticated heroStage="processing">
      <p>Processing state</p>
    </AcquisitionShell>,
  );
  const guest = renderToStaticMarkup(
    <AcquisitionShell authenticated={false} heroStage="welcome">
      <p>Guest state</p>
    </AcquisitionShell>,
  );

  expect(processing).toContain('data-hero-stage="processing"');
  expect(processing).toContain("Analysing your call");
  expect(guest).toContain("Welcome to Sales Xray");
  expect(guest).not.toContain("Welcome back");
});

it("labels a local processing fixture as an example", () => {
  const preview = renderToStaticMarkup(
    <AcquisitionShell authenticated={false} heroStage="processing" previewHero>
      <p>Example status</p>
    </AcquisitionShell>,
  );
  expect(preview).toContain("Example processing state");
  expect(preview).not.toContain("We&#x27;re processing your call");
});
