import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("./acquisition-studio", () => ({
  AcquisitionStudio: ({
    requestedCallId,
    deferRouteSelection,
  }: {
    requestedCallId?: string | null;
    deferRouteSelection?: boolean;
  }) => (
    <div
      data-requested-call-id={requestedCallId ?? ""}
      data-defer-route-selection={String(deferRouteSelection)}
    />
  ),
}));

import Page from "./page";

it("passes a valid saved-call selector to the acquisition studio", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  const callId = "11111111-1111-4111-8111-111111111111";
  const route = await Page({ searchParams: Promise.resolve({ call: callId }) });
  const markup = renderToStaticMarkup(route);
  expect(markup).toContain(`data-requested-call-id="${callId}"`);
  expect(markup).toContain('data-defer-route-selection="false"');
  vi.unstubAllEnvs();
});

it("keeps static export independent of request searchParams", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
  const unreadableSearchParams = {
    then() {
      throw new Error("static export must not read request searchParams");
    },
  } as unknown as Promise<Record<string, string | string[] | undefined>>;
  const route = await Page({ searchParams: unreadableSearchParams });
  const markup = renderToStaticMarkup(route);
  expect(markup).toContain('data-requested-call-id=""');
  expect(markup).toContain('data-defer-route-selection="true"');
  vi.unstubAllEnvs();
});
