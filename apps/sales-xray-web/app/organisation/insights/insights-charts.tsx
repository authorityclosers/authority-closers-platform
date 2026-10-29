"use client";

/**
 * The company view's charts: small, labelled, one hue for magnitude (teal),
 * the warning hue only for "needs attention". Every value a hover shows is
 * also in a label, a list or a table; nothing is colour alone.
 */
import {
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  SKILLS,
  bucketLabel,
  count,
  dateLabel,
  observedShare,
  percent,
  type Group,
  type SkillTotal,
  type TrendPoint,
} from "./insights-data";
import styles from "./insights.module.css";

/** A zero-based axis with at most four round steps. */
export function ticksFor(peak: number): number[] {
  const top = Math.max(1, peak);
  const raw = top / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10]
      .map((factor) => factor * power)
      .find((size) => top / size <= 4) ?? 10 * power;
  const max = Math.ceil(top / step) * step;
  return Array.from({ length: Math.round(max / step) + 1 }, (_, index) =>
    Math.round(index * step),
  );
}

const plural = (value: number, word: string) =>
  `${count(value)} ${word}${value === 1 ? "" : "s"}`;

/**
 * Calls per week or month: each column is the period's calls, its darker
 * lower part the calls the reports read as won. Hover, focus or drag a
 * finger across to read a period.
 */
export function TrendColumns({
  points: allPoints,
  unit,
  window,
}: {
  window?: { from: string | null; to: string | null };
  points: TrendPoint[];
  unit: "week" | "month";
}) {
  const [focus, setFocus] = useState<number | null>(null);
  const [requestedOffset, setOffset] = useState(0);
  const offset = Math.min(
    requestedOffset,
    Math.max(0, Math.floor((allPoints.length - 1) / 7) * 7),
  );
  const points = allPoints.slice(offset, offset + 7);
  const ticks = ticksFor(Math.max(0, ...allPoints.map((point) => point.calls)));
  const max = ticks[ticks.length - 1] || 1;
  const shown = focus === null ? null : points[focus];
  const total = points.reduce((sum, point) => sum + point.calls, 0);
  const won = points.reduce((sum, point) => sum + point.won, 0);
  const every = Math.max(1, Math.ceil(points.length / 6));
  const scrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" || !points.length) return;
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const at = Math.floor(
      ((event.clientX - box.left) / box.width) * points.length,
    );
    setFocus(Math.min(points.length - 1, Math.max(0, at)));
  };
  return (
    <figure className={styles.chart} onMouseLeave={() => setFocus(null)}>
      <figcaption className={styles.readout} aria-live="polite">
        {shown ? (
          <>
            <b>{bucketLabel(shown.at, unit)}</b>
            <span>
              {plural(shown.calls, "call")} · {count(shown.won)} won ·{" "}
              {percent(shown.calls ? shown.nextStep / shown.calls : null)} with
              a next step
            </span>
          </>
        ) : (
          <>
            <b>{plural(total, "call")}</b>
            <span>
              {count(won)} won · by {unit}
            </span>
          </>
        )}
        <span className={styles.legend} aria-hidden="true">
          <span>
            <i data-key="won" /> Won
          </span>
          <span>
            <i data-key="calls" /> Other calls
          </span>
        </span>
      </figcaption>
      <div className={styles.plot}>
        <ol className={styles.axis} aria-hidden="true">
          {[...ticks].reverse().map((tick) => (
            <li key={tick}>{count(tick)}</li>
          ))}
        </ol>
        <div
          className={styles.columns}
          style={{ "--rows": ticks.length - 1 } as CSSProperties}
          onPointerDown={scrub}
          onPointerMove={scrub}
        >
          {points.map((point, index) => (
            <button
              key={point.at}
              type="button"
              className={styles.column}
              data-focus={focus === index ? "" : undefined}
              aria-label={`${bucketLabel(point.at, unit)}: ${plural(point.calls, "call")}, ${count(point.won)} won`}
              onMouseEnter={() => setFocus(index)}
              onFocus={() => setFocus(index)}
              onBlur={() => setFocus(null)}
            >
              <span
                className={styles.stack}
                style={{ height: `${(point.calls / max) * 100}%` }}
              >
                <i
                  data-key="calls"
                  style={{ flexGrow: Math.max(0, point.calls - point.won) }}
                />
                <i data-key="won" style={{ flexGrow: point.won }} />
              </span>
            </button>
          ))}
        </div>
        <ol className={styles.dates} aria-hidden="true">
          {points.map((point, index) => (
            <li key={point.at}>
              {index % every === 0 ? bucketLabel(point.at, unit) : ""}
            </li>
          ))}
        </ol>
      </div>
      {window ? (
        <p className={styles.caption}>
          Window: {window.from ? dateLabel(window.from) : "—"} –{" "}
          {window.to ? dateLabel(window.to) : "—"}. First and last {unit}s may
          be partial.
        </p>
      ) : null}
      {allPoints.length > 7 ? (
        <div className={styles.chartPaging}>
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => {
              setOffset(Math.max(0, offset - 7));
              setFocus(null);
            }}
          >
            Earlier
          </button>
          <span>
            {offset + 1}–{Math.min(offset + 7, allPoints.length)} of{" "}
            {allPoints.length} {unit}s
          </span>
          <button
            type="button"
            disabled={offset + 7 >= allPoints.length}
            onClick={() => {
              setOffset(offset + 7);
              setFocus(null);
            }}
          >
            Later
          </button>
        </div>
      ) : null}
    </figure>
  );
}

