// @vitest-environment happy-dom
/**
 * Reports V4 (Dipak's spec, 13 Nov 2026): every check in its section 25, on
 * the real page, sheet and calendar with fictional reports from the list API.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  prefetch: vi.fn(),
}));
const api = vi.hoisted(() => ({ acquisition: vi.fn() }));
const access = vi.hoisted(() => ({ kind: "organisation" as string }));
const handOff = vi.hoisted(() => ({ files: [] as File[] }));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => window.location.pathname,
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: React.ReactNode }) => (
    <div data-shell="">{children}</div>
  ),
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => ({
    authenticated: true,
    status: "ready",
    context: {
      personId: "00000000-0000-4000-8000-0000000000a1",
      sessionId: "00000000-0000-4000-8000-0000000000a2",
      tenantId: "00000000-0000-4000-8000-0000000000a3",
    },
    workspaces: [
      { tenant_id: "00000000-0000-4000-8000-0000000000a3", kind: access.kind },
    ],
  }),
}));
vi.mock("../capture-setup/recording-check", () => ({
  RecordingLine: () => null,
}));
vi.mock("../calls/phone-calls", () => ({
  callsFilter: (params: URLSearchParams) =>
    params.get("day") ? { day: params.get("day") } : null,
  PhoneCalls: ({ filter }: { filter: unknown }) => (
    <section data-phone-calls={filter ? "filtered" : "all"} />
  ),
}));
vi.mock("../display-clock", () => ({
  useDisplayDates: () => ({
    locale: "en-IN",
    timeZone: "Asia/Kolkata",
    today: "2026-11-13",
  }),
}));
vi.mock("../notice-center", () => ({ notify: vi.fn() }));
vi.mock("../acquisition-client", async (original) => ({
  ...(await original<typeof import("../acquisition-client")>()),
  acquisition: api.acquisition,
}));
vi.mock("./upload-handoff", async (original) => ({
  ...(await original<typeof import("./upload-handoff")>()),
  handOverRecording: (file: File) => handOff.files.push(file),
}));

import { ReportLibrary } from "./report-library";
import { forgetReports } from "./report-rows";
import { WAVEFORM_BARS } from "./waveform";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

type Fixture = {
  n: number;
  at: string;
  name?: string;
  title?: string;
  upload: "auto" | "manual";
  side: "inbound" | "cold" | null;
  saved?: boolean;
  summary?: string;
};

/** Fictional reports; times in UTC (India is 5:30 ahead). */
const FIXTURES: Fixture[] = [
  {
    n: 1,
    at: "2026-11-13T13:10:00Z",
    name: "rohit example",
    title: "Discovery call",
    upload: "auto",
    side: "inbound",
    summary: "Good connection. The business impact needed more exploration.",
  },
  {
    n: 2,
    at: "2026-11-13T08:45:00Z",
    name: "priya fictional",
    upload: "auto",
    side: "inbound",
    saved: true,
  },
  {
    n: 3,
    at: "2026-11-12T12:40:00Z",
    title: "Pricing discussion",
    upload: "manual",
    side: null,
  },
  {
    n: 4,
    at: "2026-11-11T11:15:00Z",
    name: "aarav sample",
    upload: "auto",
    side: "cold",
  },
  {
    n: 5,
    at: "2026-11-05T07:05:00Z",
    name: "neha sample",
    upload: "manual",
    side: "inbound",
  },
  {
    n: 6,
    at: "2026-11-01T04:30:00Z",
    name: "ravi sample",
    upload: "auto",
    side: "cold",
    saved: true,
  },
];

