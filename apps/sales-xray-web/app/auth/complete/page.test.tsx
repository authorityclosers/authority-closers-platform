import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("./auth-complete-client", () => ({
  AuthCompleteClient: ({ flow }: { flow: string | null }) => (
    <div data-flow={flow ?? ""} />
  ),
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
  expect(renderToStaticMarkup(route)).toBe('<div data-flow=""></div>');
});

it("forwards the exact string flow in the production callback path", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  const route = await AuthCompletePage({
    searchParams: Promise.resolve({ flow }),
  });
  expect(renderToStaticMarkup(route)).toBe(`<div data-flow="${flow}"></div>`);
});
