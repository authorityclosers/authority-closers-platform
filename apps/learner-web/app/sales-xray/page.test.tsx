import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";

vi.mock("../../../sales-xray-web/app/acquisition-studio", () => ({
  AcquisitionStudio: ({
    homeHref,
    variant,
  }: {
    homeHref: string;
    variant: string;
  }) => (
    <div data-home-href={homeHref} data-variant={variant}>
      Acquisition Studio
    </div>
  ),
}));
vi.mock("../../../sales-xray-web/app/standalone-studio", () => ({
  StandaloneStudio: ({
    children,
    variant,
  }: {
    children: ReactNode;
    variant: string;
  }) => <div data-access-variant={variant}>{children}</div>,
}));
vi.mock("../components/site-shell", () => ({
  LearnerShell: ({
    children,
    current,
  }: {
    children: ReactNode;
    current: string;
  }) => <div data-current={current}>{children}</div>,
}));

import SalesXrayPage from "./page";

it("keeps the LMS route inside the Academy shell with an internal return path", () => {
  const markup = renderToStaticMarkup(<SalesXrayPage />);

  expect(markup).toContain('data-current="sales-xray"');
  expect(markup).toContain('id="main-content"');
  expect(markup).toContain('class="learner-main"');
  expect(markup).toContain('data-home-href="/home"');
  expect(markup).toContain('data-variant="embedded"');
  expect(markup).toContain("Acquisition Studio");
  expect(markup).toContain('data-access-variant="embedded"');
  expect(markup).toContain('href="/sales-xray/calls"');
  expect(markup).toContain('href="/sales-xray/recordings"');
  expect(markup).not.toContain("http://");
  expect(markup).not.toContain("https://");
});
