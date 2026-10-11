// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/organisation/insights",
}));

import fixture from "../../review-fixture/insights/sandbox.json";
import { DEFAULT_FILTERS } from "./insights-data";
import { InsightsView } from "./insights-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  replace.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function render(node: React.ReactNode) {
  await act(async () => {
    root.render(node);
  });
}

it("renders a seeded sandbox page whole, labelled synthetic, without reading", async () => {
  await render(
    <InsightsView
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: fixture.overview }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  const text = host.textContent ?? "";
  expect(text).toContain("Synthetic sandbox data");
  expect(text).toContain("Calls analysed");
  expect(text).toContain("Agreed a next step");
  expect(text).toContain("Skills by person");
  expect(text).toContain("Common mistakes");
  expect(text).toContain("not an official score");
  // Synthetic calls have no report page: nothing links to one.
  expect(host.querySelector('a[href^="/analysis/calls/"]')).toBeNull();
  expect(host.querySelector('a[href^="/organisation/people/"]')).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(host.querySelector('select[aria-label="Team"]')).not.toBeNull();
});

it("puts a chosen filter in the address and reads it", async () => {
  fetchMock.mockImplementation(async (path: string) =>
    json(path.includes("/calls") ? fixture.calls : fixture.overview),
  );
  await render(
    <InsightsView
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: fixture.overview }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  const outcome = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Outcome"]',
  );
  expect(outcome).not.toBeNull();
  await act(async () => {
    outcome!.value = "won";
    outcome!.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(`${window.location.pathname}${window.location.search}`).toBe(
    "/organisation/insights?outcome=won",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/conversation/acquisition/insights?outcome=won",
    expect.objectContaining({ credentials: "same-origin" }),
  );
  expect(replace).not.toHaveBeenCalled();
});

it("reads in the browser when the server could not, and links real calls", async () => {
  const real = {
    ...fixture.overview,
    source: "call",
    synthetic: false,
    teams: [],
    mistakes: [],
    facets: { ...fixture.overview.facets, teams: [] },
  };
  fetchMock.mockImplementation(async (path: string) =>
    path.includes("/calls")
      ? json({ ...fixture.calls, synthetic: false })
      : json(real),
  );
  await render(<InsightsView filters={{ ...DEFAULT_FILTERS, range: "30d" }} />);
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/conversation/acquisition/insights?range=30d",
    expect.objectContaining({ credentials: "same-origin" }),
  );
  expect(host.textContent).not.toContain("Synthetic sandbox data");
  expect(host.textContent).toContain("Skills most often needing work");
  expect(host.querySelector('a[href^="/analysis/calls/"]')).not.toBeNull();
  expect(host.querySelector('select[aria-label="Team"]')).toBeNull();
  // Real members open their profile from the people table.
  expect(host.querySelector('a[href^="/organisation/people/"]')).not.toBeNull();
});

it("tells a member the view is for owners and admins", async () => {
  fetchMock.mockResolvedValue(json({ detail: "no" }, 403));
  await render(<InsightsView filters={DEFAULT_FILTERS} />);
  expect(host.textContent).toContain(
    "Only owners and admins of this organisation can see Insights",
  );
});

it("prepares new calls, then reads the figures again", async () => {
  const before = { ...fixture.overview, pending: 120 };
  let refreshes = 0;
  fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/refresh")) {
      expect(init?.method).toBe("POST");
      refreshes += 1;
      return json({ projected: 120, pending: 0 });
    }
    if (path.includes("/calls")) return json(fixture.calls);
    return json({ ...fixture.overview, pending: 0 });
  });
  await render(
    <InsightsView
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: before }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(refreshes).toBe(1);
  expect(
    fetchMock.mock.calls.some(
      ([path]) => path === "/v1/conversation/acquisition/insights",
    ),
  ).toBe(true);
  expect(host.textContent).not.toContain("Preparing");
});

it("never reads or refreshes in a review fixture", async () => {
  await render(
    <InsightsView
      fixture
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: { ...fixture.overview, pending: 9 } }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
});

it("finishes preparing under React's development double effects", async () => {
  const { StrictMode } = await import("react");
  let refreshes = 0;
  fetchMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/refresh")) {
      refreshes += 1;
      return json({ projected: 5, pending: 0 });
    }
    if (path.includes("/calls")) return json(fixture.calls);
    return json({ ...fixture.overview, pending: 0 });
  });
  await render(
    <StrictMode>
      <InsightsView
        filters={DEFAULT_FILTERS}
        initial={{ status: 200, body: { ...fixture.overview, pending: 5 } }}
        initialCalls={{ status: 200, body: fixture.calls }}
      />
    </StrictMode>,
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  expect(refreshes).toBeGreaterThanOrEqual(1);
  expect(host.textContent).not.toContain("Preparing");
});

it("never lets an older answer replace newer figures", async () => {
  let releaseOld: (() => void) | null = null;
  fetchMock.mockImplementation(async (path: string) => {
    if (path.includes("outcome=lost") && !path.includes("/calls"))
      await new Promise<void>((resolve) => {
        releaseOld = resolve;
      });
    const body = path.includes("/calls")
      ? fixture.calls
      : {
          ...fixture.overview,
          totals: {
            ...fixture.overview.totals,
            calls: path.includes("outcome=lost") ? 111 : 222,
          },
        };
    return json(body);
  });
  await render(
    <InsightsView
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: fixture.overview }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  const outcome = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Outcome"]',
  )!;
  await act(async () => {
    outcome.value = "lost";
    outcome.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => {
    outcome.value = "won";
    outcome.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(host.textContent).toContain("222 calls");
  await act(async () => {
    releaseOld?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(host.textContent).toContain("222 calls");
  expect(host.textContent).not.toContain("111 calls");
});
