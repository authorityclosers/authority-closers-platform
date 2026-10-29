"use client";

/**
 * Insights: the owner's and manager's company view (AUT-1798). Every call in
 * the organisation, combined: trend, outcomes, people and teams, skills,
 * objections, mistakes, talk share, strongest and weakest calls, and how
 * skills are moving. One read brings every aggregate (the server sums them),
 * so the page arrives whole; filters live in the address.
 */
import {
  ArrowUpRight,
  BarChart3,
  Lock,
  RotateCw,
  Search,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { callPath } from "../../analysis-routes";
import { notify } from "../../notice-center";
import {
  Button,
  Delta,
  Empty,
  Kpi,
  PageHeader,
  Panel,
  Segmented,
  Table,
  Card,
  Tiles,
} from "../../ui/kit";
import {
  BarList,
  ShareLine,
  SkillDots,
  SkillGaps,
  SkillHeatmap,
  SkillSplit,
  TalkBands,
  TrendColumns,
} from "./insights-charts";
import {
  INSIGHTS_PATH,
  OUTCOMES,
  RANGES,
  VIEWS,
  activeFilterCount,
  addressQuery,
  count,
  dateLabel,
  duration,
  minutes,
  outcomeLabel,
  parseCallPage,
  parseInsights,
  percent,
  queryOf,
  type CallPage,
  type CallRow,
  type Filters,
  type Group,
  type Insights,
  type RangeKey,
  type View,
} from "./insights-data";
import styles from "./insights.module.css";
import { OutcomeStory } from "./insights-outcomes";
import { InsightsSkeleton } from "./insights-skeleton";

type Read =
  | { status: "loading" }
  | { status: "ready"; value: Insights }
  | { status: "denied" }
  | { status: "signed-out" }
  | { status: "error" };

export type InsightsSeed = { status: number; body: unknown } | null;

function seedOf(seed: InsightsSeed | undefined): Read | null {
  if (!seed || seed.status === 401) return null;
  if (seed.status === 403) return { status: "denied" };
  if (seed.status >= 200 && seed.status < 300)
    return { status: "ready", value: parseInsights(seed.body) };
  return null;
}

async function readJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: { accept: "application/json", ...init?.headers },
  });
  if (!response.ok) throw new ReadError(response.status);
  return response.json();
}

class ReadError extends Error {
  constructor(readonly status: number) {
    super(`Read failed (${status})`);
  }
}

const RANGE_TEXT: Record<RangeKey, string> = {
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  "12m": "Last 12 months",
  all: "All time",
};

