import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";

vi.mock("../../../sales-xray-web/app/acquisition-studio", () => ({
  AcquisitionStudio: ({
    homeHref,
    variant,
    requestedCallId,
  }: {
    homeHref: string;
    variant: string;
    requestedCallId: string | null;
  }) => (
    <div
      data-home-href={homeHref}
      data-variant={variant}
      data-requested-call-id={requestedCallId ?? ""}
    >
      Acquisition Studio
    </div>
  ),
}));
vi.mock("../../../sales-xray-web/app/standalone-studio", () => ({
  StandaloneStudio: ({
    children,
    variant,
    openingExistingCall,
  }: {
    children: ReactNode;
    variant: string;
    openingExistingCall: boolean;
  }) => (
    <div
      data-access-variant={variant}
      data-opening-existing-call={String(openingExistingCall)}
    >
      {children}
    </div>
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

async function renderRoute(searchParams: Record<string, string | string[]>) {
  const route = await SalesXrayPage({
    searchParams: Promise.resolve(searchParams),
  });
  return renderToStaticMarkup(route);
}

it("keeps the LMS route inside the Academy shell with an internal return path", async () => {
  const markup = await renderRoute({});

  expect(markup).toContain('data-current="sales-xray"');
  expect(markup).toContain('id="main-content"');
  expect(markup).toContain('class="learner-main"');
  expect(markup).toContain('data-home-href="/home"');
  expect(markup).toContain('data-variant="embedded"');
  expect(markup).toContain('data-requested-call-id=""');
  expect(markup).toContain("Acquisition Studio");
  expect(markup).toContain('data-access-variant="embedded"');
  expect(markup).toContain('data-opening-existing-call="false"');
  expect(markup).toContain('href="/sales-xray/calls"');
  expect(markup).toContain('href="/sales-xray/recordings"');
  expect(markup).not.toContain("http://");
  expect(markup).not.toContain("https://");
});

it("passes only one valid saved-call selector into the learner route", async () => {
  const callId = "11111111-1111-4111-8111-111111111111";
  const markup = await renderRoute({ call: callId });
  expect(markup).toContain(`data-requested-call-id="${callId}"`);
  expect(markup).toContain('data-opening-existing-call="true"');

  const duplicate = await renderRoute({ call: [callId, callId] });
  expect(duplicate).toContain('data-requested-call-id=""');

  const malformed = await renderRoute({ call: "not-a-call-id" });
  expect(malformed).toContain('data-requested-call-id=""');
});
