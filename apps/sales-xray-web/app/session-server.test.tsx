// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  usePathname: () => "/dashboard",
}));
vi.mock("next/headers", () => ({
  headers: async () =>
    new Headers({ cookie: "fictional-cookie", host: "salesxray.example.test" }),
}));
vi.mock("./shell/lightbox-shell", () => ({
  LightboxShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
const person = "11111111-1111-4111-8111-111111111111";
const session = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const bootstrap = (selected: boolean) => ({
  identity: {
    person_id: person,
    session_id: session,
    selected_tenant_id: selected ? tenant : null,
    workspaces: [{ tenant_id: tenant, name: "Fictional workspace" }],
  },
  directory: {
    selected_tenant_id: selected ? tenant : null,
    workspaces: [
      {
        tenant_id: tenant,
        name: "Fictional workspace",
        kind: "organisation",
        role: "member",
        sales_xray_enabled: true,
      },
    ],
  },
  profile: null,
});
const ready = (data: unknown) => ({ status: 200, data });
const snapshot = () => ({
  summary: ready({ total: 3, processing: 1, completed: 2, needs_attention: 0 }),
  activity: ready({
    timezone: "Asia/Kolkata",
    analysed_last_30_days: 3,
    analysed_previous_30_days: 1,
    days: Array.from({ length: 30 }, (_, day) => ({
      date: `2026-09-${String(day + 1).padStart(2, "0")}`,
      analysed: day === 29 ? 3 : 0,
      analysed_seconds: day === 29 ? 180 : 0,
    })),
  }),
  allowance: ready({
    allowance_seconds: 6000,
    committed_seconds: 1800,
    available_seconds: 4200,
  }),
  recent: ready({
    submissions: [
      {
        submission_id: "44444444-4444-4444-8444-444444444444",
        created_at: "2026-09-30T00:00:00Z",
        duration_seconds: 180,
        state: "completed",
        has_report: true,
        display_name: "Fictional discovery call",
        display_name_revision: 1,
      },
    ],
    next_cursor: null,
  }),
});
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "http://internal.example.test:8000");
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  vi.stubEnv("AC_SALES_XRAY_REVIEW", "0");
  fetchMock = vi.fn(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url.endsWith("bootstrap") ? bootstrap(true) : snapshot(),
        ),
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("populates the server page before browser effects and forwards cookies only to the exact origin", async () => {
  const { default: Page } = await import("./(session)/dashboard/page");
  const html = renderToStaticMarkup(await Page());
  expect(html).toContain("Calls analysed");
  expect(html).toContain("of 3 saved calls");
  expect(html).toContain("70 min");
  expect(html).toContain("Fictional discovery call");
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    "http://internal.example.test:8000/v1/me/sales-xray-bootstrap",
    "http://internal.example.test:8000/v1/conversation/acquisition/dashboard",
  ]);
  for (const [, init] of fetchMock.mock.calls) {
    expect(init).toMatchObject({
      method: "GET",
      cache: "no-store",
      redirect: "error",
      headers: { cookie: "fictional-cookie", host: "salesxray.example.test" },
    });
  }
  expect(html).not.toContain("fictional-cookie");
});

it("renders other widgets when one snapshot part fails", async () => {
  const partial = { ...snapshot(), summary: { status: 503 } };
  fetchMock.mockImplementation(
    async (url: string) =>
      new Response(
        JSON.stringify(url.endsWith("bootstrap") ? bootstrap(true) : partial),
      ),
  );
  const { default: Page } = await import("./(session)/dashboard/page");
  const html = renderToStaticMarkup(await Page());
  expect(html).toContain("70 min");
  expect(html).toContain("Some dashboard numbers could not load");
});

it("keeps chooser and signed-out states read-only and skips dashboard data", async () => {
  const { readSessionSeed, readDashboardSnapshot } = await import(
    "./session-server"
  );
  fetchMock.mockResolvedValue(new Response(JSON.stringify(bootstrap(false))));
  const seed = await readSessionSeed();
  expect(seed?.view.kind).toBe("chooser");
  expect(await readDashboardSnapshot(seed)).toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
  fetchMock.mockClear().mockResolvedValue(new Response(null, { status: 401 }));
  const signedOut = await readSessionSeed();
  expect(signedOut?.view.kind).toBe("unauthenticated");
  expect(await readDashboardSnapshot(signedOut)).toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("never accepts caller-controlled upstream URLs or follows redirects", async () => {
  const { internalApiOrigin, readSessionSeed } = await import(
    "./session-server"
  );
  for (const url of [
    "https://user:password@example.test",
    "https://example.test/path",
    "https://example.test/?url=other",
    "file:///etc/passwd",
  ])
    expect(() => internalApiOrigin(url)).toThrow();
  fetchMock.mockRejectedValue(new Error("redirect refused"));
  expect(await readSessionSeed()).toBeNull();
});

it("preserves the workspace denial surface instead of exposing other widgets", async () => {
  fetchMock.mockImplementation(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url.endsWith("bootstrap")
            ? bootstrap(true)
            : { ...snapshot(), summary: { status: 403 } },
        ),
      ),
  );
  const { default: Page } = await import("./(session)/dashboard/page");
  const html = renderToStaticMarkup(await Page());
  expect(html).toContain("Sales Xray isn&#x27;t on for this workspace yet");
  expect(html).not.toContain("Fictional discovery call");
});