export function InsightsView({
  filters: initialFilters,
  view = "overview",
  initial,
  initialCalls,
  callHref = callPath,
  fixture = false,
}: {
  filters: Filters;
  /** Overview, People or Calls; kept in the address (?view=). */
  view?: View;
  initial?: InsightsSeed;
  initialCalls?: InsightsSeed;
  /** Where a call opens; null for synthetic calls (they have no report page). */
  callHref?: ((key: string) => string) | null;
  /** Review fixtures: never read or refresh. */
  fixture?: boolean;
}) {
  const pathname = usePathname();
  // Filters are the page's own state, written to the address as they change
  // (no server round trip); a reload starts from the address again.
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [section, setSection] = useState<View>(view);
  const query = queryOf(filters);
  const [read, setRead] = useState<Read>(
    () => seedOf(initial) ?? { status: "loading" },
  );
  const [updating, setUpdating] = useState(false);
  const [calls, setCalls] = useState<CallPage | null>(() =>
    initialCalls && initialCalls.status === 200
      ? parseCallPage(initialCalls.body)
      : null,
  );
  const [moreLoading, setMoreLoading] = useState(false);
  const [preparing, setPreparing] = useState<number | null>(null);
  // The query whose figures are on screen (or on their way): a repeat of the
  // same query (React's development double effects) never reads twice.
  const shown = useRef(read.status === "ready" ? query : null);
  // Every read gets a number; an answer for an older one is dropped.
  const sequence = useRef(0);

  const load = useCallback(async (target: string) => {
    const id = ++sequence.current;
    setUpdating(true);
    try {
      const [overview, page] = await Promise.all([
        readJson(INSIGHTS_PATH + target),
        readJson(`${INSIGHTS_PATH}/calls${target}`).catch(() => null),
      ]);
      if (id !== sequence.current) return;
      setRead({ status: "ready", value: parseInsights(overview) });
      setCalls(page === null ? null : parseCallPage(page));
    } catch (error) {
      if (id !== sequence.current) return;
      const status = error instanceof ReadError ? error.status : 0;
      if (status === 403) setRead({ status: "denied" });
      else if (status === 401) setRead({ status: "signed-out" });
      else {
        setRead((current) =>
          current.status === "ready" ? current : { status: "error" },
        );
        notify({
          id: "insights-read",
          tone: "error",
          title: "Insights couldn’t load",
          message: "Check your connection and try again.",
          action: { label: "Try again", run: () => void load(target) },
        });
      }
    } finally {
      if (id === sequence.current) setUpdating(false);
    }
  }, []);

  // The address always says what is shown (after a workspace switch too).
  useEffect(() => {
    if (fixture) return;
    const target = `${pathname}${addressQuery(filters, section)}`;
    if (`${window.location.pathname}${window.location.search}` !== target)
      window.history.replaceState(null, "", target);
  }, [filters, fixture, pathname, section]);

  useEffect(() => {
    if (fixture || shown.current === query) return;
    shown.current = query;
    void load(query);
  }, [query, load, fixture]);

  // New calls since the last look: bring the projection up to date in
  // bounded batches, then read again. Honest about it while it runs.
  const pending = read.status === "ready" ? read.value.pending : 0;
  useEffect(() => {
    // Each run owns its loop; a new filter or answer cancels the old one, and
    // the line always clears when its loop ends or is cancelled.
    if (fixture || pending <= 0) return;
    let cancelled = false;
    (async () => {
      let left = pending;
      setPreparing(left);
      try {
        for (let round = 0; round < 60 && left > 0 && !cancelled; round += 1) {
          const answer = (await readJson(`${INSIGHTS_PATH}/refresh`, {
            method: "POST",
          })) as { projected?: unknown; pending?: unknown };
          left = typeof answer.pending === "number" ? answer.pending : 0;
          setPreparing(left);
          if (answer.projected === 0) break;
        }
        if (!cancelled) await load(query);
      } catch {
        if (!cancelled)
          notify({
            id: "insights-refresh",
            tone: "error",
            title: "Some new calls aren’t counted yet",
            message: "The figures show the calls prepared so far.",
          });
      } finally {
        if (!cancelled) setPreparing(null);
      }
    })();
    return () => {
      cancelled = true;
      setPreparing(null);
    };
  }, [pending, fixture, load, query]);

  const go = useCallback(
    (next: Partial<Filters>) => {
      const merged = { ...filters, ...next };
      setFilters(merged);
      if (!fixture)
        window.history.replaceState(
          null,
          "",
          `${pathname}${addressQuery(merged, section)}`,
        );
    },
    [filters, fixture, pathname, section],
  );

  async function more() {
    if (!calls || calls.nextOffset === null || moreLoading) return;
    const id = sequence.current;
    setMoreLoading(true);
    try {
      const page = parseCallPage(
        await readJson(
          `${INSIGHTS_PATH}/calls${queryOf(filters, { offset: String(calls.nextOffset) })}`,
        ),
      );
      // A filter changed meanwhile: these rows belong to the old list.
      if (id !== sequence.current) return;
      setCalls({ ...page, items: [...calls.items, ...page.items] });
    } catch {
      notify({
        id: "insights-more",
        tone: "error",
        title: "More calls couldn’t load",
        action: { label: "Try again", run: () => void more() },
      });
    } finally {
      setMoreLoading(false);
    }
  }

  if (read.status === "denied")
    return (
      <div className={styles.page}>
        <PageHeader title="Insights" />
        <Panel title="Owners and admins only">
          <Empty
            icon={Lock}
            title="Only owners and admins of this organisation can see Insights"
            text="Ask an owner of the organisation if you need the team’s figures. Your own calls and Coaching stay in Calls and Coaching."
          />
        </Panel>
      </div>
    );
  if (read.status === "signed-out")
    return (
      <div className={styles.page}>
        <PageHeader title="Insights" />
        <Panel title="Sign in">
          <Empty
            icon={Lock}
            title="Sign in to see your organisation’s calls"
            action={{ href: "/login", label: "Sign in" }}
          />
        </Panel>
      </div>
    );
  if (read.status !== "ready")
    return (
      <InsightsSkeleton
        failed={read.status === "error"}
        onRetry={() => void load(query)}
      />
    );

  const data = read.value;
  const synthetic = data.synthetic;
  const linkFor = synthetic ? null : callHref;
  const people = data.facets.people;
  const teams = data.facets.teams;
  const personName = people.find((item) => item.key === filters.person)?.name;
  const teamName = teams.find((item) => item.key === filters.team)?.name;
  const empty = data.coverage.calls && data.totals.calls === 0;

  return (
    <div className={styles.page} data-updating={updating ? "" : undefined}>
      <PageHeader
        title="Insights"
        actions={
          empty ? null : (
            <Segmented<View>
              label="View"
              items={VIEWS.map((item) => ({
                key: item.key,
                label: item.label,
              }))}
              value={section}
              onChange={setSection}
            />
          )
        }
        context={[
          RANGE_TEXT[filters.range],
          data.coverage.calls
            ? `${count(data.totals.calls)} calls · ${count(data.totals.people)} people`
            : "Call count unavailable",
          synthetic ? (
            <span key="synthetic" className={styles.fixtureBadge}>
              Synthetic sandbox data
            </span>
          ) : null,
        ]}
      />
      <FilterBar
        filters={filters}
        data={data}
        onChange={go}
        personName={personName}
        teamName={teamName}
      />
      {preparing !== null && preparing > 0 ? (
        <p className={styles.preparing} role="status">
          <RotateCw size={13} aria-hidden="true" className={styles.spin} />
          Preparing {count(preparing)} new calls for these figures…
        </p>
      ) : null}
      {empty ? (
        <Panel title="No calls here yet">
          <Empty
            icon={BarChart3}
            title={
              activeFilterCount(filters)
                ? "No calls match these filters"
                : "No analysed calls in this period"
            }
            text="Insights add up every analysed call in the organisation: who made it, how it ended, and how each skill showed up."
            action={
              activeFilterCount(filters) || filters.range !== "all"
                ? {
                    onClick: () =>
                      go({
                        range: "all",
                        person: null,
                        team: null,
                        outcome: null,
                        language: null,
                      }),
                    label: "Show all calls",
                  }
                : undefined
            }
          />
        </Panel>
      ) : (
        <Sections
          section={section}
          data={data}
          go={go}
          linkFor={linkFor}
          calls={calls}
          more={more}
          moreLoading={moreLoading}
          onCalls={(outcome) => {
            if (outcome) go({ outcome });
            setSection("calls");
          }}
        />
      )}
      <p className={styles.footnote}>
        Added up from each call’s report
        {synthetic ? ", in the fictional sandbox" : ""}. A guide for coaching,
        not an official score.
      </p>
    </div>
  );
}