/**
 * One share over time as a 2 px line (the share of skill moments needing
 * attention). Lower is better; the scale starts at zero.
 */
export function ShareLine({
  points,
  unit,
  label,
}: {
  points: { at: string; share: number | null }[];
  unit: "week" | "month";
  label: string;
}) {
  const [focus, setFocus] = useState<number | null>(null);
  const known = points.filter((point) => point.share !== null);
  if (known.length < 2) return null;
  const peak = Math.max(0.05, ...known.map((point) => point.share ?? 0));
  const top = Math.ceil(peak * 20) / 20;
  const width = 100;
  const x = (index: number) =>
    points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = (share: number) => 100 - (share / top) * 100;
  const path = points
    .map((point, index) =>
      point.share === null
        ? null
        : `${x(index).toFixed(2)},${y(point.share).toFixed(2)}`,
    )
    .filter(Boolean)
    .join(" ");
  const shown = focus === null ? null : points[focus];
  const last = known[known.length - 1];
  return (
    <figure className={styles.chart} onMouseLeave={() => setFocus(null)}>
      <figcaption className={styles.readout} aria-live="polite">
        {shown ? (
          <>
            <b>{bucketLabel(shown.at, unit)}</b>
            <span>
              {percent(shown.share)} {label}
            </span>
          </>
        ) : (
          <>
            <b>{percent(last.share)}</b>
            <span>
              {label}, latest {unit}
            </span>
          </>
        )}
      </figcaption>
      <div className={styles.linePlot}>
        <ol className={styles.axis} aria-hidden="true">
          <li>{percent(top)}</li>
          <li>{percent(top / 2)}</li>
          <li>0%</li>
        </ol>
        <div className={styles.lineArea}>
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className={styles.lineSvg}
            role="img"
            aria-label={`${label} by ${unit}`}
          >
            <polyline points={path} vectorEffect="non-scaling-stroke" />
          </svg>
          <div className={styles.lineHits}>
            {points.map((point, index) => (
              <button
                key={point.at}
                type="button"
                data-focus={focus === index ? "" : undefined}
                aria-label={`${bucketLabel(point.at, unit)}: ${percent(point.share)}`}
                onMouseEnter={() => setFocus(index)}
                onFocus={() => setFocus(index)}
                onBlur={() => setFocus(null)}
              >
                {point.share !== null && focus === index ? (
                  <i style={{ top: `${y(point.share)}%` }} />
                ) : null}
              </button>
            ))}
          </div>
        </div>
      </div>
    </figure>
  );
}

