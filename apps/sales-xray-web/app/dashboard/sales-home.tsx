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
  CalendarClock,
  ChevronRight,
  Flame,
  PhoneCall,
  Trophy,
  UserPlus,
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
import { Avatar, Delta, Segmented } from "../ui/kit";
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

function OutcomesSkeleton() {
  return (
    <dl className={styles.outcomes} aria-busy="true">
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className={styles.outcome} data-skeleton="">
          <span className={styles.outcomeIcon} />
          <dt>
            <i className={styles.bar} />
          </dt>
          <dd>
            <i className={styles.barBig} />
          </dd>
          <dd className={styles.outcomeNote}>
            <i className={styles.bar} />
          </dd>
        </div>
      ))}
    </dl>
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
          <Segmented
            label="Period"
            value={String(period)}
            onChange={(key) => setPeriod(Number(key) as Period)}
            items={PERIODS}
          />
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
          {late ? (
            <Link className={styles.chip} data-tone="bad" href="/leads">
              <CalendarClock size={15} aria-hidden="true" />
              {`${late} late ${late === 1 ? "follow-up" : "follow-ups"}`}
            </Link>
          ) : null}
          {mineDue ? (
            <Link className={styles.chip} href="/leads">
              <PhoneCall size={15} aria-hidden="true" />
              {`${mineDue} for you to call today`}
            </Link>
          ) : null}
        </div>
      </section>

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
                      <small>
                        {`${seller.won} won · ${seller.interested} interested · ${seller.calls} ${seller.calls === 1 ? "call" : "calls"}`}
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
            <p className={styles.quiet}>
              Add sellers in Organisation to see how each one does.
            </p>
          )
        ) : (
          <div className={styles.listSkeleton} aria-busy="true">
            {[0, 1, 2].map((index) => (
              <i key={index} />
            ))}
          </div>
        )}
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
          <div className={styles.listSkeleton} aria-busy="true">
            {[0, 1, 2, 3].map((index) => (
              <i key={index} />
            ))}
          </div>
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
                  style={{ width: `${Math.max(2, (count / most) * 100)}%` }}
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
  if (state.status === "loading")
    return (
      <section className={styles.block} aria-busy="true">
        <div className={styles.head}>
          <h2>Today</h2>
        </div>
        <div className={styles.listSkeleton}>
          {[0, 1, 2].map((index) => (
            <i key={index} />
          ))}
        </div>
      </section>
    );
  if (state.status === "error")
    return (
      <section className={styles.block}>
        <div className={styles.head}>
          <h2>Today</h2>
        </div>
        <p className={styles.quiet} role="status">
          Your leads didn&apos;t load. Open Leads, or come back in a moment.
        </p>
      </section>
    );
  const { desk } = state;
  const sections = deskSections(desk.queue);
  const count = (key: string) =>
    sections.find((section) => section.key === key)?.rows.length ?? 0;
  const next = desk.queue[0];
  const later = desk.upcoming?.[0];
  const { numbers } = desk;
  return (
    <>
      <section className={styles.block} aria-labelledby="today-title">
        <div className={styles.head}>
          <h2 id="today-title">Today</h2>
          <span className={styles.meta}>Who to call</span>
        </div>
        <div className={styles.chips}>
          {count("overdue") ? (
            <Link className={styles.chip} data-tone="bad" href="/leads">
              {`${count("overdue")} late`}
            </Link>
          ) : null}
          <Link className={styles.chip} href="/leads">
            {`${count("now")} to call now`}
          </Link>
          <Link className={styles.chip} href="/leads">
            {`${count("later")} later today`}
          </Link>
        </div>
        {next ? (
          <>
            <ol className={styles.list}>
              {desk.queue.slice(0, 4).map((row) => (
                <LeadLink key={row.lead_id} row={row} />
              ))}
            </ol>
            <Link
              className={styles.primary}
              href="/leads"
              onClick={() => handOverLead(next.lead_id, true)}
            >
              <PhoneCall size={18} aria-hidden="true" />
              {`Call ${displayName(next.name).split(" ")[0]}`}
            </Link>
            {desk.queue.length > 4 ? (
              <Link className={styles.more} href="/leads">
                {`See all ${desk.queue.length} for today`}
              </Link>
            ) : null}
          </>
        ) : (
          <div className={styles.caughtUp}>
            <strong>All caught up</strong>
            <span>
              {later?.next_action_at
                ? `Next call ${when(later.next_action_at)}: ${later.name}.`
                : "New leads land on Leads the moment they come in."}
            </span>
            <Link className={styles.more} href="/leads">
              Open Leads
            </Link>
          </div>
        )}
      </section>
      <dl className={styles.dayStrip} aria-label="Your day">
        <div>
          <dt>Calls</dt>
          <dd>{numbers.calls}</dd>
        </div>
        <div>
          <dt>Connected</dt>
          <dd>{numbers.connected}</dd>
        </div>
        <div>
          <dt>Follow-ups done</dt>
          <dd>{numbers.follow_ups_done}</dd>
        </div>
      </dl>
    </>
  );
}

export function SalesHome({ manager }: { manager: boolean }) {
  const desk = useDesk();
  return (
    <div className={styles.home}>
      {manager ? (
        <TeamHome desk={desk.status === "ready" ? desk.desk : null} />
      ) : (
        <SellerHome state={desk} />
      )}
    </div>
  );
}
