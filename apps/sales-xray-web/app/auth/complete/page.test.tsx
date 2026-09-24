import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("./auth-complete-client", () => ({
  AuthCompleteClient: ({
    flow,
    result,
  }: {
    flow: string | null;
    result: string | null;
  }) => <div data-flow={flow ?? ""} data-result={result ?? ""} />,
}));

import AuthCompletePage from "./page";

afterEach(() => vi.unstubAllEnvs());

it("does not read request searchParams during static preview export", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
  const unreadableSearchParams = {
    then() {
      throw new Error("static export must not read request searchParams");
    },
  } as unknown as Promise<{ flow?: string | string[] }>;

  const route = await AuthCompletePage({
    searchParams: unreadableSearchParams,
  });
  expect(renderToStaticMarkup(route)).toBe(
    '<div data-flow="" data-result=""></div>',
  );
});

it("forwards the exact flow and allowlisted result in the production callback path", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  const route = await AuthCompletePage({
    searchParams: Promise.resolve({ flow, auth_result: "success" }),
  });
  expect(renderToStaticMarkup(route)).toBe(
    `<div data-flow="${flow}" data-result="success"></div>`,
  );
});

it("does not accept the old flow-only callback as successful sign-in", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  const route = await AuthCompletePage({
    searchParams: Promise.resolve({
      flow: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
    }),
  });
  expect(renderToStaticMarkup(route)).toBe(
    '<div data-flow="" data-result=""></div>',
  );
});