/** Horizontal bars on one scale, the value at each bar's end. */
export function BarList({
  rows,
  label,
  onSelect,
}: {
  rows: { key: string; label: string; value: number; note?: string }[];
  label: string;
  onSelect?: (key: string) => void;
}) {
  const [requestedOffset, setOffset] = useState(0);
  const offset = Math.min(
    requestedOffset,
    Math.max(0, Math.floor((rows.length - 1) / 7) * 7),
  );
  const ordered = [...rows].sort((a, b) => b.value - a.value);
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <>
      <ul className={styles.barList} aria-label={label}>
        {ordered.slice(offset, offset + 7).map((row) => {
          const body = (
            <>
              <span className={styles.barLabel}>{row.label}</span>
              <span className={styles.barTrack} aria-hidden="true">
                <i style={{ width: `${(row.value / max) * 100}%` }} />
              </span>
              <span className={styles.barValue}>
                {count(row.value)} calls
                {row.note ? <small>{row.note}</small> : null}
              </span>
            </>
          );
          return (
            <li key={row.key}>
              {onSelect ? (
                <button
                  type="button"
                  className={styles.barRow}
                  onClick={() => onSelect(row.key)}
                >
                  {body}
                </button>
              ) : (
                <span className={styles.barRow}>{body}</span>
              )}
            </li>
          );
        })}
      </ul>
      {rows.length > 7 ? (
        <div className={styles.chartPaging}>
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 7))}
          >
            Previous
          </button>
          <span>
            {offset + 1}–{Math.min(offset + 7, rows.length)} of {rows.length}
          </span>
          <button
            type="button"
            disabled={offset + 7 >= rows.length}
            onClick={() => setOffset(offset + 7)}
          >
            Next
          </button>
        </div>
      ) : null}
    </>
  );
}