function submission(fixture: Fixture) {
  return {
    submission_id: id(fixture.n),
    created_at: fixture.at,
    duration_seconds: 21 * 60,
    state: "report_ready",
    has_report: true,
    display_name: fixture.title ?? null,
    display_name_revision: fixture.title ? 1 : 0,
    summary: {
      outcome: "follow_up",
      assessment: fixture.summary ?? null,
      fix_first: null,
      next_focus: null,
      strengths: 1,
      missed: 0,
    },
    ...(fixture.name
      ? {
          lead: {
            lead_id: id(100 + fixture.n),
            name: fixture.name,
            stage: "follow_up",
            step: null,
            pipeline: "main",
          },
        }
      : {}),
    upload: fixture.upload,
    lead_side: fixture.side,
    saved: fixture.saved ?? false,
  };
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  forgetReports();
  access.kind = "organisation";
  handOff.files = [];
  for (const spy of Object.values(router)) spy.mockReset();
  api.acquisition.mockReset();
  api.acquisition.mockImplementation(
    async (path: string, init?: RequestInit) => {
      if (init?.method === "PUT") return JSON.parse(String(init.body));
      expect(path).toContain("order=newest");
      expect(path).toContain("include_kind=true");
      expect(path).toContain("include_saved=true");
      // Two pages, oldest last, as the server pages them.
      if (!path.includes("before="))
        return {
          submissions: FIXTURES.slice(0, 4).map(submission),
          next_cursor: id(4),
        };
      return {
        submissions: FIXTURES.slice(4).map(submission),
        next_cursor: null,
      };
    },
  );
  window.history.replaceState(null, "", "/analysis/calls");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const flush = () =>
  act(async () => {
    for (let i = 0; i < 6; i += 1) await new Promise((r) => setTimeout(r, 0));
  });

async function open(address = "/analysis/calls") {
  window.history.replaceState(null, "", address);
  await act(async () => root.render(<ReportLibrary />));
  await flush();
}

const $ = <T extends Element = HTMLElement>(selector: string) =>
  host.querySelector<T>(selector);
const all = <T extends Element = HTMLElement>(selector: string) =>
  Array.from(host.querySelectorAll<T>(selector));
const byText = (selector: string, text: string) =>
  all<HTMLElement>(selector).find((node) => node.textContent?.trim() === text);
const cards = () =>
  all("[data-report-card]").map((card) =>
    card.getAttribute("data-report-card"),
  );
const click = (node: Element | null | undefined) =>
  act(async () => (node as HTMLElement).click());
const tab = (name: string) => byText('[role="tab"]', name);
const count = () => $("[data-report-count]")?.textContent;
const sheet = () => $('[data-filter-sheet="open"]');
const applyButton = () => $<HTMLButtonElement>("[data-apply]");

async function type(value: string) {
  const input = $<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function openFilters() {
  await click($('button[aria-label^="Filters"]'));
  await flush();
}

/** The Lead type picker's button: its name is hidden text inside it. */
const leadTypeButton = () =>
  all<HTMLButtonElement>("button").find((button) =>
    button.textContent?.startsWith("Lead type "),
  );

async function chooseLeadType(label: string) {
  await click(leadTypeButton());
  await click(
    all('[role="option"]').find((row) => row.textContent?.includes(label)),
  );
}

describe("Main page", () => {
  it("opens Reports on Main by default, with the tabs at the top", async () => {
    await open();
    expect(tab("Main")?.getAttribute("aria-selected")).toBe("true");
    expect(tab("All Reports")?.getAttribute("aria-selected")).toBe("false");
    expect(host.textContent).toContain(
      "Turn your sales conversations into clearer next steps.",
    );
    expect($("h1")?.textContent).toBe("Reports");
  });

  it("switches between Main and All Reports", async () => {
    await open();
    await click(tab("All Reports"));
    expect(tab("All Reports")?.getAttribute("aria-selected")).toBe("true");
    expect(host.textContent).toContain(
      "All your analysed calls, easy to revisit.",
    );
    await click(tab("Main"));
    expect(tab("Main")?.getAttribute("aria-selected")).toBe("true");
    expect($('[aria-label="Analyse a call"]')).not.toBeNull();
  });

  it("shows the waveform as a picture only, beside one Analyse a call button", async () => {
    await open();
    const section = $('[aria-label="Analyse a call"]')!;
    const wave = section.querySelector("[data-waveform]")!;
    expect(wave.getAttribute("aria-hidden")).toBe("true");
    expect(wave.querySelectorAll("rect")).toHaveLength(WAVEFORM_BARS);
    // Not a player: nothing to press, nothing else in the section.
    expect(wave.querySelectorAll("button, audio, input")).toHaveLength(0);
    expect(
      Array.from(section.querySelectorAll("button"), (b) => b.textContent),
    ).toEqual(["Analyse a call"]);
    await click(byText("button", "Analyse a call"));
    expect(router.push).toHaveBeenCalledWith("/analysis/calls?view=analyse");
  });

  it("shows the three newest reports, newest first, and View all opens All Reports", async () => {
    await open();
    expect(cards()).toEqual([id(1), id(2), id(3)]);
    await click(byText("button", "View all"));
    expect(tab("All Reports")?.getAttribute("aria-selected")).toBe("true");
    expect(cards()).toEqual(FIXTURES.map((fixture) => id(fixture.n)));
  });

  it("keeps the phone's own calls a tap away in a workspace", async () => {
    await open();
    expect(
      $<HTMLAnchorElement>("[data-your-calls]")?.getAttribute("href"),
    ).toBe("/analysis/calls?view=calls");
    await act(async () => root.unmount());
    root = createRoot(host);
    await open("/analysis/calls?view=calls");
    expect($("[data-phone-calls]")?.getAttribute("data-phone-calls")).toBe(
      "all",
    );
    // A number from Home or Team still opens that day's calls.
    await act(async () => root.unmount());
    root = createRoot(host);
    await open("/analysis/calls?day=today&outcome=connected");
    expect($("[data-phone-calls]")?.getAttribute("data-phone-calls")).toBe(
      "filtered",
    );
  });

  it("has no phone calls link in a personal workspace", async () => {
    access.kind = "personal";
    await open();
    expect($("[data-your-calls]")).toBeNull();
  });
});

describe("All Reports", () => {
  it("shows every report without filters, newest first, with the count", async () => {
    await open("/analysis/calls?tab=all");
    expect(cards()).toEqual(FIXTURES.map((fixture) => id(fixture.n)));
    expect(count()).toBe("6 of 6 reports");
    expect(host.textContent).toContain("Newest first");
  });

  it("searches while typing, any case, and the count follows", async () => {
    await open("/analysis/calls?tab=all");
    await type("ROHIT");
    expect(cards()).toEqual([id(1)]);
    expect(count()).toBe("1 of 6 reports");
    await type("pricing");
    expect(cards()).toEqual([id(3)]);
    await type("");
    expect(cards()).toHaveLength(6);
  });

  it("opens the same upload screen from New analysis", async () => {
    await open("/analysis/calls?tab=all");
    await click(byText("button", "New analysis"));
    expect(router.push).toHaveBeenCalledWith("/analysis/calls?view=analyse");
  });

  it("opens each card's own report", async () => {
    await open("/analysis/calls?tab=all");
    for (const fixture of FIXTURES) {
      const card = $(`[data-report-card="${id(fixture.n)}"]`)!;
      expect(card.querySelector("a")?.getAttribute("href")).toBe(
        `/analysis/calls/${id(fixture.n)}`,
      );
    }
    const first = $(`[data-report-card="${id(1)}"]`)!;
    expect(first.textContent).toContain("Inbound · Auto");
    expect(first.textContent).toContain("13 Nov · 6:40 PM");
    expect(first.querySelector("h3")?.textContent).toBe(
      "Rohit Example · Discovery call",
    );
    expect(first.textContent).toContain(
      "Good connection. The business impact needed more exploration.",
    );
    expect(first.textContent).toContain("21 min · Report ready");
    expect(first.textContent).toContain("View report");
    const manual = $(`[data-report-card="${id(3)}"]`)!;
    expect(manual.textContent).toContain("Manual upload");
    expect(manual.querySelector("h3")?.textContent).toBe(
      "Unassigned prospect · Pricing discussion",
    );
  });

  it("saves a report for this person, and the card says so", async () => {
    await open("/analysis/calls?tab=all");
    const save = $(`[data-report-card="${id(4)}"] button[aria-pressed]`)!;
    expect(save.getAttribute("aria-pressed")).toBe("false");
    await click(save);
    await flush();
    expect(api.acquisition).toHaveBeenCalledWith(
      `/submissions/${id(4)}/saved`,
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ saved: true }),
      }),
    );
    expect(
      $(`[data-report-card="${id(4)}"] button[aria-pressed]`)?.getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");
  });
});

