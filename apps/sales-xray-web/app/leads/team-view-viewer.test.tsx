// @vitest-environment happy-dom
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

import { WorkspaceAccessContext } from "../workspace-access";
import type { RepView, Team } from "./leads-client";
import { TeamView } from "./team-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Roles B (27 Oct 2026): a Viewer reads the team page and changes nothing;
// owners, admins and managers keep every control.
const TENANT = "00000000-0000-4000-8000-000000000004";

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
    auto_reassign: true,
    reassign_minutes: 10,
    default_country: "91",
    work_hours: {
      days: [0, 1, 2, 3, 4],
      start: "09:30",
      end: "19:00",
      pause_leads: true,
      inside: true,
    },
    default_max_open: 50,
    show_full_phones: false,
    strict_language: false,
  },
  by_stage: { new: 3, won: 1 },
  by_source: { manual: 4 },
  unassigned: 1,
  waiting_first_call: 2,
  first_call_minutes: 6,
} as unknown as Team;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
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

async function mount(
  role: "owner" | "admin" | "manager" | "member" | "viewer",
  rulesOnly = false,
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: TENANT },
          workspaces: [
            {
              tenant_id: TENANT,
              kind: "organisation",
              name: "Fictional Homes",
              role,
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <TeamView
          onChanged={() => {}}
          onOpen={() => {}}
          rulesOnly={rulesOnly}
        />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await act(async () => Promise.resolve());
}

/** The team's settings panels: auto-reassign, limits and work hours. */
const settings = () =>
  [...host.querySelectorAll("fieldset")].filter(
    (set) =>
      // A panel's own fieldset, not one inside it (the limit field has its own).
      !set.parentElement?.closest("fieldset") &&
      ["Minutes before it moves", "Open Inbound leads", "Starts"].some(
        (label) => set.textContent?.includes(label),
      ),
  );

const buttons = (label: string) =>
  [...host.querySelectorAll("button")].filter((button) =>
    (button.getAttribute("aria-label") ?? button.textContent ?? "").includes(
      label,
    ),
  );

it("gives a Viewer the team to read, with no way to change it", async () => {
  await mount("viewer");
  expect(host.textContent).toContain(
    "You can see the team. Owners, admins and managers change its rules.",
  );
  // The seller's rules sheet (its switch, stepper and Save) never opens.
  expect(buttons("lead rules")).toHaveLength(0);
  // The settings are shown, every field disabled, and nothing saves.
  const sets = settings();
  expect(sets).toHaveLength(3);
  expect(sets.every((set) => set.disabled)).toBe(true);
  for (const label of ["Turn off", "Check now", "Save work hours", "Save"])
    expect(
      buttons(label).filter((b) => b.textContent?.trim().endsWith(label)),
    ).toHaveLength(0);
  // The languages switch reads its state and can't be flipped.
  const strict = [...host.querySelectorAll<HTMLInputElement>("input")].find(
    (input) => input.closest("label")?.textContent?.includes("speak the lead"),
  );
  expect(strict?.disabled).toBe(true);
  // The team itself still reads: the seller and their rules in words.
  expect(host.textContent).toContain("Priya Example");
  expect(host.textContent).toContain("Marathi");
});

it("keeps every control for those who manage leads", async () => {
  await mount("manager");
  expect(host.textContent).not.toContain("You can see the team.");
  expect(buttons("lead rules").length).toBeGreaterThan(0);
  expect(settings()).toHaveLength(3);
  expect(settings().every((set) => !set.disabled)).toBe(true);
  for (const label of ["Turn off", "Check now", "Save work hours", "Save"])
    expect(
      buttons(label).filter((b) => b.textContent?.trim().endsWith(label)),
    ).not.toHaveLength(0);
});

it("leaves routing rules to managers on Settings → Lead rules", async () => {
  await mount("viewer", true);
  expect(host.textContent).not.toContain("Who gets which leads");
});
