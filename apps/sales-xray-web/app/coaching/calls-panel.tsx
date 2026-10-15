"use client";

import { ChevronRight, PhoneCall } from "lucide-react";
import Link from "next/link";
import {
  useContext,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type Ref,
} from "react";
import { Empty, kitStyles, List, Panel, Row, Segmented } from "../ui/kit";
import type { CallSummary, ProgressPoint } from "./coaching-client";
import { CALLS, FOCUS, POINT_COPY, THEIR } from "./coaching-copy";
import { callDate } from "./coaching-format";
import {
  CallsOpenReports,
  useCallHref,
  useTheirCoaching,
} from "./coaching-voice";
import styles from "./coaching.module.css";

/** Keep the saved call name intact while emphasising literal search words. */
function callNameMatch(label: string, term: string) {
  if (!term) return label;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return label.split(new RegExp(`(${escaped})`, "giu")).map((part, index) =>
    index % 2 ? (
      <mark className={styles.repMatch} key={index}>
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

/** Only retained ready calls with a saved opportunity on this focus. */
export function callsOnSkill(
  calls: CallSummary[] = [],
  progress: ProgressPoint[] = [],
) {
  const points = new Map(progress.map((point) => [point.submission_id, point]));
  return calls.filter(
    (call) =>
      call.state === "ready" &&
      points.has(call.submission_id) &&
      points.get(call.submission_id)!.state !== "not_covered",
  );
}

export type CallsPanelHandle = {
  showSkill: () => void;
  showAll: () => void;
};

type Finding = "all" | "suggested" | "no_suggestion";

/** Every call stays available; filter only from this focus's saved records. */
export function CallsPanel({
  calls,
  progress,
  focusLabel,
  ref,
}: {
  calls?: CallSummary[];
  progress?: ProgressPoint[];
  focusLabel?: string;
  ref?: Ref<CallsPanelHandle>;
}) {
  const [filter, setFilter] = useState<"all" | "skill">("all");
  const [finding, setFinding] = useState<Finding>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const section = useRef<HTMLElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const they = useTheirCoaching();
  const reportsOnly = useContext(CallsOpenReports);
  const callHref = useCallHref();
  const points = new Map(
    progress?.map((point) => [point.submission_id, point]),
  );
  const onSkill = callsOnSkill(calls, progress);
  // A ready call's saved record on the current focus (as the skill filter).
  const pointState = (call: CallSummary) => {
    const state = points.get(call.submission_id)?.state;
    return call.state === "ready" && state && state !== "not_covered"
      ? state
      : null;
  };
  const canFilter = Boolean(focusLabel && onSkill.length);
  const canCompare =
    onSkill.some(
      (call) => points.get(call.submission_id)?.state === "suggested",
    ) &&
    onSkill.some(
      (call) => points.get(call.submission_id)?.state === "no_suggestion",
    );
  const showCalls = (next: "all" | "skill") => {
    setFilter(next);
    setFinding("all");
    setQuery("");
    setExpanded(false);
    section.current?.focus({ preventScroll: true });
    section.current?.scrollIntoView({ block: "start", behavior: "instant" });
  };
  useImperativeHandle(ref, () => ({
    showSkill() {
      if (canFilter) showCalls("skill");
    },
    showAll() {
      showCalls("all");
    },
  }));
  if (!calls?.length) return null;
  const filtered = canFilter && filter === "skill";
  const searchable = calls.length > 3;
  const name = query.trim().toLocaleLowerCase();
  const shown = (filtered ? onSkill : calls).filter(
    (call) =>
      (!searchable || call.call_label.toLocaleLowerCase().includes(name)) &&
      (!filtered ||
        !canCompare ||
        finding === "all" ||
        points.get(call.submission_id)?.state === finding),
  );
  return (
    <section
      ref={section}
      id="coaching-calls"
      className={styles.callsSection}
      aria-label={CALLS.title}
      tabIndex={-1}
    >
      <Panel title={CALLS.title} sub={CALLS.recent(calls.length)}>
        {canFilter || searchable ? (
          <div className={styles.callFilter}>
            {searchable ? (
              <label className={`${kitStyles.field} ${styles.callSearch}`}>
                <span className={styles.srOnly}>{CALLS.findCall}</span>
                <input
                  ref={search}
                  type="search"
                  placeholder={CALLS.findCall}
                  aria-controls={listId}
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setExpanded(false);
                  }}
                />
              </label>
            ) : null}
            {canFilter ? (
              <Segmented
                label={CALLS.filter}
                value={filtered ? "skill" : "all"}
                onChange={(next) => {
                  setFilter(next);
                  setFinding("all");
                  setExpanded(false);
                }}
                items={[
                  { key: "all", label: CALLS.all },
                  { key: "skill", label: CALLS.onSkill },
                ]}
              />
            ) : null}
            {filtered && canCompare ? (
              <span className={`${kitStyles.field} ${styles.callFinding}`}>
                <select
                  aria-label={CALLS.finding}
                  aria-controls={listId}
                  value={finding}
                  onChange={(event) => {
                    setFinding(event.target.value as Finding);
                    setExpanded(false);
                  }}
                >
                  <option value="all">{CALLS.allFindings}</option>
                  <option value="suggested">{POINT_COPY.suggested}</option>
                  <option value="no_suggestion">
                    {POINT_COPY.no_suggestion}
                  </option>
                </select>
              </span>
            ) : null}
            <span className={styles.note} role="status">
              {CALLS.count(shown.length)}
            </span>
            {query ? (
              <button
                type="button"
                className={kitStyles.button}
                onClick={() => {
                  setQuery("");
                  setExpanded(false);
                  search.current?.focus();
                }}
              >
                {CALLS.clearSearch}
              </button>
            ) : null}
            {canFilter ? (
              <p className={styles.note}>
                {FOCUS.active}: {focusLabel}
              </p>
            ) : null}
          </div>
        ) : null}
        <div
          id={listId}
          className={styles.callList}
          data-expanded={expanded ? "" : undefined}
        >
          {shown.length ? (
            <List label={they ? THEIR.recentCalls : CALLS.label}>
              {shown.map((call) => (
                <Row
                  key={call.submission_id}
                  icon={<PhoneCall size={15} aria-hidden="true" />}
                  title={
                    <span className={styles.callTitle}>
                      {callNameMatch(call.call_label, name)}
                    </span>
                  }
                  href={
                    call.state === "ready"
                      ? callHref(call.submission_id)
                      : `/analysis/calls/${call.submission_id}`
                  }
                  meta={[
                    callDate(call.created_at),
                    filtered
                      ? POINT_COPY[points.get(call.submission_id)!.state]
                      : call.state === "pending"
                        ? CALLS.analysing
                        : call.state === "unavailable"
                          ? CALLS.unavailable
                          : (call.focus_label ??
                            (they ? THEIR.callFallback : CALLS.fallback)),
                    !filtered && call.recurring ? CALLS.recurring : null,
                    // The saved record on the current focus, marked like the
                    // progress history, so the full list scans without a filter.
                    !filtered && canFilter && pointState(call) ? (
                      <span
                        className={styles.callPoint}
                        data-state={pointState(call)}
                      >
                        {POINT_COPY[pointState(call)!]}
                      </span>
                    ) : null,
                  ]}
                  end={
                    call.state === "ready" ? (
                      reportsOnly ? (
                        <ChevronRight size={15} aria-hidden="true" />
                      ) : (
                        <Link
                          className={kitStyles.button}
                          href={`/analysis/calls/${call.submission_id}`}
                          prefetch={false}
                          aria-label={CALLS.reportFor(call.call_label)}
                        >
                          {CALLS.report}
                        </Link>
                      )
                    ) : null
                  }
                />
              ))}
            </List>
          ) : (
            <Empty
              icon={PhoneCall}
              title={CALLS.noMatches}
              text={filtered ? CALLS.noSkillMatchesText : CALLS.noMatchesText}
            />
          )}
        </div>
        {shown.length > 3 ? (
          <button
            type="button"
            className={`${kitStyles.button} ${styles.moreCalls}`}
            data-many={shown.length > 8 ? "" : undefined}
            aria-expanded={expanded}
            aria-controls={listId}
            onClick={() => {
              setExpanded(!expanded);
              if (expanded) {
                section.current
                  ?.querySelector<HTMLAnchorElement>("li a")
                  ?.focus({ preventScroll: true });
                section.current?.scrollIntoView({
                  block: "start",
                  behavior: "instant",
                });
              }
            }}
          >
            {expanded ? CALLS.showFewer : CALLS.showAll(shown.length)}
          </button>
        ) : null}
      </Panel>
    </section>
  );
}