describe("Filters: lead type", () => {
  it("opens the sheet with All lead types chosen", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    expect(sheet()).not.toBeNull();
    expect(host.textContent).toContain("Filter reports");
    expect(leadTypeButton()?.textContent).toContain("All lead types");
    expect(applyButton()?.textContent).toBe("Show all reports");
  });

  for (const [label, expected] of [
    ["Inbound leads (Auto-uploaded)", [1, 2]],
    ["Cold leads (Auto-uploaded)", [4, 6]],
    ["Manually Uploaded", [3, 5]],
    ["Saved Reports", [2, 6]],
  ] as const) {
    it(`shows only ${label}`, async () => {
      await open("/analysis/calls?tab=all");
      await openFilters();
      await chooseLeadType(label);
      expect(applyButton()?.textContent).toBe(
        `Show ${expected.length} reports`,
      );
      await click(applyButton());
      await flush();
      expect(sheet()).toBeNull();
      expect(cards()).toEqual(expected.map(id));
      expect(count()).toBe(`${expected.length} of 6 reports · Filtered`);
      expect(
        $('button[aria-label^="Filters"]')?.getAttribute("aria-label"),
      ).toBe("Filters, 1 active filter");
      expect($('[aria-label="Applied filters"]')?.textContent).toContain(label);
    });
  }
});

