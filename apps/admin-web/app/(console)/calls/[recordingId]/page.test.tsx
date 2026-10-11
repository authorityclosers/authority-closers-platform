/**
 * A call with no report says why and shows what can be done about it: its
 * failed steps (Retry only where the step never reached a provider) and runs.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import type { ApiResult } from "@/app/lib/server-api";

const UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

vi.mock("@/app/lib/server-api", async (original) => {
  const actual = await original<typeof import("@/app/lib/server-api")>();
  return {
    ...actual,
    adminRead: async <T,>(
      path: string,
      normalize: (raw: unknown) => T,
    ): Promise<ApiResult<T>> => ({
      ok: true,
      status: 200,
      data: normalize(
        path.endsWith(`/calls/${UUID}`)
          ? {
              recording_id: UUID,
              organisation: { id: "o1", name: "Synthetic Team" },
              rep: { label: "Asha Synthetic" },
              status: "failed",
              runs: [
                {
                  id: "run-1",
                  state: "failed",
                  report_id: null,
                  model: "pro",
                  prompt_revision: "coaching-v5",
                },
              ],
              failed_jobs: [
                {
                  job_id: "job-1",
                  stage: "C2",
                  attempts: 3,
                  code: "provider_timeout",
                  failed_at: "2026-10-11T03:00:00Z",
                  retryable: true,
                },
              ],
            }
          : {},
      ),
    }),
  };
});
vi.mock("@/app/lib/console-access", () => ({
  loadConsoleAccess: async () => ({ platform: [] }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

it("shows a failed call's failed steps with Retry, and its runs", async () => {
  const { default: CallReviewPage } = await import("./page");
  const markup = renderToStaticMarkup(
    await CallReviewPage({
      params: Promise.resolve({ recordingId: UUID }),
      searchParams: Promise.resolve({}),
    }),
  );
  expect(markup).toContain("The analysis failed");
  expect(markup).toContain("Failed steps");
  expect(markup).toContain("Transcript");
  expect(markup).toContain("provider_timeout");
  expect(markup).toContain(">Retry<");
  expect(markup).toContain("coaching-v5");
  expect(markup).not.toContain("Analysis health");
});
