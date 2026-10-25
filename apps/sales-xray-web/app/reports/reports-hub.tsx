"use client";

/**
 * Reports, /reports (owner, 25 Oct 2026: "all report kinds in one place, with
 * types, categories and intelligence"): what stands out first, from real
 * numbers only; then every kind of report by category (calls, leads, team),
 * each with its own live line, one tap from its full view. Sellers see their
 * own; owners and admins also see the team's.
 */

import {
  AudioLines,
  BarChart3,
  ChevronRight,
  Filter,
  GraduationCap,
  LineChart,
  Sparkles,
  Timer,
  TrendingUp,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import { CALLS_PATH } from "../analysis-routes";
import { readCallSummary, type CallSummary } from "../dashboard/dashboard-data";
import { readPerformance, type Performance } from "../leads/leads-client";
import {
  readPipelineReport,
  type PipelineReport,
} from "../leads/pipeline/pipeline-client";
import { waCall, type SlaReport } from "../leads/whatsapp-client";
import { Skeleton } from "../ui/kit";
import styles from "./reports.module.css";

export type ReportKind = "all" | "calls" | "leads" | "team";

const KINDS: { key: ReportKind; label: string }[] = [
  { key: "all", label: "All" },
  { key: "calls", label: "Calls" },
  { key: "leads", label: "Leads" },
  { key: "team", label: "Team" },
];

export type ReportsData = {
  calls?: CallSummary | null;
  pipeline?: PipelineReport | null;
  performance?: Performance | null;
  sla?: SlaReport | null;
};

type Loaded<T> = T | null | undefined;

const percent = (part: number, whole: number) =>
  whole ? Math.round((part / whole) * 100) : null;

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count.toLocaleString("en-IN")} ${count === 1 ? one : many}`;

export type Standout = { key: string; text: string; href: string };

/**
 * What stands out, most urgent first, at most three, from facts the server
 * counted (never an estimate): calls that need a look, overdue leads, leads
 * waiting past the first-response target, the connect rate's move on last
 * week, and the most common reason for lost leads.
 */
export function standouts(data: ReportsData): Standout[] {
  const out: Standout[] = [];
  const { calls, pipeline, performance, sla } = data;
  if (calls?.needsAttention)
    out.push({
      key: "attention",
      text: `${plural(calls.needsAttention, "call")} ${calls.needsAttention === 1 ? "needs" : "need"} a look`,
      href: `${CALLS_PATH}?status=attention`,
    });
  if (pipeline?.overdue)
    out.push({
      key: "overdue",
      text: `${plural(pipeline.overdue, "lead")} ${pipeline.overdue === 1 ? "is" : "are"} overdue for a call`,
      href: "/leads",
    });
  const late = sla?.settings.on ? (sla.late?.length ?? 0) : 0;
  if (late)
    out.push({
      key: "late",
      text: `${plural(late, "new lead")} waited past ${sla?.settings.minutes} min for a first call`,
      href: "/dashboard",
    });
  if (performance) {
    const now = percent(
      performance.current.connected,
      performance.current.calls,
    );
    const before = percent(
      performance.previous.connected,
      performance.previous.calls,
    );
    if (now !== null && before !== null && Math.abs(now - before) >= 5)
      out.push({
        key: "connect",
        text: `${now}% of calls connected, ${now > before ? "up" : "down"} from ${before}% the week before`,
        href: "/dashboard?period=7",
      });
  }
  const lost = pipeline?.lost_moves[0];
  if (lost?.count)
    out.push({
      key: "lost",
      text: `Most leads lost this month: ${lost.label} (${lost.count})`,
      href: "/leads?tab=numbers",
    });
  return out.slice(0, 3);
}

function callsLine(calls: Loaded<CallSummary>) {
  if (calls === undefined) return undefined;
  if (!calls || !calls.total) return "Analyse a call to get your first report";
  return [
    `${plural(calls.completed, "report")} ready`,
    calls.needsAttention ? `${calls.needsAttention} need a look` : null,
    calls.processing ? `${calls.processing} on the way` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function pipelineLine(pipeline: Loaded<PipelineReport>) {
  if (pipeline === undefined) return undefined;
  if (!pipeline || !pipeline.total) return "Stage by stage, once leads come in";
  const reached = pipeline.first_connect.rate;
  return [
    `${plural(pipeline.total, "lead")} in 30 days`,
    reached !== null ? `${Math.round(reached * 100)}% reached` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function lostLine(pipeline: Loaded<PipelineReport>) {
  if (pipeline === undefined) return undefined;
  const top = pipeline?.lost_now[0];
  if (!pipeline || (!top && !pipeline.junk_now))
    return "Why leads are lost, once some are";
  return [
    top ? `Top reason: ${top.label} (${top.count})` : null,
    pipeline.junk_now ? `${pipeline.junk_now} junk` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function salesLine(performance: Loaded<Performance>) {
  if (performance === undefined) return undefined;
  if (!performance) return "Won, interested and connected, by period";
  const { current } = performance;
  const connected = percent(current.connected, current.calls);
  return [
    `${current.won} won`,
    `${current.interested} interested`,
    connected !== null ? `${connected}% connected` : null,
  ]
    .filter(Boolean)
    .join(" · ")
    .concat(" in 7 days");
}

function firstResponseLine(sla: Loaded<SlaReport>) {
  if (sla === undefined) return undefined;
  if (!sla?.settings.on) return "Set a first-response target in Leads settings";
  const late = sla.late?.length ?? 0;
  return late
    ? `${plural(late, "lead")} waiting past ${sla.settings.minutes} min now`
    : `Everyone answered within ${sla.settings.minutes} min`;
}

type Card = {
  key: string;
  kind: Exclude<ReportKind, "all">;
  icon: LucideIcon;
  tone: string;
  title: string;
  line: string | undefined;
  href: string;
  team?: boolean;
};

function cards(data: ReportsData): Card[] {
  return [
    {
      key: "calls",
      kind: "calls",
      icon: AudioLines,
      tone: "teal",
      title: "Call reports",
      line: callsLine(data.calls),
      href: CALLS_PATH,
    },
    {
      key: "coaching",
      kind: "calls",
      icon: GraduationCap,
      tone: "violet",
      title: "Coaching",
      line: "Your selling skills, from your analysed calls",
      href: "/coaching",
    },
    {
      key: "pipeline",
      kind: "leads",
      icon: Filter,
      tone: "blue",
      title: "Pipeline numbers",
      line: pipelineLine(data.pipeline),
      href: "/leads?tab=numbers",
    },
    {
      key: "lost",
      kind: "leads",
      icon: LineChart,
      tone: "slate",
      title: "Lost and junk",
      line: lostLine(data.pipeline),
      href: "/leads?tab=numbers",
    },
    {
      key: "sales",
      kind: "team",
      icon: TrendingUp,
      tone: "green",
      title: "How sales are going",
      line: salesLine(data.performance),
      href: "/dashboard?period=7",
      team: true,
    },
    {
      key: "first-response",
      kind: "team",
      icon: Timer,
      tone: "amber",
      title: "First response",
      line: firstResponseLine(data.sla),
      href: "/dashboard",
      team: true,
    },
    {
      key: "insights",
      kind: "team",
      icon: BarChart3,
      tone: "blue",
      title: "Team insights",
      line: "Calls, skills and outcomes across your sellers",
      href: "/organisation/insights",
      team: true,
    },
    {
      key: "sellers",
      kind: "team",
      icon: UsersRound,
      tone: "slate",
      title: "Sellers",
      line: "Each seller's calls, leads and coaching",
      href: "/organisation",
      team: true,
    },
  ];
}

const KIND_EVENT = "sx:reports-kind";

const readKind = (): ReportKind => {
  const asked = new URLSearchParams(window.location.search).get("kind");
  return KINDS.some((item) => item.key === asked)
    ? (asked as ReportKind)
    : "all";
};

const onKind = (change: () => void) => {
  window.addEventListener("popstate", change);
  window.addEventListener(KIND_EVENT, change);
  return () => {
    window.removeEventListener("popstate", change);
    window.removeEventListener(KIND_EVENT, change);
  };
};

/** The category, kept in the address without adding to Back. */
function useKind(): [ReportKind, (next: ReportKind) => void] {
  const kind = useSyncExternalStore(onKind, readKind, () => "all" as const);
  return [
    kind,
    (next) => {
      const params = new URLSearchParams(window.location.search);
      if (next === "all") params.delete("kind");
      else params.set("kind", next);
      const query = params.toString();
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}`,
      );
      window.dispatchEvent(new Event(KIND_EVENT));
    },
  ];
}

