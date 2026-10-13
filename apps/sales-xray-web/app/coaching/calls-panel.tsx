"use client";

import { ChevronRight, PhoneCall } from "lucide-react";
import { useId, useImperativeHandle, useRef, useState, type Ref } from "react";
import { kitStyles, List, Panel, Row, Segmented } from "../ui/kit";
import type { CallSummary, ProgressPoint } from "./coaching-client";
import { CALLS, FOCUS, POINT_COPY, THEIR } from "./coaching-copy";
import { callDate } from "./coaching-format";
import { useCallHref, useTheirCoaching } from "./coaching-voice";
import styles from "./coaching.module.css";

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

export type CallsPanelHandle = { showSkill: () => void };

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
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const section = useRef<HTMLElement>(null);
  const they = useTheirCoaching();
  const callHref = useCallHref();
  const points = new Map(
    progress?.map((point) => [point.submission_id, point]),
  );
  const onSkill = callsOnSkill(calls, progress);
  const canFilter = Boolean(focusLabel && onSkill.length);
  useImperativeHandle(ref, () => ({
    showSkill() {
      if (!canFilter) return;
      setFilter("skill");
      setExpanded(false);
      section.current?.focus({ preventScroll: true });
      section.current?.scrollIntoView({ block: "start", behavior: "instant" });
    },
  }));
  if (!calls?.length) return null;
  const filtered = canFilter && filter === "skill";
  const shown = filtered ? onSkill : calls;
  return (
    <section
      ref={section}
      id="coaching-calls"
      className={styles.callsSection}
      aria-label={CALLS.title}
      tabIndex={-1}
    >
      <Panel title={CALLS.title} sub={CALLS.recent(calls.length)}>
        {canFilter ? (
          <div className={styles.callFilter}>
            <Segmented
              label={CALLS.filter}
              value={filtered ? "skill" : "all"}
              onChange={(next) => {
                setFilter(next);
                setExpanded(false);
              }}
              items={[
                { key: "all", label: CALLS.all },
                { key: "skill", label: CALLS.onSkill },
              ]}
            />
            <span className={styles.note} role="status">
              {CALLS.count(shown.length)}
            </span>
            <p className={styles.note}>
              {FOCUS.active}: {focusLabel}
            </p>
          </div>
        ) : null}
        <div
          id={listId}
          className={styles.callList}
          data-expanded={expanded ? "" : undefined}
        >
          <List label={they ? THEIR.recentCalls : CALLS.label}>
            {shown.map((call) => (
              <Row
                key={call.submission_id}
                icon={<PhoneCall size={15} aria-hidden="true" />}
                title={call.call_label}
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
                ]}
                end={
                  call.state === "ready" ? (
                    <ChevronRight size={15} aria-hidden="true" />
                  ) : null
                }
              />
            ))}
          </List>
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
