"use client";

/**
 * Home in an organisation (owner's 28 Oct 2026 meeting, section 03: "today's
 * work on top, recent work below"; bugs #70–#72 from his Android phone).
 *
 * - Today's line, with its few controls on it: My day or Team, and for those
 *   who manage leads, Team controls behind the gear.
 * - The top four, each red until its rule is met and one tap into Leads: for
 *   the team, new leads, open leads as a share of all, late follow-ups and
 *   leads with no owner; for you, new and open leads, today's follow-ups and
 *   today's tasks.
 * - One primary action: Call the next lead (you), or review the late
 *   follow-ups (the team).
 * - The second figures sideways in a slider (the team's outcomes).
 * - The team's recent calls, with Activity beside them; then My work.
 * - A seller's Home (Leads redesign, section 6; Dipak and the owner, 30 Oct
 *   2026): today's work counting down and the pending work first; then what
 *   was done (Analyse yourself, then recent calls with Activity beside them,
 *   three each); the longest breaks last.
 *
 * Only real numbers: nothing here is estimated or invented.
 */

import { FileText, Gauge, UsersRound, WifiOff } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { LibrarySubmission } from "../acquisition-client";
import { can } from "../organisation/roles";
import { FirstRun } from "./first-run";
import { MyTasks, SellerBlocks, useSidesAccess } from "./seller-home";
import type { Side } from "../ui/side-selector";
import { SetupStart } from "./home-v2";
import { TeamFloor, type StageKeys } from "./team-floor";
import { HomeLoadWatch, useHomeRead, useOnline } from "./home-load";
import { RevenueBar } from "./revenue-bar";
import { TeamControls } from "./team-controls";
import {
  readDesk,
  readPerformance,
  readTeam,
  type Desk,
  type Period,
} from "../leads/leads-client";
import { ActionList, ActionRow } from "../ui/kit";
import { InCorner } from "../notice-center";
import { ModeSwitch } from "./mode-switch";
import { OutcomeTiles, TILE_SETS } from "./outcome-tiles";
import type { HomeDesk } from "./my-day-client";
import styles from "./sales-home.module.css";

const PERIOD_EVENT = "sx:home-period";

const readPeriod = (): Period => {
  const asked = Number(
    new URLSearchParams(window.location.search).get("period"),
  );
  return asked === 1 || asked === 30 ? asked : 7;
};

const onPeriod = (change: () => void) => {
  window.addEventListener("popstate", change);
  window.addEventListener(PERIOD_EVENT, change);
  return () => {
    window.removeEventListener("popstate", change);
    window.removeEventListener(PERIOD_EVENT, change);
  };
};

/** Today, 7 or 30 days: kept in the address, so a refresh keeps it. */
function usePeriod(): [Period, (next: Period) => void] {
  const period = useSyncExternalStore<Period>(onPeriod, readPeriod, () => 7);
  return [
    period,
    (next) => {
      const url = new URL(window.location.href);
      url.searchParams.set("period", String(next));
      window.history.replaceState(null, "", url.pathname + url.search);
      window.dispatchEvent(new Event(PERIOD_EVENT));
    },
  ];
}

/** The desk, read once (and again on Retry); the last good one if a read fails. */
function useDesk():
  | { status: "loading" }
  | { status: "ready"; desk: Desk }
  | { status: "error" } {
  const { value, failed } = useHomeRead("desk", (signal) => readDesk(signal));
  return value
    ? { status: "ready", desk: value }
    : failed
      ? { status: "error" }
      : { status: "loading" };
}

/** All the organisation's leads, for an owner or admin; null until read, and
 *  still null if the read fails (Home then stays as it is). */
function useTeamLeadCount(enabled: boolean): number | null {
  const [total, setTotal] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    readTeam(controller.signal).then(
      (team) =>
        setTotal(
          Object.values(team.by_stage).reduce((sum, n) => sum + n, 0) +
            (team.unassigned ?? 0),
        ),
      () => undefined,
    );
    return () => controller.abort();
  }, [enabled]);
  return total;
}

