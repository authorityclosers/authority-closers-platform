/**
 * The Admin company view (AUT-1798) reads one organisation's aggregates on
 * the server and shows them whole; a failed read is a small card, the
 * sandbox is labelled synthetic and every call is listed, 50 at a time.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

import type { ApiResult } from "@/app/lib/server-api";

import sandbox from "../../../../sales-xray-web/app/review-fixture/insights/sandbox.json";

const state = vi.hoisted(() => ({
  ok: true,
  paths: [] as string[],
  analysis: null as unknown,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/company",
}));

vi.mock("@/app/lib/server-api", async (original) => {
  const actual = await original<typeof import("@/app/lib/server-api")>();
  return {
    ...actual,
    adminRead: async <T,>(
      path: string,
      normalize: (raw: unknown) => T,
    ): Promise<ApiResult<T>> => {
      state.paths.push(path);
      if (!state.ok)
        return {
          ok: false,
          status: 503,
          error: "The data service is reconnecting.",
        };
      if (path.startsWith("/v1/admin/conversation/insights/calls"))
        return { ok: true, status: 200, data: normalize(sandbox.calls) };
      if (path.startsWith("/v1/admin/conversation/insights/analysis"))
        return { ok: true, status: 200, data: normalize(state.analysis ?? {}) };
      return {
        ok: true,
        status: 200,
        data: normalize({
          organisations: [
            {
              id: "00000000-0000-0000-0000-00000000b001",
              name: "AC Sandbox",
              sandbox: true,
            },
          ],
          organisation: {
            id: "00000000-0000-0000-0000-00000000b001",
            name: "AC Sandbox",
            sandbox: true,
          },
          overview: sandbox.overview,
        }),
      };
    },
  };
});

import CompanyPage from "./page";

beforeEach(() => {
  state.ok = true;
  state.paths = [];
  state.analysis = null;
});

it("shows the organisation's calls combined, labelled synthetic", async () => {
  const html = renderToStaticMarkup(
    await CompanyPage({
      searchParams: Promise.resolve({ range: "12m", outcome: "won" }),
    }),
  );
  expect(state.paths[0]).toBe(
    "/v1/admin/conversation/insights?range=12m&outcome=won",
  );
  expect(state.paths[1]).toBe(
    "/v1/admin/conversation/insights/calls?range=12m&outcome=won&organisation=00000000-0000-0000-0000-00000000b001",
  );
  for (const text of [
    "Company view",
    "AC Sandbox",
    "Synthetic sandbox data",
    "Calls over time",
    "How calls ended",
    "Skills across the calls",
    "Common mistakes",
    "never an official score",
  ])
    expect(html).toContain(text);
  // People and Calls are their own views, as tabs that keep the filters.
  expect(html).not.toContain("Strongest calls");
  expect(html).toContain("view=people");
  const calls = renderToStaticMarkup(
    await CompanyPage({
      searchParams: Promise.resolve({
        range: "12m",
        outcome: "won",
        view: "calls",
      }),
    }),
  );
  for (const text of ["Strongest calls", "Calls to review", "Older 50"])
    expect(calls).toContain(text);
  expect(calls).toContain(
    "range=12m&amp;outcome=won&amp;offset=50&amp;view=calls",
  );
  const people = renderToStaticMarkup(
    await CompanyPage({ searchParams: Promise.resolve({ view: "people" }) }),
  );
  expect(people).toContain("People (and teams)");
  expect(people).not.toContain("How calls ended");
});

it("keeps a failed read to a small card", async () => {
  state.ok = false;
  const html = renderToStaticMarkup(
    await CompanyPage({ searchParams: Promise.resolve({}) }),
  );
  expect(html).toContain("Company view is unavailable");
  expect(html).toContain("reconnecting");
});

it("ignores an organisation that isn't an id", async () => {
  renderToStaticMarkup(
    await CompanyPage({
      searchParams: Promise.resolve({ organisation: "../x" }),
    }),
  );
  expect(state.paths[0]).toBe("/v1/admin/conversation/insights");
});

it("shows skills as the AI pointer review scored them, never every skill at 100%", async () => {
  state.analysis = {
    window: { days: 90 },
    calls_analysed: 20,
    calls_scored: 16,
    skills: [
      { label: "Discovery", calls: 16, average: 41, needs_work_share: 0.75 },
      { label: "Rapport", calls: 4, average: 82, needs_work_share: 0 },
    ],
  };
  const html = renderToStaticMarkup(
    await CompanyPage({ searchParams: Promise.resolve({}) }),
  );
  expect(html).toContain("Skills needing work");
  expect(html).toContain("60%"); // (16 × 0.75 + 4 × 0) / 20 calls
  expect(html).toContain("AI pointer review · 16 calls scored · weakest first");
  expect(html).not.toContain("Observed share; calls needing attention");
  // Shown once, in the Skills panel; the analysis panels leave theirs out.
  expect(html.match(/Skill scores/g)).toHaveLength(1);
  expect(html).not.toContain(">Skill scores<");
});