describe("Filters: date range", () => {
  it("opens on the current month and moves between months", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    expect($("[data-calendar-month]")?.textContent).toBe("November 2026");
    await click($('button[aria-label="Previous month"]'));
    expect($("[data-calendar-month]")?.textContent).toBe("October 2026");
    await click($('button[aria-label="Next month"]'));
    await click($('button[aria-label="Next month"]'));
    expect($("[data-calendar-month]")?.textContent).toBe("December 2026");
  });

  it("selects From and To, highlights the range, includes both days", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    await click($('[data-day="2026-11-05"]'));
    expect($('[data-slot="from"]')?.textContent).toContain("5 Nov 2026");
    await click($('[data-day="2026-11-12"]'));
    expect($('[data-slot="to"]')?.textContent).toContain("12 Nov 2026");
    expect($('[data-day="2026-11-05"]')?.hasAttribute("data-edge")).toBe(true);
    expect($('[data-day="2026-11-12"]')?.hasAttribute("data-edge")).toBe(true);
    expect(
      all("[data-between]").map((day) => day.getAttribute("data-day")),
    ).toEqual([
      "2026-11-06",
      "2026-11-07",
      "2026-11-08",
      "2026-11-09",
      "2026-11-10",
      "2026-11-11",
    ]);
    expect(applyButton()?.textContent).toBe("Show 3 reports");
    await click(applyButton());
    await flush();
    // 5 Nov 12:35 IST and 12 Nov 18:10 IST are the edges, both shown.
    expect(cards()).toEqual([id(3), id(4), id(5)]);
    expect($('[aria-label="Applied filters"]')?.textContent).toContain(
      "5 Nov – 12 Nov 2026",
    );
  });

  it("refuses a range with only one date", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    await click($('[data-day="2026-11-05"]'));
    expect(applyButton()?.textContent).toBe("Select an end date");
    expect(applyButton()?.getAttribute("aria-disabled")).toBe("true");
    await click(applyButton());
    expect(sheet()).not.toBeNull();
    expect($("[data-date-hint]")?.textContent).toBe("Select an end date");
    expect(cards()).toHaveLength(6);
  });

  it("clears the dates but keeps the lead type", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    await chooseLeadType("Cold leads (Auto-uploaded)");
    await click($('[data-day="2026-11-01"]'));
    await click($('[data-day="2026-11-13"]'));
    await click(byText("button", "Clear dates"));
    expect($('[data-slot="from"]')?.textContent).toContain("Select start date");
    expect($('[data-slot="to"]')?.textContent).toContain("Select end date");
    expect(all("[data-edge]")).toHaveLength(0);
    expect(leadTypeButton()?.textContent).toContain("Cold leads");
  });

  it("works together with a lead type", async () => {
    await open("/analysis/calls?tab=all");
    await openFilters();
    await chooseLeadType("Cold leads (Auto-uploaded)");
    await click($('[data-day="2026-11-10"]'));
    await click($('[data-day="2026-11-13"]'));
    await click(applyButton());
    await flush();
    expect(cards()).toEqual([id(4)]);
    expect($('button[aria-label^="Filters"]')?.getAttribute("aria-label")).toBe(
      "Filters, 2 active filters",
    );
    // The applied range shows again when the sheet reopens.
    await openFilters();
    expect($('[data-day="2026-11-10"]')?.hasAttribute("data-edge")).toBe(true);
    expect($('[data-day="2026-11-13"]')?.hasAttribute("data-edge")).toBe(true);
  });
});