/** The stages Home's lead cards open, as the server found them by meaning; an older
 *  server (no sides) or a desk that failed keeps the first and Open Leads keys. */
function stagesOf(desk: ReturnType<typeof useDesk>): StageKeys | undefined {
  if (desk.status === "loading") return undefined;
  const side =
    desk.status === "ready" ? (desk.desk as HomeDesk).sides?.inbound : null;
  return side
    ? { newKey: side.new_key, openKey: side.open_key }
    : { newKey: "new", openKey: "open_leads" };
}

/** The period's report for the team, with the period kept in the address. */
function usePerformance() {
  const [period, setPeriod] = usePeriod();
  const { value, failed } = useHomeRead(`performance:${period}`, (signal) =>
    readPerformance(period, signal),
  );
  return { period, setPeriod, shown: value, failed: failed && !value };
}

/** The team's Home: the floor, on the side the address names; the
 *  owner's own tasks beside it when they work leads. */
function TeamHome({
  manages,
  mine,
  me,
  stages,
}: {
  manages: boolean;
  mine: HomeDesk | null;
  me: string | null;
  stages: StageKeys | undefined;
}) {
  const { period, setPeriod, shown, failed } = usePerformance();
  const [side, setSide] = useHomeSide();
  const sellers = shown?.sellers.length ?? 0;
  return (
    <TeamFloor
      side={side}
      onSide={setSide}
      controls={manages ? <TeamControls /> : null}
      mine={mine ? <MyTasks desk={mine} side={side} /> : null}
      me={me}
      stages={stages}
      outcomes={
        <OutcomeTiles
          period={period}
          onPeriod={setPeriod}
          performance={shown}
          failed={failed}
          tiles={TILE_SETS.outcomes}
          layout="grid"
        />
      }
      more={
        <ActionList label="More">
          <ActionRow
            icon={<Gauge size={20} />}
            tone="neutral"
            title="Performance"
            note="Each seller's calls, talk time and breaks"
            href="/growth"
          />
          <ActionRow
            icon={<UsersRound size={20} />}
            tone="neutral"
            title="Your team"
            note={
              sellers
                ? `${sellers} ${sellers === 1 ? "seller" : "sellers"}`
                : "Sellers and how each one does"
            }
            href="/organisation?tab=team"
          />
          <ActionRow
            icon={<FileText size={20} />}
            tone="neutral"
            title="Call reports"
            note="Every analysed call"
            href="/reports"
          />
        </ActionList>
      }
    />
  );
}

const SIDES_KEY = "sx:home-sides";
const subscribeNothing = () => () => {};
const readKeptSides = (): string | null => {
  try {
    return window.localStorage.getItem(SIDES_KEY);
  } catch {
    return null;
  }
};

/** Which sides this seller works: the read, or while it is on the way the
 *  last answer on this device, so the Inbound | Cold selector is in its place
 *  from the first frame (the test robot, 1 Nov 2026: 0.06 at 360 px when it
 *  arrived after Today). */
function useKeptSides(
  access: { inbound: boolean; cold: boolean } | null,
): { inbound: boolean; cold: boolean } | null {
  const kept = useSyncExternalStore(
    subscribeNothing,
    readKeptSides,
    () => null,
  );
  useEffect(() => {
    if (!access) return;
    try {
      window.localStorage.setItem(
        SIDES_KEY,
        `${Number(access.inbound)}${Number(access.cold)}`,
      );
    } catch {
      // Not kept this time; the read still answers.
    }
  }, [access]);
  if (access) return access;
  return kept === "11"
    ? { inbound: true, cold: true }
    : kept === "10"
      ? { inbound: true, cold: false }
      : kept === "01"
        ? { inbound: false, cold: true }
        : null;
}

