import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined }),
}));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as never}</a>
  ),
}));

import type { RepView, Team } from "./leads-client";
import { LeadRulesPane } from "./settings-panes";
import { TeamView } from "./team-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner #38 (27 Oct 2026): "Lead rules shows this stupid dashboard again, and
// why?" Settings → Lead rules shows the rules; Leads → Team keeps the numbers.
let root: Root;
let host: HTMLDivElement;

const rep: RepView = {
  person_id: "aaaaaaaa-0000-4000-8000-000000000001",
  name: "Priya Example",
  role: "member",
  revision: 1,
  available: true,
  max_open: 50,
  languages: ["Marathi"],
  areas: ["Pune"],
  interests: [],
  open_leads: 12,
  due_now: 3,
  calls_today: 9,
  connected_today: 4,
  first_call_minutes: 6,
};

const team: Team = {
  reps: [rep],
  settings: {
    revision: 2,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "91",
    work_hours: null,
    default_max_open: 50,
    show_full_phones: false,
  },
  by_stage: { new: 3, won: 1 },
  by_source: { manual: 4 },
  unassigned: 1,
  waiting_first_call: 2,
  first_call_minutes: 6,
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  vi.stubGlobal("fetch", async (url: string) =>
    String(url).endsWith("/team")
      ? Response.json(team)
      : Response.json({ detail: "Not here" }, { status: 404 }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
}

// A panel's heading carries its small count or state ("Who takes new leads 1").
const headed = (title: string) =>
  [...host.querySelectorAll("h2, h3")].some((item) =>
    item.textContent?.trim().startsWith(title),
  );

it("shows only the rules in Settings → Lead rules", async () => {
  await act(async () => root.render(<LeadRulesPane />));
  await settle();
  for (const title of [
    "Who takes new leads",
    "Auto-reassign",
    "Limits and phone numbers",
    "Work hours",
  ])
    expect(headed(title)).toBe(true);
  // None of the dashboard: the team's numbers, calls, response times, stages.
  expect(host.querySelector('[aria-label="Team leads"]')).toBeNull();
  expect(host.textContent).not.toContain("Where leads stand");
  expect(host.textContent).not.toContain("Calls by seller");
  expect(host.textContent).not.toContain("calls today");
  expect(host.textContent).not.toContain("Due now");
  // No routing rules or language switch where the server doesn't offer them.
  expect(headed("Who gets which leads")).toBe(false);
  expect(host.textContent).not.toContain("Only sellers who speak");
  // Each seller's own rules stay one tap away.
  expect(
    host.querySelectorAll(
      'button[aria-label="Edit Priya Example\'s lead rules"]',
    ).length,
  ).toBeGreaterThan(0);
});

it("puts the routing rules first in Lead rules, not on Leads → Team", async () => {
  vi.stubGlobal("fetch", async (url: string) =>
    String(url).endsWith("/team")
      ? Response.json(team)
      : String(url).endsWith("/routing-rules")
        ? Response.json({
            schema: "lead-desk/1",
            revision: 1,
            can_edit: true,
            value_answer: null,
            rules: [],
            sources: {},
            people: [],
            questions: [],
          })
        : Response.json({ detail: "Not here" }, { status: 404 }),
  );
  await act(async () => root.render(<LeadRulesPane />));
  await settle();
  const titles = [...host.querySelectorAll("h2, h3")].map((item) =>
    item.textContent?.trim(),
  );
  expect(titles[0]).toBe("Who gets which leads");
  await act(async () =>
    root.render(
      <TeamView onChanged={() => undefined} onOpen={() => undefined} />,
    ),
  );
  await settle();
  expect(headed("Who gets which leads")).toBe(false);
});

it("makes languages strict at once, keeping the other settings", async () => {
  const sent: { url: string; body: unknown }[] = [];
  const offered: Team = {
    ...team,
    settings: { ...team.settings, strict_language: false },
  };
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as {
        strict_language: boolean;
      };
      sent.push({ url: String(url), body });
      return Response.json({
        ...offered,
        settings: {
          ...offered.settings,
          revision: 3,
          strict_language: body.strict_language,
        },
      });
    }
    return String(url).endsWith("/team")
      ? Response.json(offered)
      : Response.json({ detail: "Not here" }, { status: 404 });
  });
  await act(async () => root.render(<LeadRulesPane />));
  await settle();
  expect(host.textContent).toContain(
    "If nobody free speaks it, the lead still goes to someone.",
  );
  const strict = [...host.querySelectorAll("label")]
    .find((label) => label.textContent?.includes("Only sellers who speak"))!
    .querySelector("input")!;
  expect(strict.checked).toBe(false);
  await act(async () => strict.click());
  await settle();
  expect(sent).toHaveLength(1);
  expect(sent[0].url.endsWith("/settings")).toBe(true);
  expect(sent[0].body).toEqual({
    expected_revision: 2,
    auto_reassign: false,
    reassign_minutes: 10,
    strict_language: true,
  });
  expect(strict.checked).toBe(true);
  expect(host.textContent).toContain(
    "If nobody free speaks it, the lead waits for a manager to give it out.",
  );
});

it("keeps the team's numbers on Leads → Team", async () => {
  await act(async () =>
    root.render(
      <TeamView onChanged={() => undefined} onOpen={() => undefined} />,
    ),
  );
  await settle();
  expect(host.querySelector('[aria-label="Team leads"]')).not.toBeNull();
  expect(host.textContent).toContain("Where leads stand");
  expect(host.textContent).toContain("9 calls today");
  expect(headed("Sellers")).toBe(true);
});
