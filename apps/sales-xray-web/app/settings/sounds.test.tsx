// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  played: [] as string[],
  view: null as unknown,
  saved: [] as unknown[],
  team: [] as unknown[],
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));
vi.mock("../notice-center", () => ({ notify: mocks.notify }));
vi.mock("../sounds/player", () => ({
  playSound: (choice: string) => {
    mocks.played.push(choice);
    return true;
  },
  stopSound: () => undefined,
  isPlaying: () => false,
}));
vi.mock("../sounds/prefs", async (original) => ({
  ...(await original<typeof import("../sounds/prefs")>()),
  readSounds: async () => mocks.view,
  saveMine: async (_view: unknown, mine: Record<string, string | null>) => {
    mocks.saved.push(mine);
    const view = mocks.view as {
      events: {
        id: string;
        team: string;
        mine: string | null;
        plays: string;
      }[];
    };
    return {
      ...view,
      events: view.events.map((row) =>
        row.id in mine
          ? { ...row, mine: mine[row.id], plays: mine[row.id] ?? row.team }
          : row,
      ),
    };
  },
  saveTeam: async (team: Record<string, string>, sellersPick: boolean) => {
    mocks.team.push({ team, sellersPick });
    return { ...(mocks.view as object), sellers_pick: sellersPick };
  },
}));

import { SX_EVENTS } from "../sounds/library";
import { MySounds, TeamSounds } from "./sounds";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const view = (over: Record<string, unknown> = {}) => ({
  events: SX_EVENTS.map((event) => ({
    id: event.id,
    team: event.default,
    mine: event.id === "sx.report_ready" ? "warm-v1.success" : null,
    plays: event.id === "sx.report_ready" ? "warm-v1.success" : event.default,
  })),
  sellers_pick: true,
  manager: false,
  own_picks: 1,
  ...over,
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mocks.played = [];
  mocks.saved = [];
  mocks.team = [];
  mocks.notify.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const button = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) =>
      item.textContent?.trim() === name ||
      item.getAttribute("aria-label") === name,
  );

it("lists every moment in the library's groups, the team's or mine", async () => {
  mocks.view = view();
  await act(async () => root.render(<MySounds />));
  const groups = [...host.querySelectorAll("section[aria-label] > h2")].map(
    (h2) => h2.textContent,
  );
  expect(groups).toEqual([
    "Calls",
    "Messages & leads",
    "Reminders",
    "Feedback",
  ]);
  expect(host.textContent).toContain("Incoming call");
  expect(host.textContent).toContain("Glass V3 · Ringtone");
  expect(host.textContent).toContain("Warm V1 · Success");
  expect(host.textContent).toContain("Mine");
  expect(host.textContent).toContain("Team default");
  expect(host.textContent).toContain("Just me");
  // Every row is a 44 px tap that opens its picker, with a telemetry name.
  const rows = host.querySelectorAll('button[data-sx-feature="sound_open"]');
  expect(rows).toHaveLength(6);
});

it("picks from the sheet: hear it, pick it, Done saves mine and says when it plays", async () => {
  mocks.view = view();
  await act(async () => root.render(<MySounds />));
  const lead = [
    ...host.querySelectorAll<HTMLButtonElement>(
      'button[data-sx-feature="sound_open"]',
    ),
  ].find((row) => row.textContent?.includes("New lead given to me"));
  await act(async () => lead?.click());
  const sheet = document.querySelector("dialog");
  expect(sheet?.textContent).toContain("Glass");
  expect(sheet?.textContent).toContain("Synth A · Mention");
  expect(sheet?.textContent).toContain("Phone default");
  // ▶ plays without picking.
  await act(async () => button("Play Pulse V2 · Mention")?.click());
  expect(mocks.played).toEqual(["pulse-v2.mention"]);
  // Picking plays it once too, then Done saves it as mine.
  const pick = [
    ...(sheet?.querySelectorAll<HTMLButtonElement>(
      'button[data-sx-feature="sound_pick"]',
    ) ?? []),
  ].find((item) => item.textContent?.includes("Warm V3 · Mention"));
  await act(async () => pick?.click());
  expect(mocks.played.at(-1)).toBe("warm-v3.mention");
  await act(async () => button("Done")?.click());
  expect(mocks.saved).toEqual([{ "sx.new_lead": "warm-v3.mention" }]);
  expect(mocks.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "success",
      title: "Saved for you",
      message: "Warm V3 · Mention plays on your next new lead.",
    }),
  );
});

it("goes back to the team's sound, and locks the rows when sellers can't pick", async () => {
  mocks.view = view();
  await act(async () => root.render(<MySounds />));
  const report = [
    ...host.querySelectorAll<HTMLButtonElement>(
      'button[data-sx-feature="sound_open"]',
    ),
  ].find((row) => row.textContent?.includes("Call report ready"));
  await act(async () => report?.click());
  await act(async () => button("Use team default")?.click());
  expect(mocks.saved).toEqual([{ "sx.report_ready": null }]);
  await act(async () => root.unmount());
  root = createRoot(host);
  mocks.view = view({ sellers_pick: false });
  await act(async () => root.render(<MySounds />));
  expect(
    host.querySelectorAll('button[data-sx-feature="sound_open"]'),
  ).toHaveLength(0);
  expect(host.textContent).toContain("set by your owner");
});

it("lets the owner set the team's sound per moment, who may pick their own, and reset", async () => {
  mocks.view = view({ manager: true });
  await act(async () => root.render(<TeamSounds />));
  expect(host.textContent).toContain(
    "Sellers hear these unless they pick their own.",
  );
  expect(host.textContent).toContain("1 person picked sounds of their own.");
  expect(
    host.querySelectorAll('[data-sx-feature="team_sound_pick"]'),
  ).toHaveLength(6);
  await act(async () => button("Play Glass V3 · Ringtone")?.click());
  expect(mocks.played).toEqual(["glass-v3.ringtone"]);
  await act(async () =>
    host.querySelector<HTMLButtonElement>('button[role="switch"]')?.click(),
  );
  expect(mocks.team.at(-1)).toEqual({ team: {}, sellersPick: false });
  await act(async () => button("Reset to library default")?.click());
  expect(mocks.team.at(-1)).toEqual(
    expect.objectContaining({
      team: Object.fromEntries(
        SX_EVENTS.map((event) => [event.id, event.default]),
      ),
    }),
  );
  expect(mocks.notify).toHaveBeenCalledWith(
    expect.objectContaining({ title: "Saved for everyone" }),
  );
});

it("sends a seller to their own sounds from the team's page", async () => {
  mocks.view = view();
  await act(async () => root.render(<TeamSounds />));
  expect(host.textContent).toContain(
    "Your owner or an admin sets the team’s sounds.",
  );
  expect(host.querySelector('a[href="/settings/sounds"]')).not.toBeNull();
});