describe("Filters: chips, reset, empty state", () => {
  async function filtered() {
    await open(
      "/analysis/calls?tab=all&type=cold_auto&from=2026-11-01&to=2026-11-13",
    );
  }

  it("reads filters from the address, so Back from a report keeps them", async () => {
    await filtered();
    expect(cards()).toEqual([id(4), id(6)]);
    expect(count()).toBe("2 of 6 reports · Filtered");
    // A card remembers its list for the way back.
    host.addEventListener("click", (event) => event.preventDefault(), {
      once: true,
    });
    await click($(`[data-report-card="${id(4)}"] a`));
    expect(sessionStorage.getItem("sx.reports.return")).toBe(
      "/analysis/calls?tab=all&type=cold_auto&from=2026-11-01&to=2026-11-13",
    );
  });

  it("writes the tab, search and filters into the address", async () => {
    await open();
    await click(tab("All Reports"));
    await type("sample");
    await flush();
    expect(window.location.search).toBe("?tab=all&q=sample");
  });

  it("removes one filter with its chip and keeps the other", async () => {
    await filtered();
    await click($('button[aria-label="Remove lead type filter"]'));
    expect(cards()).toEqual(FIXTURES.map((fixture) => id(fixture.n)));
    expect($('[aria-label="Applied filters"]')?.textContent).toContain(
      "1 Nov – 13 Nov 2026",
    );
    await click($('button[aria-label="Remove date filter"]'));
    expect($('[aria-label="Applied filters"]')).toBeNull();
    expect(count()).toBe("6 of 6 reports");
  });

  it("resets everything in the sheet, and closing without applying changes nothing", async () => {
    await filtered();
    await openFilters();
    await click(byText("button", "Reset all"));
    expect(leadTypeButton()?.textContent).toContain("All lead types");
    expect(all("[data-edge]")).toHaveLength(0);
    expect(applyButton()?.textContent).toBe("Show all reports");
    // Closed with ×: the applied filters stay.
    await click($('button[aria-label="Close"]'));
    await flush();
    expect(cards()).toEqual([id(4), id(6)]);
    // Reset and applied: everything again.
    await openFilters();
    await click(byText("button", "Reset all"));
    await click(applyButton());
    await flush();
    expect(cards()).toHaveLength(6);
    expect(count()).toBe("6 of 6 reports");
  });

  it("says nothing matched, and one tap clears filters and search", async () => {
    await filtered();
    await type("nobody by this name");
    expect(cards()).toHaveLength(0);
    const empty = $("[data-no-match]")!;
    expect(empty.querySelector("h3")?.textContent).toBe("No matching reports");
    expect(empty.textContent).toContain("Your reports have not been removed.");
    await click(byText("button", "Clear filters & search"));
    expect(cards()).toEqual(FIXTURES.map((fixture) => id(fixture.n)));
    expect($<HTMLInputElement>('input[type="search"]')?.value).toBe("");
    expect(count()).toBe("6 of 6 reports");
  });
});

describe("Analyse a call", () => {
  it("chooses a recording and hands it to New analysis", async () => {
    await open("/analysis/calls?view=analyse");
    expect($("h1")?.textContent).toBe("Make your next call better.");
    expect(host.textContent).toContain(
      "Upload a call, get clear feedback you can use.",
    );
    expect($("[data-chosen-file]")?.textContent).toBe("No file selected");
    expect(host.textContent).toContain("MP3 · WAV · M4A · OGG · FLAC");
    const input = $<HTMLInputElement>("[data-recording-input]")!;
    expect(input.accept).toContain(".flac");
    const file = new File([new Uint8Array([1, 2, 3])], "call-with-sample.m4a", {
      type: "audio/mp4",
    });
    Object.defineProperty(input, "files", { value: [file] });
    await act(async () =>
      input.dispatchEvent(new Event("change", { bubbles: true })),
    );
    expect($("[data-chosen-file]")?.textContent).toBe(
      "Selected: call-with-sample.m4a",
    );
    expect(handOff.files).toEqual([file]);
    expect(router.replace).toHaveBeenCalledWith("/analysis/new");
  });

  it("goes back to Reports", async () => {
    await open("/analysis/calls?view=analyse");
    await click(byText("button", "Back to Reports"));
    expect(
      router.back.mock.calls.length + router.replace.mock.calls.length,
    ).toBe(1);
  });
});