function FilterBar({
  filters,
  data,
  onChange,
  personName,
  teamName,
}: {
  filters: Filters;
  data: Insights;
  onChange: (next: Partial<Filters>) => void;
  personName?: string;
  teamName?: string;
}) {
  const active = activeFilterCount(filters);
  return (
    <div className={styles.filters} role="group" aria-label="Filters">
      <Segmented
        label="Period"
        items={RANGES.map((item) => ({ key: item.key, label: item.label }))}
        value={filters.range}
        onChange={(range) => onChange({ range })}
      />
      <details className={styles.filterDetails}>
        <summary>
          <SlidersHorizontal size={16} aria-hidden="true" />
          Filter{active ? ` · ${active}` : ""}
        </summary>
        <div className={styles.filterFields}>
          <select
            className={styles.select}
            aria-label="Person"
            value={filters.person ?? ""}
            onChange={(event) =>
              onChange({ person: event.target.value || null })
            }
          >
            <option value="">Everyone</option>
            {filters.person && !personName ? (
              <option value={filters.person}>Selected person</option>
            ) : null}
            {data.facets.people.map((person) => (
              <option key={person.key} value={person.key}>
                {person.name}
              </option>
            ))}
          </select>
          {data.facets.teams.length ? (
            <select
              className={styles.select}
              aria-label="Team"
              value={filters.team ?? ""}
              onChange={(event) =>
                onChange({ team: event.target.value || null })
              }
            >
              <option value="">All teams</option>
              {filters.team && !teamName ? (
                <option value={filters.team}>Selected team</option>
              ) : null}
              {data.facets.teams.map((team) => (
                <option key={team.key} value={team.key}>
                  {team.name}
                </option>
              ))}
            </select>
          ) : null}
          <select
            className={styles.select}
            aria-label="Outcome"
            value={filters.outcome ?? ""}
            onChange={(event) =>
              onChange({
                outcome: (event.target.value || null) as Filters["outcome"],
              })
            }
          >
            <option value="">Any outcome</option>
            {OUTCOMES.map((outcome) => (
              <option key={outcome.key} value={outcome.key}>
                {outcome.label}
              </option>
            ))}
          </select>
          {data.facets.languages.length > 1 || filters.language ? (
            <select
              className={styles.select}
              aria-label="Language"
              value={filters.language ?? ""}
              onChange={(event) =>
                onChange({ language: event.target.value || null })
              }
            >
              <option value="">Any language</option>
              {data.facets.languages.map((language) => (
                <option key={language.key} value={language.key}>
                  {language.label}
                </option>
              ))}
            </select>
          ) : null}
          {active ? (
            <Button
              variant="ghost"
              onClick={() =>
                onChange({
                  person: null,
                  team: null,
                  outcome: null,
                  language: null,
                })
              }
            >
              <X size={13} aria-hidden="true" /> Clear {active}
            </Button>
          ) : null}
        </div>
      </details>
    </div>
  );
}

