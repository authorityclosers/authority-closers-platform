"use client";

/**
 * Home in an organisation (owner, 22 Oct 2026): "Working late", "your call
 * analysis", "ready reports" and "minutes left" mean nothing to a salesperson,
 * "Attention needs 5" is not a metric, and there was no direct call to action.
 *
 * - Owners and admins first see how sales are going: won, interested, new
 *   leads and connect rate for today, 7 or 30 days, each beside the period
 *   before; then sellers ranked by what they won; then the open leads by
 *   stage. Call analysis comes after, on the page below.
 * - A salesperson sees today: who is late, who to call now and later, with
 *   one primary action, "Call <name>", and today's own numbers.
 *
 * Only real numbers: nothing here is estimated or invented.
 */

import { ChevronRight, PhoneCall, UsersRound } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import type { LibrarySubmission } from "../acquisition-client";
import { useWeekActivity } from "../calls/call-rows";
import { displayName } from "../display-name";
import { can } from "../organisation/roles";
import { DayTiles, MyStages } from "./day-board";
import { FirstRun } from "./first-run";
import { HomeActivity, HomeRecentCalls, PickUp, SetupStart } from "./home-v2";
import { TeamActivity } from "./team-activity";
import { TeamControls } from "./team-controls";
import { whyLine } from "../leads/desk-view";
import { handOverLead } from "../leads/lead-handoff";
import {
  deskSections,
  readDesk,
  readTeam,
  readPerformance,
  when,
  type Desk,
  type LeadRow,
  type Performance,
  type Period,
} from "../leads/leads-client";
import { ActionList, ActionRow, Avatar, Segmented } from "../ui/kit";
import { NeedsYou } from "./needs-you";
import { OutcomeTiles } from "./outcome-tiles";
import { StuckFunnel } from "./stuck-funnel";
import { ShareOut } from "../leads/assign-sheet";
import { TakingSwitch } from "../leads/taking-switch";
import type { HomeDesk } from "./my-day-client";
import { DayNumbers, DoNowRow, NextUp, TeamPoolCard, useMyDay } from "./my-day";
import { RecentlyCalled } from "./recently-called";
import { RowsSkeleton, TodaySkeleton } from "./sales-home-skeleton";
import styles from "./sales-home.module.css";

const percent = (part: number, whole: number) =>
  whole ? `${Math.round((part / whole) * 100)}%` : "–";

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

