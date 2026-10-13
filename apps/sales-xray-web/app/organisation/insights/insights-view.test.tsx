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

async function choose(view: string) {
  const button = Array.from(
    host.querySelectorAll<HTMLButtonElement>('[aria-label="View"] button'),
  ).find((item) => item.textContent === view);
  expect(button).toBeDefined();
  await act(async () => {
    button!.click();
  });
}

function returnedPeople(size: number) {
  const people = Array.from({ length: size }, (_, index) => ({
    ...fixture.overview.people[index % fixture.overview.people.length],
    key: `fictional-person-${index + 1}`,
    name: `Fictional person ${index + 1}`,
  }));
  return {
    ...fixture.overview,
    // A summary total is not a promise that additional rows were returned.
    totals: { ...fixture.overview.totals, people: 999 },
    people,
    facets: { ...fixture.overview.facets, people },
  };
}

it.each([51, 125])(
  "reaches all %i returned people in source order and folds with focus",
  async (size) => {
    const overview = returnedPeople(size);
    await render(
      <InsightsView
        view="people"
        filters={DEFAULT_FILTERS}
        initial={{ status: 200, body: overview }}
        initialCalls={{ status: 200, body: fixture.calls }}
      />,
    );
    const table = host.querySelector('table[aria-label="People"]')!;
    const cards = host.querySelector('[role="list"][aria-label="People"]')!;
    const toggle = Array.from(host.querySelectorAll("button")).find(
      (button) => button.textContent === "Show more",
    )!;
    expect(table.querySelectorAll("tbody tr")).toHaveLength(50);
    expect(cards.querySelectorAll('[role="listitem"]')).toHaveLength(50);
    expect(host.textContent).toContain(`Showing 50 of ${size} people`);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(
      document
        .getElementById(toggle.getAttribute("aria-controls")!)!
        .contains(table),
    ).toBe(true);

    await act(async () => toggle.click());
    expect(toggle.textContent).toBe("Show fewer");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(host.textContent).toContain(`Showing ${size} of ${size} people`);
    const names = overview.people.map((person) => person.name);
    expect(
      Array.from(
        table.querySelectorAll("tbody td:first-child button"),
        (button) => button.textContent,
      ),
    ).toEqual(names);
    expect(
      Array.from(
        cards.querySelectorAll("article button"),
        (button) => button.textContent,
      ),
    ).toEqual(names);
    expect(host.querySelector('a[href^="/organisation/people/"]')).toBeNull();

    const last = Array.from(
      table.querySelectorAll<HTMLButtonElement>("button"),
    ).find((button) => button.textContent === names.at(-1))!;
    last.focus();
    expect(document.activeElement).toBe(last);
    await act(async () => toggle.click());
    expect(document.activeElement).toBe(toggle);
    expect(toggle.textContent).toBe("Show more");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(50);
    expect(cards.querySelectorAll('[role="listitem"]')).toHaveLength(50);
    expect(table.textContent).not.toContain(names.at(-1));
    expect(fetchMock).not.toHaveBeenCalled();
  },
);

it("keeps the last returned person's profile and call-filter identity", async () => {
  const overview = {
    ...returnedPeople(65),
    source: "call",
    synthetic: false,
  };
  const last = overview.people.at(-1)!;
  // Exercise profile URL encoding independently of the displayed name.
  last.key = "fictional/person?65";
  fetchMock.mockImplementation(async (path: string) =>
    json(path.includes("/calls") ? fixture.calls : overview),
  );
  await render(
    <InsightsView
      view="people"
      filters={DEFAULT_FILTERS}
      initial={{ status: 200, body: overview }}
      initialCalls={{ status: 200, body: fixture.calls }}
    />,
  );
  const toggle = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Show more",
  )!;
  await act(async () => toggle.click());
  const profilePath = `/organisation/people/${encodeURIComponent(last.key)}`;
  const table = host.querySelector('table[aria-label="People"]')!;
  const cards = host.querySelector('[role="list"][aria-label="People"]')!;
  for (const surface of [table, cards]) {
    const profile = surface.querySelector(`a[href="${profilePath}"]`)!;
    expect(profile.getAttribute("aria-label")).toBe(
      `Open ${last.name}’s profile`,
    );
  }
  expect(fetchMock).not.toHaveBeenCalled();
  const person = Array.from(
    cards.querySelectorAll<HTMLButtonElement>("button"),
  ).find((button) => button.textContent === last.name)!;
  await act(async () => person.click());
  expect(new URL(window.location.href).searchParams.get("person")).toBe(
    last.key,
  );
  expect(new URL(window.location.href).searchParams.get("view")).toBe("people");
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/conversation/acquisition/insights?person=fictional%2Fperson%3F65",
    expect.objectContaining({ credentials: "same-origin" }),
  );
});

it.each([0, 1, 50])(
  "shows the returned count without expansion when there are %i people",
  async (size) => {
    await render(
      <InsightsView
        view="people"
        filters={DEFAULT_FILTERS}
        initial={{ status: 200, body: returnedPeople(size) }}
        initialCalls={{ status: 200, body: fixture.calls }}
      />,
    );
    expect(host.textContent).toContain(`Showing ${size} of ${size} people`);
    expect(
      Array.from(host.querySelectorAll("button")).some(
        (button) =>
          button.textContent === "Show more" ||
          button.textContent === "Show fewer",
      ),
    ).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  },
);

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
  expect(text).toContain("Calls over time");
  expect(text).toContain("Common mistakes");
  expect(text).toContain("not an official score");
  // People and Calls are their own views, chosen at the top.
  expect(text).not.toContain("Skills by person");
  await choose("People");
  expect(host.textContent).toContain("Skills by person");
  expect(host.querySelector('a[href^="/organisation/people/"]')).toBeNull();
  expect(`${window.location.pathname}${window.location.search}`).toBe(
    "/organisation/insights?view=people",
  );
  await choose("Calls");
  expect(host.textContent).toContain("All calls");
  // Synthetic calls have no report page: nothing links to one.
  expect(host.querySelector('a[href^="/analysis/calls/"]')).toBeNull();
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
  expect(host.querySelector('select[aria-label="Team"]')).toBeNull();
  // Real members open their profile from the people table.
  await choose("People");
  expect(host.querySelector('a[href^="/organisation/people/"]')).not.toBeNull();
  // Real calls open their report.
  await choose("Calls");
  expect(host.querySelector('a[href^="/analysis/calls/"]')).not.toBeNull();
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
