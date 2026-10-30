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

import {
  ArrowRight,
  ChevronRight,
  FileText,
  Gauge,
  PhoneCall,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import type { LibrarySubmission } from "../acquisition-client";
import { useWeekActivity } from "../calls/call-rows";
import { displayName } from "../display-name";
import { can } from "../organisation/roles";
import { FirstRun } from "./first-run";
import { HomeActivity, HomeRecentCalls, SetupStart } from "./home-v2";
import {
  FourTiles,
  MyWork,
  RecentToggle,
  TodayBar,
  TodayCountdown,
  YourBreaks,
  mineFour,
  teamFour,
} from "./home-today";
import { TeamActivity } from "./team-activity";
import { TeamControls } from "./team-controls";
import { handOverLead } from "../leads/lead-handoff";
import {
  readDesk,
  readPerformance,
  readTasks,
  readTeam,
  type Desk,
  type Performance,
  type Period,
} from "../leads/leads-client";
import { ActionList, ActionRow } from "../ui/kit";
import { OutcomeTiles, TILE_SETS } from "./outcome-tiles";
import { ShareOut } from "../leads/assign-sheet";
import { TakingSwitch } from "../leads/taking-switch";
import type { HomeDesk } from "./my-day-client";
import { NextUp, TeamPoolCard, YourTargets, useMyDay } from "./my-day";
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

function useDesk() {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "ready"; desk: Desk }
    | { status: "error" }
  >({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    readDesk(controller.signal)
      .then((desk) => setState({ status: "ready", desk }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, []);
  return state;
}

/** Your tasks due today and those already past their time; null until read,
 *  "off" when they didn't load (the tile says so instead of waiting forever). */
function useTasksToday() {
  const [tasks, setTasks] = useState<
    { today: number; late: number } | "off" | null
  >(null);
  useEffect(() => {
    const controller = new AbortController();
    readTasks("today", controller.signal).then(
      (list) =>
        setTasks({
          today: list.counts.today ?? 0,
          late: list.counts.overdue ?? 0,
        }),
      () => {
        if (!controller.signal.aborted) setTasks("off");
      },
    );
    return () => controller.abort();
  }, []);
  return tasks;
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
  const [report, setReport] = useState<{
    period: Period;
    value: Performance;
  } | null>(null);
  const [failed, setFailed] = useState<Period | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readPerformance(period, controller.signal)
      .then((value) => {
        setReport({ period, value });
        setFailed(null);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(period);
      });
    return () => controller.abort();
  }, [period]);
  return {
    period,
    setPeriod,
    shown: report?.period === period ? report.value : null,
    failed: failed === period,
  };
}

/** My day or Team: one tap, on Today's line. */
function ViewChip({ to, onPick }: { to: HomeView; onPick: () => void }) {
  return (
    <button type="button" className={styles.viewShortcut} onClick={onPick}>
      {to === "mine" ? "My day" : "Team"}
      <ChevronRight size={16} aria-hidden="true" />
    </button>
  );
}

function TeamHome({
  desk,
  saved,
  allLeads,
  works,
  manages,
  onMine,
}: {
  desk: HomeDesk | null;
  /** The team's latest saved calls, for Recent calls' Reports. */
  saved: readonly LibrarySubmission[] | null;
  allLeads: number | null;
  works: boolean;
  manages: boolean;
  onMine: () => void;
}) {
  const { period, setPeriod, shown, failed } = usePerformance();
  const four = teamFour(shown, allLeads, desk?.counts.unassigned ?? null);
  const late = shown?.sellers.reduce((sum, seller) => sum + seller.late, 0);
  const sellers = shown?.sellers.length ?? 0;
  return (
    <>
      <TodayBar>
        {works ? <ViewChip to="mine" onPick={onMine} /> : null}
        {manages ? <TeamControls /> : null}
      </TodayBar>
      <FourTiles label="The team's day" tiles={four} />
      {/* The screen's one primary action, while any follow-up is late. */}
      {manages && late ? (
        <Link className={styles.primary} href="/leads?tab=all&due=late">
          {`Review ${late} late ${late === 1 ? "follow-up" : "follow-ups"}`}
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      ) : null}
      <section className={styles.block} aria-labelledby="sales-title">
        <div className={styles.head}>
          <h2 id="sales-title">How sales are going</h2>
        </div>
        <OutcomeTiles
          period={period}
          onPeriod={setPeriod}
          performance={shown}
          failed={failed}
          tiles={TILE_SETS.slider}
          layout="slider"
        />
      </section>
      <RecentToggle
        calls={<TeamActivity saved={saved} bare only="calls" />}
        activity={<TeamActivity saved={saved} bare />}
        seeAll={{ calls: "/analysis/calls" }}
      />
      {works ? <MyWork desk={desk} /> : null}
      <ActionList label="More">
        <ActionRow
          icon={<Gauge size={20} />}
          tone="neutral"
          title="Performance"
          note="Each seller's calls, talk time and breaks, Live and Cold apart"
          href="/performance"
        />
        <ActionRow
          icon={<UsersRound size={20} />}
          tone="neutral"
          title="Your team"
          note={
            sellers
              ? `${sellers} ${sellers === 1 ? "seller" : "sellers"}, how each one does`
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
    </>
  );
}

function SellerHome({
  state,
  recent,
  onTeam,
}: {
  state: ReturnType<typeof useDesk>;
  recent: readonly LibrarySubmission[] | null;
  /** Owners and admins: back to the team's Home. */
  onTeam?: () => void;
}) {
  // Read beside the desk, so both land together (Lead OS's team engine).
  const myDay = useMyDay();
  const tasks = useTasksToday();
  const [week] = useWeekActivity();
  const [sharing, setSharing] = useState(false);
  if (state.status === "loading" || myDay.status === "loading")
    return <TodaySkeleton />;
  if (state.status === "error")
    return (
      <section className={styles.block}>
        <TodayBar>
          {onTeam ? <ViewChip to="team" onPick={onTeam} /> : null}
        </TodayBar>
        <div className={styles.quiet} role="status">
          <span>Your leads didn&apos;t load. Come back in a moment.</span>
          <Link className={styles.more} href="/leads">
            Open Leads
          </Link>
        </div>
      </section>
    );
  const desk: HomeDesk = state.desk;
  // My day's ranked work with why; the desk's queue if My day didn't load.
  const ranked = myDay.status === "ready" ? myDay.value.do_now : null;
  const first = ranked
    ? ranked[0] && { id: ranked[0].lead_id, name: ranked[0].lead_name }
    : desk.queue[0] && { id: desk.queue[0].lead_id, name: desk.queue[0].name };
  const mineNone = !desk.queue.length && !desk.counts.open;
  const nextUp =
    myDay.status === "ready" ? myDay.value.fallback?.next_up : null;
  return (
    <>
      <TodayBar>
        {/* Taking new leads, as a small pill (Dipak, 28 Oct 2026). */}
        <TakingSwitch
          key={`taking-${desk.me.taking_leads !== false}`}
          initial={desk.me.taking_leads !== false}
          place="chip"
          pausedUntil={desk.me.paused_until ?? null}
        />
        {onTeam ? <ViewChip to="team" onPick={onTeam} /> : null}
      </TodayBar>
      <TodayCountdown desk={desk} />
      <FourTiles label="Your day" tiles={mineFour(desk, tasks)} />
      {first ? (
        <Link
          className={styles.primary}
          href="/leads"
          onClick={() => handOverLead(first.id, true)}
        >
          <PhoneCall size={18} aria-hidden="true" />
          {`Call ${displayName(first.name).split(" ")[0]}`}
        </Link>
      ) : mineNone && desk.team_pool?.open ? (
        <>
          <TeamPoolCard desk={desk} onShare={() => setSharing(true)} />
          {desk.me.can_manage ? (
            <ShareOut
              open={sharing}
              target={{
                kind: "unassigned",
                count: desk.team_pool?.unassigned ?? 0,
              }}
              onClose={() => setSharing(false)}
              onDone={() => setSharing(false)}
            />
          ) : null}
        </>
      ) : (
        <>
          <p className={styles.caughtUp} role="status">
            <strong>All caught up</strong>
            <span>
              {nextUp?.length
                ? "Nothing is due now. Next up:"
                : "New leads land on Leads the moment they come in."}
            </span>
          </p>
          {nextUp?.length ? <NextUp items={nextUp} /> : null}
        </>
      )}
      <YourTargets myDay={myDay} />
      <MyWork desk={desk} />
      {/* What was done, under the pending work: three each, one tap to all. */}
      <RecentToggle
        calls={<HomeRecentCalls week={week} saved={recent} bare />}
        activity={<HomeActivity week={week} bare />}
        seeAll={{ calls: "/analysis/calls", activity: "/leads?tab=work" }}
      />
      <YourBreaks desk={desk} />
    </>
  );
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
  recent = null,
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
  return (
    <div className={styles.home}>
      {manager && (view === "team" || !works) ? (
        <TeamHome
          desk={desk.status === "ready" ? desk.desk : null}
          saved={recent}
          allLeads={teamLeads}
          works={works}
          manages={manages}
          onMine={() => setView("mine")}
        />
      ) : (
        <SellerHome
          state={desk}
          recent={recent}
          onTeam={manager ? () => setView("team") : undefined}
        />
      )}
    </div>
  );
}