/** Each report's numbers, read side by side; one that fails shows its plain line. */
export function useReportsData(manager: boolean): ReportsData {
  const [data, setData] = useState<ReportsData>({});
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const put =
      <K extends keyof ReportsData>(key: K) =>
      (value: ReportsData[K]) => {
        if (!signal.aborted) setData((now) => ({ ...now, [key]: value }));
      };
    const none =
      <K extends keyof ReportsData>(key: K) =>
      () =>
        put(key)(null);
    readCallSummary(signal).then(put("calls"), none("calls"));
    readPipelineReport({ days: 30 }, signal).then(
      put("pipeline"),
      none("pipeline"),
    );
    if (manager) {
      readPerformance(7, signal).then(put("performance"), none("performance"));
      waCall<SlaReport>("/reports/sla", { signal }).then(
        put("sla"),
        none("sla"),
      );
    }
    return () => controller.abort();
  }, [manager]);
  return data;
}

export function ReportsHub({
  manager,
  data,
}: {
  /** Owners and admins: the team's reports too. */
  manager: boolean;
  data: ReportsData;
}) {
  const [kind, setKind] = useKind();
  const kinds = manager ? KINDS : KINDS.filter((item) => item.key !== "team");
  const shown = cards(data).filter(
    (card) => (manager || !card.team) && (kind === "all" || card.kind === kind),
  );
  const loaded =
    data.calls !== undefined &&
    data.pipeline !== undefined &&
    (!manager || (data.performance !== undefined && data.sla !== undefined));
  const facts = standouts(data);
  return (
    <div className={styles.hub}>
      <div className={styles.kinds} role="tablist" aria-label="Kind of report">
        {kinds.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={kind === item.key}
            className={styles.kind}
            onClick={() => setKind(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {kind === "all" ? (
        <section className={styles.standout} aria-labelledby="standout-title">
          <h2 id="standout-title">
            <Sparkles size={16} aria-hidden="true" />
            What stands out
          </h2>
          {!loaded ? (
            <div className={styles.standoutSkeleton} aria-hidden="true">
              <Skeleton width="80%" height={14} />
              <Skeleton width="60%" height={14} />
            </div>
          ) : facts.length ? (
            <ul>
              {facts.map((fact) => (
                <li key={fact.key}>
                  <Link href={fact.href}>
                    <span>{fact.text}</span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.calm}>
              Nothing needs you right now. Your reports are below.
            </p>
          )}
        </section>
      ) : null}
      {(["calls", "leads", "team"] as const)
        .filter((group) => shown.some((card) => card.kind === group))
        .map((group) => (
          <section
            key={group}
            className={styles.group}
            aria-labelledby={`reports-${group}`}
          >
            <h2 id={`reports-${group}`}>
              {KINDS.find((item) => item.key === group)?.label}
            </h2>
            <ul className={styles.cards}>
              {shown
                .filter((card) => card.kind === group)
                .map((card) => {
                  const Icon = card.icon;
                  return (
                    <li key={card.key}>
                      <Link
                        className={styles.card}
                        href={card.href}
                        data-tone={card.tone}
                      >
                        <span className={styles.icon} aria-hidden="true">
                          <Icon size={20} />
                        </span>
                        <span className={styles.words}>
                          <strong>{card.title}</strong>
                          {card.line === undefined ? (
                            <Skeleton width={160} height={12} />
                          ) : (
                            <small>{card.line}</small>
                          )}
                        </span>
                        <ChevronRight size={16} aria-hidden="true" />
                      </Link>
                    </li>
                  );
                })}
            </ul>
          </section>
        ))}
    </div>
  );
}
