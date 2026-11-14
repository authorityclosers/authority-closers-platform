/**
 * Admin -> Testers' tiles (Codex review on the v1.59 release PR, 14 Nov 2026):
 * Play's own requirement (12 testers opted in for 14 days in a row, counted in
 * Play Console) is never read off app activity, and approved testers who are
 * not in the Google Group yet are not counted as in it.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import type { ApiResult } from "../lib/server-api";

const RAW = {
  items: [],
  counts: {
    applied: 0,
    approved: 2,
    in_group: 3,
    emailed: 1,
    installed: 0,
    active: 13,
    declined: 0,
  },
  feedback: 0,
  active: 13,
  play_needs: 12,
  active_days: 7,
};

vi.mock("../lib/server-api", async (original) => {
  const actual = await original<typeof import("../lib/server-api")>();
  return {
    ...actual,
    adminRead: async <T,>(
      _path: string,
      normalize: (raw: unknown) => T,
    ): Promise<ApiResult<T>> => ({
      ok: true,
      status: 200,
      data: normalize(RAW),
    }),
  };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  usePathname: () => "/testers",
  useSearchParams: () => new URLSearchParams(),
}));

async function markup(): Promise<string> {
  const { default: TestersPage } = await import("../(console)/testers/page");
  const element = await TestersPage({ searchParams: Promise.resolve({}) });
  return renderToStaticMarkup(element);
}

it("keeps Play's 14-day requirement apart from recent app activity", async () => {
  const html = await markup();
  expect(html).toContain("13 active in the last 7 days");
  expect(html).not.toContain("Play needs");
  expect(html).toContain(
    "Play counts 12 opted in for 14 days in a row, in Play Console",
  );
  // 13 recent app users never mark Play's requirement as met.
  expect(html).not.toContain('data-tone="good"');
});

it("counts only testers in the Google Group as in it", async () => {
  const html = await markup();
  expect(html).toMatch(/Approved, to add to the group[\s\S]*?>2</);
  expect(html).toMatch(/In the group, not installed[\s\S]*?>4</);
});