/** Calls → with an agreed next step → won, each as a share of all calls. */
export function Funnel({
  calls,
  nextStep,
  won,
}: {
  calls: number;
  nextStep: number;
  won: number;
}) {
  const steps = [
    { key: "calls", label: "Calls analysed", value: calls },
    { key: "next", label: "Agreed a next step", value: nextStep },
    { key: "won", label: "Won", value: won },
  ];
  return (
    <ol className={styles.funnel} aria-label="From calls to won">
      {steps.map((step) => (
        <li key={step.key}>
          <span className={styles.funnelLabel}>{step.label}</span>
          <span className={styles.funnelTrack} aria-hidden="true">
            <i
              data-key={step.key}
              style={{
                width: `${calls ? Math.max(1, (step.value / calls) * 100) : 0}%`,
              }}
            />
          </span>
          <span className={styles.funnelValue}>
            {count(step.value)}
            <small>{percent(calls ? step.value / calls : null)}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** A skill's observed share (strong included) and its parts. */
function skillShare(skill: SkillTotal) {
  const observed = skill.strong + skill.observed;
  const whole = observed + skill.needsAttention + skill.unknown;
  return { observed, whole, share: whole ? observed / whole : null };
}

/**
 * Each skill across the calls (owner bug #79, 29 Oct 2026: "far better UX
 * for the presentation of all this data"). The answer first: the strongest
 * skill and the one to coach next. Then all eight at once, best first, each a
 * name, its observed share in large figures and one bar split into observed,
 * needs attention and not enough evidence. No paging, no legend to decode:
 * the parts are named under the list and in each row's label.
 */
export function SkillSplit({ skills }: { skills: SkillTotal[] }) {
  const ranked = skills
    .map((skill) => ({ skill, ...skillShare(skill) }))
    .sort((a, b) => (b.share ?? -1) - (a.share ?? -1));
  const read = ranked.filter((row) => row.share !== null);
  const best = read[0];
  const coach = [...read].sort(
    (a, b) =>
      b.skill.needsAttention - a.skill.needsAttention ||
      (a.share ?? 0) - (b.share ?? 0),
  )[0];
  return (
    <>
      {best && coach && best.skill.id !== coach.skill.id ? (
        <div className={styles.skillAnswer}>
          <p data-tone="good">
            <small>Strongest</small>
            <b>{best.skill.label}</b>
            <span>{percent(best.share)} observed</span>
          </p>
          <p data-tone="warn">
            <small>Coach next</small>
            <b>{coach.skill.label}</b>
            <span>
              {coach.skill.needsAttention
                ? `${plural(coach.skill.needsAttention, "call")} needed work`
                : `${percent(coach.share)} observed`}
            </span>
          </p>
        </div>
      ) : null}
      <ul className={styles.skillList} aria-label="Skills across the calls">
        {ranked.map(({ skill, observed, share }) => (
          <li
            key={skill.id}
            aria-label={`${skill.label}: ${percent(share)} observed, ${count(skill.needsAttention)} calls need attention, ${count(skill.unknown)} without enough evidence`}
          >
            <span className={styles.skillName}>{skill.label}</span>
            <span className={styles.skillValue}>{percent(share)}</span>
            <span className={styles.split} aria-hidden="true">
              <i data-key="observed" style={{ flexGrow: observed }} />
              <i
                data-key="attention"
                style={{ flexGrow: skill.needsAttention }}
              />
              <i data-key="unknown" style={{ flexGrow: skill.unknown }} />
            </span>
          </li>
        ))}
      </ul>
      <p className={styles.legendRow}>
        <span>
          <i data-key="observed" aria-hidden="true" /> Observed
        </span>
        <span>
          <i data-key="attention" aria-hidden="true" /> Needs work
        </span>
        <span>
          <i data-key="unknown" aria-hidden="true" /> Not enough evidence
        </span>
      </p>
    </>
  );
}

/**
 * People (or teams) against the eight skills: each cell is the share of that
 * group's skill moments that were observed. Full cells stay quiet; a gap is
 * tinted amber, deeper the more often the skill needed attention. A real
 * table, so the values read without colour.
 */
export function SkillHeatmap({
  groups,
  label,
  onSelect,
}: {
  groups: Group[];
  label: string;
  onSelect?: (key: string) => void;
}) {
  return (
    <div
      className={styles.scrollHeat}
      tabIndex={0}
      role="region"
      aria-label={label}
    >
      <table className={styles.heat}>
        <thead>
          <tr>
            <th scope="col">{label}</th>
            {SKILLS.map((skill) => (
              <th key={skill.id} scope="col">
                {skill.short}
              </th>
            ))}
            <th scope="col">Calls</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.key ?? group.name}>
              <th scope="row">
                {onSelect && group.key ? (
                  <button
                    type="button"
                    onClick={() => onSelect(group.key ?? "")}
                  >
                    {group.name}
                  </button>
                ) : (
                  group.name
                )}
              </th>
              {SKILLS.map((skill) => {
                const cell = group.skills.find((item) => item.id === skill.id);
                const share = cell ? observedShare(cell) : null;
                return (
                  <td
                    key={skill.id}
                    data-empty={share === null ? "" : undefined}
                    data-full={share === 1 ? "" : undefined}
                    style={
                      share === null || share === 1
                        ? undefined
                        : ({
                            "--gap": `${Math.min(72, Math.round(10 + (1 - share) * 120))}%`,
                          } as CSSProperties)
                    }
                    title={`${group.name} · ${skill.short}: ${percent(share)} observed${cell?.needsAttention ? `, ${cell.needsAttention} needed attention` : ""}`}
                  >
                    {percent(share)}
                  </td>
                );
              })}
              <td className={styles.heatCount}>{count(group.calls)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Where each person needs coaching (owner bug #80, 29 Oct 2026: "so much
 * text … far better cleaner and tidy design"): the answer to the heatmap in
 * a few lines. Each skill that needed attention lists the people below full
 * marks, lowest first, as chips that filter to that person; the skills with
 * no gaps share one line. The full grid stays one tap away.
 */
export function SkillGaps({
  groups,
  onSelect,
}: {
  groups: Group[];
  onSelect?: (key: string) => void;
}) {
  const rows = SKILLS.map((skill) => ({
    skill,
    people: groups
      .map((group) => {
        const cell = group.skills.find((item) => item.id === skill.id);
        return { group, share: cell ? observedShare(cell) : null };
      })
      .filter(
        (item): item is { group: Group; share: number } =>
          item.share !== null && item.share < 1,
      )
      .sort((a, b) => a.share - b.share),
  }));
  const gaps = rows
    .filter((row) => row.people.length)
    .sort((a, b) => b.people.length - a.people.length);
  const clear = rows.filter((row) => !row.people.length);
  if (!gaps.length)
    return (
      <p className={styles.gapClear}>
        Everyone showed every skill they were read on in these calls.
      </p>
    );
  return (
    <>
      <ul className={styles.gaps} aria-label="Coaching gaps by skill">
        {gaps.map(({ skill, people }) => (
          <li key={skill.id}>
            <span className={styles.gapSkill}>
              {skill.short}
              <small>
                {people.length === 1
                  ? "1 person"
                  : `${count(people.length)} people`}
              </small>
            </span>
            <span className={styles.gapPeople}>
              {people.slice(0, 3).map(({ group, share }) =>
                onSelect && group.key ? (
                  <button
                    key={group.key}
                    type="button"
                    onClick={() => onSelect(group.key ?? "")}
                  >
                    {group.name}
                    <b>{percent(share)}</b>
                  </button>
                ) : (
                  <span key={group.key ?? group.name}>
                    {group.name}
                    <b>{percent(share)}</b>
                  </span>
                ),
              )}
              {people.length > 3 ? (
                <span className={styles.gapMore}>
                  +{count(people.length - 3)} more
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {clear.length ? (
        <p className={styles.caption}>
          No gaps in {clear.map((row) => row.skill.short).join(", ")}.
        </p>
      ) : null}
    </>
  );
}

/** The seller's share of talk, in bands; the middle band is the usual aim. */
export function TalkBands({
  bands,
}: {
  bands: { band: string; label: string; calls: number }[];
}) {
  const max = Math.max(1, ...bands.map((band) => band.calls));
  return (
    <ol
      className={styles.bands}
      aria-label="Calls by the seller's share of talk"
    >
      {bands.map((band) => (
        <li
          key={band.band}
          aria-label={`${band.label}: ${plural(band.calls, "call")}`}
          data-aim={
            band.band === "40_50" || band.band === "50_60" ? "" : undefined
          }
        >
          <span className={styles.bandValue}>{count(band.calls)}</span>
          <span className={styles.bandTrack} aria-hidden="true">
            <i style={{ height: `${(band.calls / max) * 100}%` }} />
          </span>
          <span className={styles.bandLabel}>{band.label}</span>
        </li>
      ))}
    </ol>
  );
}

/** The eight skill states of one call as eight small squares, in order. */
export function SkillDots({ skills }: { skills: string | null }) {
  if (!skills) return <span className={styles.muted}>—</span>;
  const words: Record<string, string> = {
    S: "strong",
    O: "observed",
    N: "needs attention",
    U: "not enough evidence",
    "-": "not applicable",
  };
  return (
    <span
      className={styles.dots}
      role="img"
      aria-label={SKILLS.map(
        (skill, index) => `${skill.short} ${words[skills[index]] ?? "unknown"}`,
      ).join(", ")}
    >
      {Array.from(skills).map((code, index) => (
        <i key={index} data-code={code} />
      ))}
    </span>
  );
}
