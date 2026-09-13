import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";

vi.mock("../../../sales-xray-web/app/call-studio", () => ({
  CallStudio: ({ homeHref }: { homeHref: string }) => (
    <div data-home-href={homeHref}>Call Studio</div>
  ),
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
  expect(markup).toContain("Call Studio");
  expect(markup).not.toContain("http://");
  expect(markup).not.toContain("https://");
});