function SellerHome({
  state,
  onDrawn,
}: {
  state: ReturnType<typeof useDesk>;
  onDrawn?: () => void;
}) {
  const [side, setSide] = useHomeSide();
  const access = useKeptSides(useSidesAccess());
  const answered = state.status !== "loading";
  const known = access !== null;
  useEffect(() => {
    if (known && answered) onDrawn?.();
  }, [known, answered, onDrawn]);
  // Loading and a failed read draw the same blocks in the same places, with
  // placeholders or "–" (FRAMEWORK L6: a skeleton the shape of the result;
  // the four cards and the next call never vanish on a bad network).
  // Home keeps no Taking new leads pill (Dipak's picture, 2 Nov 2026): it is
  // in Settings and on Leads.
  // A device that has never seen this seller's sides draws Today's outline at
  // once, the selector's place held, and fills both in when the sides are
  // known: never a blank page on a slow line (QA robot 4cf9a9c7 and 054a9c20,
  // 9 Nov 2026, 3G at 360 and 390), and the selector never lands above Today
  // (the test robot, 1 Nov 2026: 0.06 at 360 px). Later visits draw at once
  // from the kept answer.
  const status = access ? state.status : "loading";
  return (
    <SellerBlocks
      desk={
        access && state.status === "ready" ? (state.desk as HomeDesk) : null
      }
      state={status}
      side={side}
      onSide={setSide}
      access={access}
    />
  );
}

const readSide = (): Side =>
  new URLSearchParams(window.location.search).get("side") === "cold"
    ? "cold"
    : "inbound";

/** Your day's side, Inbound or Cold (Dipak's handoff, items 05-06), kept in
 *  the address like the view, so Back returns to the same mode. Home opens on
 *  Inbound, as Leads does. */
function useHomeSide(): [Side, (next: Side) => void] {
  const side = useSyncExternalStore<Side>(onView, readSide, () => "inbound");
  const choose = (next: Side) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "cold") params.set("side", "cold");
    else params.delete("side");
    const query = params.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
    window.dispatchEvent(new Event(VIEW_EVENT));
  };
  return [side, choose];
}

type HomeView = "team" | "mine";

const VIEW_EVENT = "sx:home-view";

const readView = (): HomeView =>
  new URLSearchParams(window.location.search).get("view") === "mine"
    ? "mine"
    : "team";

const onView = (change: () => void) => {
  window.addEventListener("popstate", change);
  window.addEventListener(VIEW_EVENT, change);
  return () => {
    window.removeEventListener("popstate", change);
    window.removeEventListener(VIEW_EVENT, change);
  };
};

/** Owners and admins: Team, or My day (their own calls), kept in the address.
 *  The server draws Team and the address's choice follows on the phone, so the
 *  two never disagree (a direct ?view=mine threw a hydration error and showed
 *  "Something glitched", 25 Oct 2026). */
function useHomeView(): [HomeView, (next: HomeView) => void] {
  const view = useSyncExternalStore<HomeView>(onView, readView, () => "team");
  const choose = (next: HomeView) => {
    const params = new URLSearchParams(window.location.search);
    if (next === "mine") params.set("view", "mine");
    else params.delete("view");
    const query = params.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
    window.dispatchEvent(new Event(VIEW_EVENT));
  };
  return [view, choose];
}

/** Nothing here yet: no leads (none waiting in the team either), nothing
 *  coming up, no calls, not the sandbox. */
function brandNew(desk: HomeDesk): boolean {
  return (
    !desk.sandbox &&
    !desk.team_pool?.open &&
    desk.counts.open === 0 &&
    !desk.counts.unassigned &&
    desk.queue.length === 0 &&
    (desk.upcoming?.length ?? 0) === 0 &&
    desk.numbers.calls === 0
  );
}