function TeamHome({
  desk,
  layout = "v1",
  saved = null,
}: {
  desk: Desk | null;
  layout?: "v1" | "v2";
  /** The team's latest saved calls, for Team today's reports. */
  saved?: readonly LibrarySubmission[] | null;
}) {
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
  const shown = report?.period === period ? report.value : null;
  const late = shown?.sellers.reduce((sum, seller) => sum + seller.late, 0);
  const mineDue = desk ? desk.queue.length : 0;

  const salesBlock = (
    <section className={styles.block} aria-labelledby="sales-title">
      <div className={styles.head}>
        <h2 id="sales-title">How sales are going</h2>
      </div>
      {/* Owner Home v3 (28 Oct 2026): B's tiles, the period as the one segmented
          control; each tile opens its detail. */}
      <OutcomeTiles
        period={period}
        onPeriod={setPeriod}
        performance={shown}
        failed={failed === period}
      />
      <div className={styles.chips}>
        {mineDue ? (
          <Link className={styles.chip} href="/leads">
            <PhoneCall size={15} aria-hidden="true" />
            {`${mineDue} for you to call today`}
          </Link>
        ) : null}
      </div>
    </section>
  );
  // Approved map, slice 8: what is waiting on someone, before who sold what.
  const needs = <NeedsYou desk={desk} late={shown ? late : undefined} />;
  return (
    <>
      {/* Owner Home v3 (28 Oct 2026, B): the period's outcomes first, then
          what needs you, then the team's day (Team v2's feed). */}
      {salesBlock}
      {needs}
      {/* Owner Home v3, A: where the open leads wait, and what to do. */}
      <StuckFunnel performance={shown} />
      {layout === "v2" ? <TeamActivity saved={saved} /> : null}

      <section className={styles.block} aria-labelledby="sellers-title">
        <div className={styles.head}>
          <h2 id="sellers-title">Sellers</h2>
          <span className={styles.meta}>By what they won</span>
        </div>
        {shown ? (
          shown.sellers.length ? (
            <ol className={styles.list}>
              {shown.sellers.map((seller) => (
                <li key={seller.person_id}>
                  <Link
                    className={styles.row}
                    href={`/organisation/people/${seller.person_id}`}
                  >
                    <Avatar name={seller.name} size={34} />
                    <span className={styles.rowMain}>
                      <strong>{seller.name}</strong>
                      {/* Each number keeps its word; the line breaks only
                          between them (polish pass, 24 Oct 2026). */}
                      <small>
                        {`${seller.won}\u00a0won · ${seller.interested}\u00a0interested · ${seller.calls}\u00a0${seller.calls === 1 ? "call" : "calls"}`}
                      </small>
                    </span>
                    <span className={styles.rowEnd}>
                      <span className={styles.rate}>
                        {percent(seller.connected, seller.calls)}
                        <small>connected</small>
                      </span>
                      {seller.late ? (
                        <span
                          className={styles.late}
                        >{`${seller.late} late`}</span>
                      ) : null}
                    </span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ol>
          ) : (
            <div className={styles.quiet}>
              <span>Add sellers to see how each one does.</span>
              {desk?.me.can_manage ? (
                <Link className={styles.more} href="/organisation/invites">
                  Invite sellers
                </Link>
              ) : null}
            </div>
          )
        ) : (
          <RowsSkeleton rows={3} kind="seller" />
        )}
        {/* Owner, 23 Oct 2026: team and organisation were "too hidden". */}
        <ActionList label="Team">
          <ActionRow
            icon={<UsersRound size={20} />}
            tone="neutral"
            title="Organisation"
            note="Team, analytics, insights and settings"
            href="/organisation"
          />
        </ActionList>
      </section>
    </>
  );
}

function LeadLink({ row }: { row: LeadRow }) {
  return (
    <li>
      <Link
        className={styles.row}
        href="/leads"
        onClick={() => handOverLead(row.lead_id)}
        data-late={row.overdue ? "" : undefined}
      >
        <Avatar name={row.name} size={34} />
        <span className={styles.rowMain}>
          <strong>{row.name}</strong>
          <small>{whyLine(row)}</small>
        </span>
        {row.overdue ? <span className={styles.late}>Late</span> : null}
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </li>
  );
}

function SellerHome({
  state,
  before = null,
  after = null,
}: {
  state: ReturnType<typeof useDesk>;
  /** Home v2 (27 Oct 2026): what goes above Today, and what replaces the
   *  stage strip and Recently called below it. */
  before?: ReactNode;
  after?: ReactNode;
}) {
  // Read beside the desk, so both land together (Lead OS's team engine).
  const myDay = useMyDay();
  const [now] = useState(() => Date.now());
  const [sharing, setSharing] = useState(false);
  if (state.status === "loading" || myDay.status === "loading")
    return <TodaySkeleton />;
  if (state.status === "error")
    return (
      <section className={styles.block}>
        <div className={styles.head}>
          <h2>Today</h2>
        </div>
        <div className={styles.quiet} role="status">
          <span>Your leads didn&apos;t load. Come back in a moment.</span>
          <Link className={styles.more} href="/leads">
            Open Leads
          </Link>
        </div>
      </section>
    );
  const desk: HomeDesk = state.desk;
  const sections = deskSections(desk.queue);
  const count = (key: string) =>
    sections.find((section) => section.key === key)?.rows.length ?? 0;
  // My day's ranked work with why; the desk's queue if My day didn't load.
  const ranked = myDay.status === "ready" ? myDay.value.do_now : null;
  const first = ranked
    ? ranked[0] && { id: ranked[0].lead_id, name: ranked[0].lead_name }
    : desk.queue[0] && { id: desk.queue[0].lead_id, name: desk.queue[0].name };
  const fallback = myDay.status === "ready" ? myDay.value.fallback : null;
  const later = desk.upcoming?.[0];
  const mineNone = !desk.queue.length && !desk.counts.open;
  return (
    <>
      {/* Taking new leads, or not, in plain sight with one tap to change
          (owner, 25 Oct 2026: "it isn't clear whether I'm taking leads"). */}
      <section className={styles.taking} aria-label="New leads">
        <TakingSwitch
          key={`taking-${desk.me.taking_leads !== false}`}
          initial={desk.me.taking_leads !== false}
          place="row"
          pausedUntil={desk.me.paused_until ?? null}
        />
      </section>
      {before}
      <section className={styles.block} aria-labelledby="today-title">
        <div className={styles.head}>
          <h2 id="today-title">Today</h2>
          {/* A clear button, not a quiet label (orchestrator for the owner,
              27 Oct 2026): everyone due, on Leads. */}
          <Link className={styles.headAction} href="/leads">
            <UsersRound size={16} aria-hidden="true" />
            Who to call
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </div>
        {/* The day at a glance, each tile one tap into its Leads (owner,
            #18, 26 Oct 2026: Home was the same as Leads). */}
        <DayTiles
          counts={{
            overdue: count("overdue"),
            dueToday: count("now") + count("later"),
            fresh: desk.counts.new,
            calls: desk.numbers.calls,
          }}
        />
        {first ? (
          <>
            <ol className={styles.list}>
              {ranked
                ? ranked
                    .slice(0, 2)
                    .map((item) => (
                      <DoNowRow key={item.lead_id} item={item} now={now} />
                    ))
                : desk.queue
                    .slice(0, 2)
                    .map((row) => <LeadLink key={row.lead_id} row={row} />)}
            </ol>
            <Link
              className={styles.primary}
              href="/leads"
              onClick={() => handOverLead(first.id, true)}
            >
              <PhoneCall size={18} aria-hidden="true" />
              {`Call ${displayName(first.name).split(" ")[0]}`}
            </Link>
            {desk.queue.length > 2 ? (
              <Link className={styles.more} href="/leads">
                {`See all ${desk.queue.length} for today`}
              </Link>
            ) : null}
          </>
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
            <div className={styles.caughtUp}>
              <strong>All caught up</strong>
              <span>
                {fallback?.next_up.length
                  ? "Nothing is due now. Next up:"
                  : later?.next_action_at
                    ? `Next call ${when(later.next_action_at)}: ${displayName(later.name)}.`
                    : "New leads land on Leads the moment they come in."}
              </span>
              {fallback?.next_up.length ? null : (
                <Link className={styles.more} href="/leads">
                  Open Leads
                </Link>
              )}
            </div>
            {fallback ? <NextUp items={fallback.next_up} /> : null}
          </>
        )}
      </section>
      {after ?? (
        <>
          <MyStages />
          <RecentlyCalled />
        </>
      )}
      <DayNumbers desk={desk} myDay={myDay} />
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

const VIEWS: { key: HomeView; label: string }[] = [
  { key: "team", label: "Team" },
  { key: "mine", label: "My day" },
];

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

/** Home v2's seller day: where you left off and your last calls above Today,
 *  your recent activity below it, from one read of this week's work. */
function SellerHomeV2({
  state,
  recent,
}: {
  state: ReturnType<typeof useDesk>;
  recent: readonly LibrarySubmission[] | null;
}) {
  const [week] = useWeekActivity();
  return (
    <SellerHome
      state={state}
      before={
        <>
          <PickUp />
          <HomeRecentCalls week={week} saved={recent} />
        </>
      }
      after={<HomeActivity week={week} />}
    />
  );
}

export function SalesHome({
  manager,
  layout = "v1",
  team = "v1",
  recent = null,
}: {
  manager: boolean;
  /** "v2": the Team view redesign, on review fixtures until signed off. */
  team?: "v1" | "v2";
  /** "v2": the Home redesign (27 Oct 2026), on review fixtures until signed off. */
  layout?: "v1" | "v2";
  /** The latest saved calls the dashboard already read, for v2's Recent calls. */
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
      {manager && (works || manages) ? (
        <div className={styles.homeBar}>
          {works ? (
            <Segmented
              label="Show"
              value={view}
              onChange={setView}
              items={VIEWS}
            />
          ) : null}
          {/* Owner Home v3 (28 Oct 2026, #52): targets, nudges and the lead
              rules behind one labelled gear, not in the scroll. */}
          {manages && (view === "team" || !works) ? <TeamControls /> : null}
        </div>
      ) : null}
      {manager && (view === "team" || !works) ? (
        <TeamHome
          desk={desk.status === "ready" ? desk.desk : null}
          layout={team}
          saved={recent}
        />
      ) : layout === "v2" ? (
        <SellerHomeV2 state={desk} recent={recent} />
      ) : (
        <SellerHome state={desk} />
      )}
    </div>
  );
}
