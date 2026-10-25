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

import {
  ChevronDown,
  ChevronRight,
  Flame,
  PhoneCall,
  Trophy,
  UserPlus,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { displayName } from "../display-name";
import { whyLine } from "../leads/desk-view";
import { handOverLead } from "../leads/lead-handoff";
import {
  deskSections,
  readDesk,
  readPerformance,
  when,
  type Desk,
  type LeadRow,
  type Performance,
  type Period,
} from "../leads/leads-client";
import {
  MAIN_PIPELINE,
  readJourney,
  type Kind,
} from "../leads/journey/journey-client";
import { KIND_WORDS } from "../leads/stage-tabs";
import { several, usePipelines } from "../leads/use-pipelines";
import { ActionList, ActionRow, Avatar, Delta, Segmented } from "../ui/kit";
import { NeedsYou } from "./needs-you";
import { TakingSwitch } from "../leads/taking-switch";
import type { HomeDesk } from "./my-day-client";
import { DayNumbers, DoNowRow, NextUp, TeamPoolCard, useMyDay } from "./my-day";
import { RecentlyCalled } from "./recently-called";
import {
  FunnelSkeleton,
  OutcomesSkeleton,
  RowsSkeleton,
  TodaySkeleton,
} from "./sales-home-skeleton";
import styles from "./sales-home.module.css";

const PERIODS: { key: string; label: string }[] = [
  { key: "1", label: "Today" },
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
];

const OPEN_KINDS = ["new", "not_connected", "follow_up", "interested"] as const;

const percent = (part: number, whole: number) =>
  whole ? `${Math.round((part / whole) * 100)}%` : "–";

function minutesWords(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 6) / 10;
  return hours < 24 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

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

function Outcome({
  icon: Icon,
  tone,
  label,
  value,
  delta,
  note,
}: {
  icon: LucideIcon;
  tone: "good" | "violet" | "teal" | "slate";
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  note: ReactNode;
}) {
  return (
    <div className={styles.outcome} data-tone={tone}>
      <span className={styles.outcomeIcon} aria-hidden="true">
        <Icon size={18} />
      </span>
      <dt>{label}</dt>
      <dd>
        <span className={styles.outcomeValue}>{value}</span>
        {delta}
      </dd>
      <dd className={styles.outcomeNote}>{note}</dd>
    </div>
  );
}

function TeamHome({ desk }: { desk: Desk | null }) {
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
  const now = shown?.current;
  const before = shown?.previous;
  const late = shown?.sellers.reduce((sum, seller) => sum + seller.late, 0);
  // Several pipelines: the funnel shows one at a time, in its own stages.
  const pipes = usePipelines();
  const [picked, setPicked] = useState<string | null>(null);
  const inPipeline = several(pipes)
    ? (
        pipes.pipelines.find((item) => item.key === picked) ??
        pipes.pipelines[0]
      ).key
    : null;
  const open = shown
    ? inPipeline
      ? (shown.pipelines?.[inPipeline] ?? {})
      : shown.pipeline
    : null;
  const mineDue = desk ? desk.queue.length : 0;

  return (
    <>
      <section className={styles.block} aria-labelledby="sales-title">
        <div className={styles.head}>
          <h2 id="sales-title">How sales are going</h2>
          {/* Team | My day is the screen's one switch; the period is a chip. */}
          <label className={styles.periodChip}>
            <select
              aria-label="Period"
              value={String(period)}
              onChange={(event) =>
                setPeriod(Number(event.target.value) as Period)
              }
            >
              {PERIODS.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
            <ChevronDown size={14} aria-hidden="true" />
          </label>
        </div>
        {now && before ? (
          <dl className={styles.outcomes}>
            <Outcome
              icon={Trophy}
              tone="good"
              label="Won"
              value={now.won}
              delta={<Delta value={now.won} previous={before.won} />}
              note={
                now.leads_called
                  ? `${percent(now.won, now.leads_called)} of ${now.leads_called} leads called`
                  : "No leads called yet"
              }
            />
            <Outcome
              icon={Flame}
              tone="violet"
              label="Interested"
              value={now.interested}
              delta={
                <Delta value={now.interested} previous={before.interested} />
              }
              note="Leads who said they want it"
            />
            <Outcome
              icon={UserPlus}
              tone="teal"
              label="New leads"
              value={now.new_leads}
              delta={
                <Delta value={now.new_leads} previous={before.new_leads} />
              }
              note={
                now.first_call_minutes !== null
                  ? `First call in ${minutesWords(now.first_call_minutes)}`
                  : now.new_leads
                    ? "None called yet"
                    : "None came in"
              }
            />
            <Outcome
              icon={PhoneCall}
              tone="slate"
              label="Connected"
              value={percent(now.connected, now.calls)}
              delta={
                <Delta value={now.connected} previous={before.connected} />
              }
              note={`${now.connected} of ${now.calls} ${now.calls === 1 ? "call" : "calls"}`}
            />
          </dl>
        ) : failed === period ? (
          <p className={styles.quiet} role="status">
            Sales numbers didn&apos;t load. Pull down or come back in a moment.
          </p>
        ) : (
          <OutcomesSkeleton />
        )}
        <div className={styles.chips}>
          {mineDue ? (
            <Link className={styles.chip} href="/leads">
              <PhoneCall size={15} aria-hidden="true" />
              {`${mineDue} for you to call today`}
            </Link>
          ) : null}
        </div>
      </section>

      {/* Approved map, slice 8: what is waiting on someone, before who sold what. */}
      <NeedsYou desk={desk} late={shown ? late : undefined} />

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
              <Link className={styles.more} href="/organisation/invites">
                Invite sellers
              </Link>
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

      <section className={styles.block} aria-labelledby="pipeline-title">
        <div className={styles.head}>
          <h2 id="pipeline-title">Open leads by stage</h2>
          {open ? (
            <span className={styles.meta}>
              {`${OPEN_KINDS.reduce((sum, kind) => sum + (open[kind] ?? 0), 0)} open now`}
            </span>
          ) : null}
        </div>
        {several(pipes) && inPipeline ? (
          <Segmented
            label="Pipeline"
            value={inPipeline}
            onChange={setPicked}
            items={pipes.pipelines.map((item) => ({
              key: item.key,
              label: item.name,
            }))}
          />
        ) : null}
        {open ? (
          <Funnel pipeline={open} inPipeline={inPipeline} />
        ) : (
          <FunnelSkeleton />
        )}
      </section>
    </>
  );
}

/**
 * A pipeline's own name for each kind of stage, where it has one stage of that
 * kind (Redmi, 22 Oct 2026: Home read "New / Not contacted" while Leads read
 * "New enquiry / Couldn't reach").
 */
function useStageNames(pipeline: string): Partial<Record<Kind, string>> {
  const [names, setNames] = useState<{
    key: string;
    value: Partial<Record<Kind, string>>;
  } | null>(null);
  useEffect(() => {
    let live = true;
    readJourney(pipeline).then(
      (view) => {
        if (!live) return;
        const found: Partial<Record<Kind, string>> = {};
        for (const kind of OPEN_KINDS) {
          const own = view.stages.filter(
            (stage) => !stage.archived && stage.kind === kind,
          );
          if (own.length === 1) found[kind] = own[0].label;
        }
        setNames({ key: pipeline, value: found });
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [pipeline]);
  return names?.key === pipeline ? names.value : {};
}

function Funnel({
  pipeline,
  inPipeline = null,
}: {
  pipeline: Record<string, number>;
  /** The pipeline shown, when the organisation runs several. */
  inPipeline?: string | null;
}) {
  const names = useStageNames(inPipeline ?? MAIN_PIPELINE);
  const where = inPipeline ? `&pipeline=${encodeURIComponent(inPipeline)}` : "";
  const most = Math.max(1, ...OPEN_KINDS.map((kind) => pipeline[kind] ?? 0));
  return (
    <ul className={styles.funnel}>
      {OPEN_KINDS.map((kind) => {
        const count = pipeline[kind] ?? 0;
        return (
          <li key={kind} data-kind={kind}>
            <Link href={`/leads?tab=all&stage=${kind}${where}`}>
              <span className={styles.funnelLabel}>
                {names[kind] ?? KIND_WORDS[kind]}
              </span>
              <span className={styles.funnelTrack} aria-hidden="true">
                <span
                  className={styles.funnelBar}
                  style={{
                    width: count ? `${Math.max(2, (count / most) * 100)}%` : 0,
                  }}
                />
              </span>
              <strong className={styles.funnelCount}>{count}</strong>
            </Link>
          </li>
        );
      })}
    </ul>
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

function SellerHome({ state }: { state: ReturnType<typeof useDesk> }) {
  // Read beside the desk, so both land together (Lead OS's team engine).
  const myDay = useMyDay();
  const [now] = useState(() => Date.now());
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
      <section className={styles.block} aria-labelledby="today-title">
        <div className={styles.head}>
          <h2 id="today-title">Today</h2>
          <span className={styles.meta}>Who to call</span>
        </div>
        {/* Only counts that are there: never "0 to call now". */}
        <div className={styles.chips}>
          {count("overdue") ? (
            <Link className={styles.chip} data-tone="bad" href="/leads">
              {`${count("overdue")} late`}
            </Link>
          ) : null}
          {count("now") ? (
            <Link className={styles.chip} href="/leads">
              {`${count("now")} to call now`}
            </Link>
          ) : null}
          {count("later") ? (
            <Link className={styles.chip} href="/leads">
              {`${count("later")} later today`}
            </Link>
          ) : null}
        </div>
        {first ? (
          <>
            <ol className={styles.list}>
              {ranked
                ? ranked
                    .slice(0, 4)
                    .map((item) => (
                      <DoNowRow key={item.lead_id} item={item} now={now} />
                    ))
                : desk.queue
                    .slice(0, 4)
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
            {desk.queue.length > 4 ? (
              <Link className={styles.more} href="/leads">
                {`See all ${desk.queue.length} for today`}
              </Link>
            ) : null}
          </>
        ) : mineNone && desk.team_pool?.open ? (
          <TeamPoolCard desk={desk} />
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
      <RecentlyCalled />
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

export function SalesHome({ manager }: { manager: boolean }) {
  const desk = useDesk();
  const [view, setView] = useHomeView();
  return (
    <div className={styles.home}>
      {manager ? (
        <Segmented label="Show" value={view} onChange={setView} items={VIEWS} />
      ) : null}
      {manager && view === "team" ? (
        <TeamHome desk={desk.status === "ready" ? desk.desk : null} />
      ) : (
        <SellerHome state={desk} />
      )}
    </div>
  );
}