export function SalesHome({
  manager,
  layout = "v1",
  onDrawn,
}: {
  manager: boolean;
  /** Kept for callers; Home has one layout now (28 Oct 2026). */
  team?: "v1" | "v2";
  /** "v2": a new workspace starts with steps and the sample report. */
  layout?: "v1" | "v2";
  /** The latest saved calls the dashboard already read, for Recent calls. */
  recent?: readonly LibrarySubmission[] | null;
  /**
   * Called once this block has drawn its content (the desk has answered and,
   * on My day, the seller's sides are known): the dashboard puts the sandbox
   * card after it only then, so the card never sits where this content lands
   * (QA robot 474deee5, 9 Nov 2026).
   */
  onDrawn?: () => void;
}) {
  const desk = useDesk();
  const [view, setView] = useHomeView();
  const online = useOnline();
  const person = desk.status === "ready" ? desk.desk.me.person_id : null;
  // Remembered per person on this device; the address still says which, so
  // Back returns to it.
  useEffect(() => {
    if (!person || new URLSearchParams(window.location.search).has("view"))
      return;
    try {
      if (window.localStorage.getItem(`sx:home-view:${person}`) === "mine")
        setView("mine");
    } catch {
      // Storage refused (a private window): Team, as before.
    }
  }, [person]); // eslint-disable-line react-hooks/exhaustive-deps
  const chooseView = (next: HomeView) => {
    setView(next);
    try {
      if (person) window.localStorage.setItem(`sx:home-view:${person}`, next);
    } catch {
      // Not remembered this time; the address still has it.
    }
  };
  const teamLeads = useTeamLeadCount(manager);
  // A Viewer sees the team and works no leads (Roles B, 27 Oct 2026): the Team
  // view only, with no My day and no first steps; editing stays with managers.
  const me = desk.status === "ready" ? desk.desk.me : null;
  const works = me === null || can(me.role, "leads.work");
  const manages = me?.can_manage === true;
  // A brand-new workspace: three first steps, not empty figures (owner, #20).
  const starting =
    desk.status === "ready" &&
    works &&
    brandNew(desk.desk) &&
    (!manager || teamLeads === 0);
  // Team | Me (owner, 31 Oct 2026): for those who manage sellers and work
  // leads, one toggle; the whole screen slides in from its side.
  const shown: HomeView =
    manager && (view === "team" || !works) ? "team" : "mine";
  // The first steps and the team's view are drawn once the desk has
  // answered; My day says so itself, once the seller's sides are known too.
  const answered = desk.status !== "loading";
  useEffect(() => {
    if (answered && (starting || shown === "team")) onDrawn?.();
  }, [answered, starting, shown, onDrawn]);
  if (starting)
    return (
      <div className={styles.home}>
        {layout === "v2" ? (
          <SetupStart desk={desk.desk} manager={manager && manages} />
        ) : (
          <FirstRun team={manager && manages ? "invite" : null} />
        )}
      </div>
    );
  return (
    <div className={styles.home} data-home="">
      <HomeLoadWatch />
      {/* Offline: a corner card over the page, with the other corner cards,
          so Home never moves as it comes and goes (ux-audit, 9 Nov 2026: in
          the page's flow it moved Home 28 to 40 px each way at 363). */}
      {online ? null : (
        <InCorner>
          <p className={styles.offline} role="status">
            <WifiOff size={16} aria-hidden="true" />
            You&apos;re offline. Showing what was saved.
          </p>
        </InCorner>
      )}
      {/* The month's revenue against its target, above both modes
          (capture-setup session, 31 Oct 2026), with Team | Me at the end of
          its line rather than on a row of its own (Home studio, 4 Nov 2026:
          the row it freed keeps the next call above the fold). */}
      <RevenueBar
        scope={shown === "team" ? "team" : "mine"}
        end={
          manager && works ? (
            <ModeSwitch value={view} onChange={chooseView} />
          ) : undefined
        }
      />

      <div key={shown} className={styles.mode} data-mode={shown}>
        {shown === "team" ? (
          <TeamHome
            manages={manages}
            mine={works && desk.status === "ready" ? desk.desk : null}
            me={desk.status === "ready" ? desk.desk.me.person_id : null}
            stages={stagesOf(desk)}
          />
        ) : (
          <SellerHome state={desk} onDrawn={onDrawn} />
        )}
      </div>
    </div>
  );
}
