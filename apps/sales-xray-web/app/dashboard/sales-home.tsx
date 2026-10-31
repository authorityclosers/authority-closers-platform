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

import { FileText, Gauge, UsersRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { LibrarySubmission } from "../acquisition-client";
import { can } from "../organisation/roles";
import { FirstRun } from "./first-run";
import { MyTasks, SellerBlocks } from "./seller-home";
import type { Side } from "../ui/side-selector";
import { SetupStart } from "./home-v2";
import { TodayBar } from "./home-today";
import { TeamFloor } from "./team-floor";
import { HomeLoadWatch, useHomeRead } from "./home-load";
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
import { ModeSwitch } from "./mode-switch";
import { OutcomeTiles, TILE_SETS } from "./outcome-tiles";
import { TakingSwitch } from "../leads/taking-switch";
import type { HomeDesk } from "./my-day-client";
import { TodaySkeleton } from "./sales-home-skeleton";
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
}: {
  manages: boolean;
  mine: HomeDesk | null;
  me: string | null;
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

function SellerHome({ state }: { state: ReturnType<typeof useDesk> }) {
  const [side, setSide] = useHomeSide();
  if (state.status === "loading") return <TodaySkeleton />;
  if (state.status === "error")
    return (
      <section className={styles.block}>
        <TodayBar />
        <div className={styles.quiet} role="status">
          <span>Your leads didn&apos;t load. Come back in a moment.</span>
          <Link className={styles.more} href="/leads">
            Open Leads
          </Link>
        </div>
      </section>
    );
  const desk: HomeDesk = state.desk;
  return (
    <SellerBlocks
      desk={desk}
      side={side}
      onSide={setSide}
      headerExtras={
        <>
          {/* Taking new leads, as a small pill (Dipak, 28 Oct 2026). */}
          <TakingSwitch
            key={`taking-${desk.me.taking_leads !== false}`}
            initial={desk.me.taking_leads !== false}
            place="chip"
            pausedUntil={desk.me.paused_until ?? null}
          />
        </>
      }
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
}: {
  manager: boolean;
  /** Kept for callers; Home has one layout now (28 Oct 2026). */
  team?: "v1" | "v2";
  /** "v2": a new workspace starts with steps and the sample report. */
  layout?: "v1" | "v2";
  /** The latest saved calls the dashboard already read, for Recent calls. */
  recent?: readonly LibrarySubmission[] | null;
}) {
  const desk = useDesk();
  const [view, setView] = useHomeView();
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
  if (
    desk.status === "ready" &&
    works &&
    brandNew(desk.desk) &&
    (!manager || teamLeads === 0)
  )
    return (
      <div className={styles.home}>
        {layout === "v2" ? (
          <SetupStart desk={desk.desk} manager={manager && manages} />
        ) : (
          <FirstRun team={manager && manages ? "invite" : null} />
        )}
      </div>
    );
  // Team | Me (owner, 31 Oct 2026): for those who manage sellers and work
  // leads, one toggle; the whole screen slides in from its side.
  const shown: HomeView =
    manager && (view === "team" || !works) ? "team" : "mine";
  return (
    <div className={styles.home} data-home="">
      <HomeLoadWatch />
      {/* The month's revenue against its target (capture-setup's bar). */}
      <RevenueBar scope={shown === "team" ? "team" : "mine"} />
      {/* The month's revenue bar goes here, above both modes (capture-setup
          session, 31 Oct 2026). */}
      {manager && works ? (
        <ModeSwitch value={view} onChange={chooseView} />
      ) : null}
      <div key={shown} className={styles.mode} data-mode={shown}>
        {shown === "team" ? (
          <TeamHome
            manages={manages}
            mine={works && desk.status === "ready" ? desk.desk : null}
            me={desk.status === "ready" ? desk.desk.me.person_id : null}
          />
        ) : (
          <SellerHome state={desk} />
        )}
      </div>
    </div>
  );
}