function shareDelta(now: number | null, before: number | null): ReactNode {
  if (now === null || before === null) return null;
  const points = Math.round((now - before) * 100);
  return (
    <span className={styles.points}>
      {points === 0 ? "±0" : points > 0 ? `+${points}` : `${points}`} pts
    </span>
  );
}

function Sections({
  section,
  data,
  go,
  linkFor,
  calls,
  more,
  moreLoading,
  onCalls,
}: {
  section: View;
  onCalls: (outcome?: Filters["outcome"]) => void;
  data: Insights;
  go: (next: Partial<Filters>) => void;
  linkFor: ((key: string) => string) | null;
  calls: CallPage | null;
  more: () => void;
  moreLoading: boolean;
}) {
  const { totals, previous } = data;
  const [grouping, setGrouping] = useState<"people" | "teams">("people");
  const attention = useMemo(
    () =>
      [...data.skills]
        .filter((skill) => skill.needsAttention > 0)
        .sort((a, b) => b.needsAttention - a.needsAttention)
        .slice(0, 6)
        .map((skill) => ({
          key: skill.id,
          label: skill.label,
          value: skill.needsAttention,
        })),
    [data.skills],
  );
  const heatGroups = (grouping === "teams" ? data.teams : data.people).slice(
    0,
    12,
  );
  const movers = data.people
    .filter(
      (person) => person.needsAttentionChange !== null && person.calls >= 3,
    )
    .sort(
      (a, b) => (a.needsAttentionChange ?? 0) - (b.needsAttentionChange ?? 0),
    );
  const improving = movers
    .filter((person) => (person.needsAttentionChange ?? 0) < -0.005)
    .slice(0, 4);
  const slipping = movers
    .filter((person) => (person.needsAttentionChange ?? 0) > 0.005)
    .reverse()
    .slice(0, 4);

  return (
    <>
      {section !== "overview" ? (
        <Tiles label="This period">
          <Kpi
            label="Calls analysed"
            value={count(totals.calls)}
            delta={
              previous ? (
                <Delta value={totals.calls} previous={previous.calls} />
              ) : null
            }
            note={`${minutes(totals.minutes)} · ${count(totals.people)} people`}
          />
          <Kpi
            label="Agreed a next step"
            value={percent(totals.nextStepShare)}
            delta={shareDelta(
              totals.nextStepShare,
              previous?.nextStepShare ?? null,
            )}
            note={`${count(totals.nextStep)} calls`}
          />
          <Kpi
            label="Won"
            value={count(totals.won)}
            delta={
              previous ? (
                <Delta value={totals.won} previous={previous.won} />
              ) : null
            }
            note={`${percent(totals.winShare)} of calls`}
          />
          <Kpi
            label="Skills needing attention"
            value={percent(totals.needsAttentionShare)}
            delta={shareDelta(
              totals.needsAttentionShare,
              previous?.needsAttentionShare ?? null,
            )}
            note="Lower is better"
          />
        </Tiles>
      ) : null}

      {section === "overview" ? (
        <>
          <OutcomeStory data={data} onCalls={onCalls} />
          <Panel
            title="Calls over time"
            sub={`By ${data.window.unit}`}
            className={styles.wide}
          >
            <div className={styles.inset}>
              <TrendColumns
                points={data.trend}
                unit={data.window.unit}
                window={data.window}
              />
            </div>
          </Panel>

          <div className={styles.grid}>
            <Panel title="Skills across the calls" sub="Share observed">
              <div className={styles.inset}>
                <SkillSplit skills={data.skills} />
              </div>
            </Panel>
          </div>

          <div className={styles.grid}>
            <Panel title="Objections" sub="What prospects raised">
              <div className={styles.inset}>
                {data.objections.length ? (
                  <BarList
                    label="Objections"
                    rows={data.objections.map((row) => ({
                      key: row.kind,
                      label: row.label,
                      value: row.calls,
                      note: `${percent(row.calls ? row.won / row.calls : null)} won`,
                    }))}
                  />
                ) : (
                  <p className={styles.muted}>
                    No objections recorded in these calls.
                  </p>
                )}
              </div>
            </Panel>
            <Panel
              title={
                data.mistakes.length ? "Common mistakes" : "Skills needing work"
              }
              sub={
                data.mistakes.length
                  ? "Main one per call"
                  : "Calls needing work"
              }
            >
              <div className={styles.inset}>
                {data.mistakes.length ? (
                  <BarList
                    label="Common mistakes"
                    rows={data.mistakes.map((row) => ({
                      key: row.kind,
                      label: row.label,
                      value: row.calls,
                    }))}
                  />
                ) : attention.length ? (
                  <BarList label="Skills needing attention" rows={attention} />
                ) : (
                  <p className={styles.muted}>
                    No skill needed attention in these calls.
                  </p>
                )}
              </div>
            </Panel>
          </div>
        </>
      ) : null}

      {section === "people" ? (
        <>
          <Panel
            title={data.teams.length ? "People and teams" : "People"}
            sub={`${count(data.people.length)} with calls`}
            className={styles.wide}
          >
            <PeopleTable
              groups={data.people}
              teams={data.teams}
              onPerson={(key) => go({ person: key })}
              onTeam={(key) => go({ team: key })}
              profiles={!data.synthetic}
            />
          </Panel>

          <Panel
            title="Skills by person"
            sub="Where to coach"
            className={styles.wide}
          >
            <div className={styles.inset}>
              <SkillGaps
                groups={data.people}
                onSelect={(key) => go({ person: key })}
              />
              <details className={styles.gridDetails}>
                <summary>Every skill, person by person</summary>
                <div className={styles.heatBar}>
                  {data.teams.length ? (
                    <Segmented
                      label="Group by"
                      items={[
                        { key: "people", label: "People" },
                        { key: "teams", label: "Teams" },
                      ]}
                      value={grouping}
                      onChange={setGrouping}
                    />
                  ) : null}
                  <span className={styles.caption}>
                    Amber marks a skill that needed work.
                  </span>
                </div>
                <SkillHeatmap
                  groups={heatGroups}
                  label={grouping === "teams" ? "Team" : "Person"}
                  onSelect={(key) =>
                    go(grouping === "teams" ? { team: key } : { person: key })
                  }
                />
              </details>
            </div>
          </Panel>

          <div className={styles.grid}>
            <Panel
              title="Talk share"
              sub={
                totals.talkShare === null
                  ? undefined
                  : `${totals.talkShare}% on average`
              }
            >
              <div className={styles.inset}>
                {totals.talkCalls ? (
                  <>
                    <TalkBands bands={data.talk} />
                    <p className={styles.caption}>
                      {count(totals.talkCalls)} calls with a confirmed seller ·
                      good calls sit at{" "}
                      <span className={styles.nowrap}>40–60%</span>
                    </p>
                  </>
                ) : (
                  <p className={styles.muted}>
                    Talk share appears once reps confirm who the seller is on
                    their calls.
                  </p>
                )}
              </div>
            </Panel>
            <Panel title="Coaching progress" sub="Lower is better">
              <div className={styles.inset}>
                {data.trend.some(
                  (point) => (point.needsAttentionShare ?? 0) > 0,
                ) ? (
                  <ShareLine
                    points={data.trend.map((point) => ({
                      at: point.at,
                      share: point.needsAttentionShare,
                    }))}
                    unit={data.window.unit}
                    label="needing attention"
                  />
                ) : (
                  <p className={styles.bigStat}>
                    <b>0%</b>
                    <span>of skill moments needed work in this period</span>
                  </p>
                )}
                {improving.length || slipping.length ? (
                  <>
                    <div className={styles.movers}>
                      <MoverList
                        title="Improving"
                        tone="better"
                        people={improving}
                        onSelect={(key) => go({ person: key })}
                      />
                      <MoverList
                        title="Slipping"
                        tone="worse"
                        people={slipping}
                        onSelect={(key) => go({ person: key })}
                      />
                    </div>
                    <p className={styles.caption}>
                      Second half of the period against the first
                    </p>
                  </>
                ) : (
                  <p className={styles.muted}>
                    Who is improving shows once people have three or more calls.
                  </p>
                )}
              </div>
            </Panel>
          </div>
        </>
      ) : null}

      {section === "calls" ? (
        <>
          <div className={styles.grid}>
            <Panel title="Strongest calls" sub="Fewest gaps">
              <CallList rows={data.strongest} linkFor={linkFor} />
            </Panel>
            <Panel title="Calls to review" sub="Most gaps">
              <CallList rows={data.weakest} linkFor={linkFor} />
            </Panel>
          </div>

          <Panel
            title="All calls"
            sub={calls ? `${count(calls.total)} in this view` : undefined}
            className={styles.wide}
          >
            {calls ? (
              <CallsTable
                page={calls}
                linkFor={linkFor}
                more={more}
                moreLoading={moreLoading}
              />
            ) : (
              <p className={styles.mutedInset}>
                The call list couldn’t load. Change a filter or reload to try
                again.
              </p>
            )}
          </Panel>
        </>
      ) : null}
    </>
  );
}

