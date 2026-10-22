/**
 * Home shows today's calls and analysis health to the accounts that review
 * calls, read on the server together; a failed read never hides the rest.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

import type { ApiResult } from "@/app/lib/server-api";

const reads = vi.hoisted(() => ({ health: true, meter: true }));

vi.mock("@/app/lib/server-api", async (original) => {
  const actual = await original<typeof import("@/app/lib/server-api")>();
  return {
    ...actual,
    adminRead: async <T,>(
      path: string,
      normalize: (raw: unknown) => T,
    ): Promise<ApiResult<T>> => {
      if (path.startsWith("/v1/admin/conversation/meter")) {
        if (!reads.meter)
          return { ok: false, status: 403, error: "Not for this account." };
        const { meterFixture } = await import(
          "@/app/review-fixture/meter/meter-fixture"
        );
        return {
          ok: true,
          status: 200,
          data: normalize(meterFixture(new Date())),
        };
      }
      if (path.startsWith("/v1/admin/conversation/calls"))
        return {
          ok: true,
          status: 200,
          data: normalize({
            counts: { ready: 7, analysing: 2, failed: 1, uploaded: 0 },
            review_counts: { new: 4, needs_review: 2, disputed: 1, done: 3 },
            window: { truncated: false },
          }),
        };
      if (!reads.health)
        return { ok: false, status: 503, error: actual.MESSAGES.reconnecting };
      return {
        ok: true,
        status: 200,
        data: normalize({
          jobs: {
            by_status: { dead_letter: 0 },
            by_stage: { C5: { succeeded: 12 } },
          },
          stuck: { plans: [], unfinished_runs: [] },
        }),
      };
    },
  };
});
vi.mock("@/app/lib/console-access", () => ({
  loadConsoleAccess: async () => ({
    state: "verified",
    email: "dipak@authorityclosers.com",
    displayName: "Dipak Synthetic",
    role: "admin",
    permissions: ["admin_surface"],
    platform: [],
  }),
}));
vi.mock("@/app/components/admin-dashboard", () => ({
  CourseActivity: () => null,
}));

beforeEach(() => {
  reads.health = true;
  reads.meter = true;
});

const markup = async () => {
  const { default: HomePage } = await import("./page");
  return renderToStaticMarkup(await HomePage());
};

it("shows today's calls and health as tiles that open the right view", async () => {
  const html = await markup();
  expect(html).toContain("Needs review");
  expect(html).toContain('href="/calls?review=new"');
  expect(html).toContain('href="/calls?review=disputed"');
  expect(html).toContain('href="/calls?status=failed"');
  expect(html).toContain("Reports, last 24 h");
  expect(html).toContain(">12<");
  expect(html).toContain("Stuck now");
});

it("keeps the call tiles when the health read fails", async () => {
  reads.health = false;
  const html = await markup();
  expect(html).toContain("Needs review");
  expect(html).not.toContain("Reports, last 24 h");
});

it("shows production's cost per minute now, and is whole without it", async () => {
  const html = await markup();
  expect(html).toContain("₹/min now · production");
  expect(html).toContain("Last 7 days: ₹1.07/min");
  expect(html).toContain('href="/health#cost-meter"');
  reads.meter = false;
  const without = await markup();
  expect(without).not.toContain("₹/min now");
  expect(without).toContain("Needs review");
});