function changeText(change: number | null) {
  if (change === null) return "—";
  const points = Math.round(change * 100);
  const size = Math.abs(points) === 1 ? "1 pt" : `${Math.abs(points)} pts`;
  return points === 0
    ? "steady"
    : points < 0
      ? `${size} better`
      : `${size} worse`;
}

/** A person's profile page (Organisation → people), for real members only. */
function ProfileLink({ group }: { group: Group }) {
  if (!group.key) return null;
  return (
    <Link
      href={`/organisation/people/${encodeURIComponent(group.key)}`}
      className={styles.profileLink}
      aria-label={`Open ${group.name}’s profile`}
      title="Open profile"
    >
      <ArrowUpRight size={13} aria-hidden="true" />
    </Link>
  );
}

/** People lists longer than this get a search field and a count line. */
const SEARCH_FROM = 8;

/** Two letters for a person's round mark ("Fictional seller 4" -> "FS"). */
function initials(name: string): string {
  const words = name
    .trim()
    .split(/\s+/)
    .filter((word) => /\p{L}/u.test(word));
  return (
    words
      .slice(0, 2)
      .map((word) => (word.match(/\p{L}/u)?.[0] ?? "").toLocaleUpperCase())
      .join("") || "?"
  );
}

function PeopleTable({
  groups,
  teams,
  onPerson,
  onTeam,
  profiles,
}: {
  groups: Group[];
  teams: Group[];
  onPerson: (key: string) => void;
  onTeam: (key: string) => void;
  /** Real organisations: each name also opens the person's profile. */
  profiles: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const peopleId = useId();
  const teamKey = (name: string | null) =>
    teams.find((team) => team.name === name)?.key ?? null;
  const query = search.trim().toLocaleLowerCase();
  // Search the full returned list; clearing restores the 50/all choice.
  const rows = query
    ? groups.filter((group) => group.name.toLocaleLowerCase().includes(query))
    : expanded
      ? groups
      : groups.slice(0, 50);
  // A short team reads at a glance: search and the count line only earn
  // their place on a longer list (owner bug #80: "so much text").
  const long = groups.length > SEARCH_FROM;
  return (
    <>
      {long ? (
        <div className={styles.peopleSearch}>
          <label className={styles.peopleSearchField}>
            <Search size={17} aria-hidden="true" />
            <span className={styles.srOnly}>Search people</span>
            <input
              ref={searchInput}
              type="search"
              placeholder="Search people"
              value={search}
              aria-describedby={`${peopleId}-count`}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <button
            type="button"
            className={styles.clearSearch}
            disabled={search.length === 0}
            onClick={() => {
              setSearch("");
              searchInput.current?.focus();
            }}
          >
            <X size={16} aria-hidden="true" />
            <span className={styles.srOnly}>Clear search</span>
          </button>
        </div>
      ) : null}
      <div id={peopleId}>
        {query && rows.length === 0 ? (
          <p className={styles.mutedInset}>No people match this name.</p>
        ) : (
          <Table
            label="People"
            cards={rows.map((group) => (
              <Card key={group.key ?? group.name}>
                <div className={styles.personRow}>
                  <span className={styles.initials} aria-hidden="true">
                    {initials(group.name)}
                  </span>
                  <span className={styles.personMain}>
                    <span className={styles.personName}>
                      <button
                        type="button"
                        className={`${styles.linkish} ${styles.peopleButton}`}
                        onClick={() => group.key && onPerson(group.key)}
                      >
                        {group.name}
                      </button>
                      {profiles ? <ProfileLink group={group} /> : null}
                    </span>
                    <span className={styles.personMeta}>
                      {count(group.calls)} calls · {count(group.won)} won
                      {group.team ? ` · ${group.team}` : ""}
                      {group.needsAttentionChange !== null ? (
                        <span
                          className={styles.personTrend}
                          data-trend={trendTone(group.needsAttentionChange)}
                        >
                          {changeText(group.needsAttentionChange)}
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <span className={styles.personFigure}>
                    <b>
                      {percent(
                        group.calls ? group.nextStep / group.calls : null,
                      )}
                    </b>
                    <small>next step</small>
                  </span>
                </div>
              </Card>
            ))}
          >
            <thead>
              <tr>
                <th>Person</th>
                {teams.length ? <th>Team</th> : null}
                <th className={styles.num}>Calls</th>
                <th className={styles.num}>Time</th>
                <th className={styles.num}>Next step</th>
                <th className={styles.num}>Won</th>
                <th className={styles.num}>Talk</th>
                <th>Skills trend</th>
                <th>Last call</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((group) => (
                <tr key={group.key ?? group.name}>
                  <td>
                    <button
                      type="button"
                      className={`${styles.linkish} ${styles.peopleButton}`}
                      onClick={() => group.key && onPerson(group.key)}
                    >
                      {group.name}
                    </button>
                    {profiles ? <ProfileLink group={group} /> : null}
                  </td>
                  {teams.length ? (
                    <td>
                      {group.team ? (
                        <button
                          type="button"
                          className={`${styles.linkish} ${styles.peopleButton}`}
                          onClick={() => {
                            const key = teamKey(group.team);
                            if (key) onTeam(key);
                          }}
                        >
                          {group.team}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  ) : null}
                  <td className={styles.num}>{count(group.calls)}</td>
                  <td className={styles.num}>{minutes(group.minutes)}</td>
                  <td className={styles.num}>
                    {percent(group.calls ? group.nextStep / group.calls : null)}
                  </td>
                  <td className={styles.num}>{count(group.won)}</td>
                  <td className={styles.num}>
                    {group.talkShare === null ? "—" : `${group.talkShare}%`}
                  </td>
                  <td data-trend={trendTone(group.needsAttentionChange)}>
                    {changeText(group.needsAttentionChange)}
                  </td>
                  <td>{dateLabel(group.lastAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
      {long ? (
        <div className={styles.peopleControls}>
          <p id={`${peopleId}-count`} className={styles.caption} role="status">
            {query ? "Matches:" : "Showing"} {count(rows.length)} of{" "}
            {count(groups.length)} people
          </p>
          {!query && groups.length > 50 ? (
            <Button
              aria-expanded={expanded}
              aria-controls={peopleId}
              onClick={(event) => {
                if (expanded) event.currentTarget.focus();
                setExpanded(!expanded);
              }}
            >
              {expanded ? "Show fewer" : "Show more"}
            </Button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

const trendTone = (change: number | null) =>
  change === null
    ? undefined
    : change < -0.005
      ? "better"
      : change > 0.005
        ? "worse"
        : undefined;

function MoverList({
  title,
  tone,
  people,
  onSelect,
}: {
  title: string;
  tone: "better" | "worse";
  people: Group[];
  onSelect: (key: string) => void;
}) {
  const Icon = tone === "better" ? TrendingUp : TrendingDown;
  return (
    <div className={styles.moverList}>
      <h3 data-trend={tone}>
        <Icon size={15} aria-hidden="true" />
        {title}
      </h3>
      {people.length ? (
        <ul>
          {people.map((person) => (
            <li key={person.key ?? person.name}>
              <button
                type="button"
                className={styles.linkish}
                onClick={() => person.key && onSelect(person.key)}
              >
                {person.name}
              </button>
              <span data-trend={trendTone(person.needsAttentionChange)}>
                {changeText(person.needsAttentionChange)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>No one yet</p>
      )}
    </div>
  );
}

function CallList({
  rows,
  linkFor,
}: {
  rows: CallRow[];
  linkFor: ((key: string) => string) | null;
}) {
  if (!rows.length)
    return (
      <p className={styles.mutedInset}>
        No calls with all eight skills read yet.
      </p>
    );
  return (
    <ul className={styles.callList}>
      {rows.map((row) => (
        <li key={row.key}>
          <span className={styles.callMain}>
            {linkFor ? (
              <Link href={linkFor(row.key)} className={styles.callTitle}>
                {row.person}
              </Link>
            ) : (
              <span className={styles.callTitle}>{row.person}</span>
            )}
            <span className={styles.callMeta}>
              {dateLabel(row.at)} · {outcomeLabel(row.outcome)} ·{" "}
              {duration(row.durationMs)}
            </span>
          </span>
          <SkillDots skills={row.skills} />
        </li>
      ))}
    </ul>
  );
}

function CallsTable({
  page,
  linkFor,
  more,
  moreLoading,
}: {
  page: CallPage;
  linkFor: ((key: string) => string) | null;
  more: () => void;
  moreLoading: boolean;
}) {
  return (
    <>
      <Table
        label="All calls"
        cards={page.items.map((row) => (
          <Card key={row.key}>
            <div className={styles.cardHead}>
              {linkFor ? (
                <Link href={linkFor(row.key)} className={styles.linkish}>
                  {row.person}
                </Link>
              ) : (
                <span>{row.person}</span>
              )}
              <span>{dateLabel(row.at)}</span>
            </div>
            <div className={styles.cardMeta}>
              <span>{outcomeLabel(row.outcome)}</span>
              <span>{duration(row.durationMs)}</span>
              <SkillDots skills={row.skills} />
            </div>
          </Card>
        ))}
      >
        <thead>
          <tr>
            <th>When</th>
            <th>Person</th>
            <th>Outcome</th>
            <th className={styles.num}>Length</th>
            <th className={styles.num}>Talk</th>
            <th>Skills</th>
            <th>Objections</th>
          </tr>
        </thead>
        <tbody>
          {page.items.map((row) => (
            <tr key={row.key}>
              <td>{dateLabel(row.at, true)}</td>
              <td>
                {linkFor ? (
                  <Link href={linkFor(row.key)} className={styles.linkish}>
                    {row.person}
                  </Link>
                ) : (
                  row.person
                )}
                {row.team ? (
                  <span className={styles.sub}>{row.team}</span>
                ) : null}
              </td>
              <td>{outcomeLabel(row.outcome)}</td>
              <td className={styles.num}>{duration(row.durationMs)}</td>
              <td className={styles.num}>
                {row.talkShare === null ? "—" : `${row.talkShare}%`}
              </td>
              <td>
                <SkillDots skills={row.skills} />
              </td>
              <td className={styles.objections}>
                {row.objections.length
                  ? row.objections
                      .map((item) => item.replace(/_/g, " "))
                      .join(", ")
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {page.nextOffset !== null ? (
        <div className={styles.more}>
          <Button onClick={more} disabled={moreLoading}>
            {moreLoading
              ? "Loading…"
              : `Show more (${count(page.total - page.items.length)} left)`}
          </Button>
        </div>
      ) : null}
    </>
  );
}

export { InsightsSkeleton };
