"use client";

/**
 * One screen per call: the player and transcript on the left, the report,
 * six pillars, Coaching, metrics and runs on the right; on phones the player
 * stays on top and the transcript becomes a tab. Keyboard-first (press ?).
 * Nothing moves while it loads: the server sends the call whole.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  Keyboard,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge, Kbd, kitStyles } from "../ui/kit";
import {
  STATUS_LABEL,
  STATUS_TONE,
  clock,
  languageLabel,
  segmentAt,
  speakerNames,
  when,
  type Bundle,
  type Call,
  type Evidence,
} from "./call-data";
import { Player } from "./player";
import {
  Coaching,
  CurrentReport,
  Metrics,
  Pillars,
  Runs,
} from "./report-views";
import {
  SHORTCUTS,
  durationOf,
  keyAction,
  nextSpeed,
  waveformBars,
  type ReviewTab,
} from "./review-logic";
import { typing } from "./queue-keys";
import { TranscriptPane } from "./transcript-pane";
import styles from "./review.module.css";

const TABS: {
  key: ReviewTab;
  label: string;
  key1: string;
  phoneOnly?: boolean;
}[] = [
  { key: "transcript", label: "Transcript", key1: "T", phoneOnly: true },
  { key: "report", label: "Report", key1: "R" },
  { key: "pillars", label: "Six pillars", key1: "S" },
  { key: "coaching", label: "Coaching", key1: "C" },
  { key: "metrics", label: "Metrics", key1: "M" },
  { key: "runs", label: "Runs", key1: "U" },
];

export type Neighbours = { previous: string | null; next: string | null };

export function ReviewScreen({
  call,
  bundle,
  compare,
  compareBundle,
  back,
  neighbours,
  safety = false,
}: {
  /** The operator may withhold passages (platform_content_safety_manage). */
  safety?: boolean;
  call: Call;
  bundle: Bundle;
  compare: string | null;
  compareBundle: Bundle | null;
  back: string;
  neighbours: Neighbours;
}) {
  const router = useRouter();
  const audio = useRef<HTMLAudioElement | null>(null);
  const [tab, setTab] = useState<ReviewTab>(compare ? "runs" : "report");
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [failed, setFailed] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);
  const [help, setHelp] = useState(false);

  const segments = bundle.transcript.segments;
  const names = useMemo(
    () => speakerNames(bundle.report, segments),
    [bundle.report, segments],
  );
  const durationMs = durationOf(bundle);
  const bars = useMemo(
    () => waveformBars(bundle.waveform, 220),
    [bundle.waveform],
  );
  const active = segmentAt(segments, currentMs);
  const run = call.runs.find((item) => item.id === bundle.runId);

  const href = useCallback(
    (query: Record<string, string | null>, recordingId = call.recordingId) => {
      const params = new URLSearchParams();
      const next: Record<string, string | null> = {
        run: bundle.runId,
        compare,
        back: back || null,
        ...query,
      };
      if (recordingId !== call.recordingId) {
        next.run = null;
        next.compare = null;
      }
      for (const [key, value] of Object.entries(next))
        if (value) params.set(key, value);
      const text = params.toString();
      return `/calls/${recordingId}${text ? `?${text}` : ""}`;
    },
    [back, bundle.runId, call.recordingId, compare],
  );

  const seek = useCallback(
    (ms: number) => {
      const element = audio.current;
      const bounded = Math.max(0, Math.min(ms, durationMs ?? ms));
      setCurrentMs(bounded);
      if (element && !failed) element.currentTime = bounded / 1000;
    },
    [durationMs, failed],
  );
  const toggle = useCallback(() => {
    const element = audio.current;
    if (!element || failed) return;
    if (element.paused) void element.play().catch(() => setFailed(true));
    else element.pause();
  }, [failed]);
  const changeSpeed = useCallback((step: 1 | -1) => {
    setSpeed((value) => {
      const next = nextSpeed(value, step);
      if (audio.current) audio.current.playbackRate = next;
      return next;
    });
  }, []);
  const playEvidence = useCallback(
    (evidence: Evidence) => {
      setFocused(evidence.segmentId);
      seek(evidence.startMs);
      const element = audio.current;
      if (element && element.paused && !failed)
        void element.play().catch(() => setFailed(true));
    },
    [failed, seek],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (typing(event.target)) return;
      // Buttons keep Space and Enter for themselves.
      if (event.key === " " && event.target instanceof HTMLButtonElement)
        return;
      const action = keyAction(event);
      if (!action) return;
      if (action.kind === "close") {
        if (help) setHelp(false);
        return;
      }
      event.preventDefault();
      if (action.kind === "toggle") toggle();
      else if (action.kind === "seek") seek(currentMs + action.byMs);
      else if (action.kind === "speed") changeSpeed(action.step);
      else if (action.kind === "tab") setTab(action.tab);
      else if (action.kind === "help") setHelp((value) => !value);
      else if (action.kind === "call") {
        const target = action.step > 0 ? neighbours.next : neighbours.previous;
        if (target) router.push(href({}, target));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [changeSpeed, currentMs, help, href, neighbours, router, seek, toggle]);

  return (
    <div className={styles.screen}>
      <header className={styles.head}>
        <div className={styles.headText}>
          <Link
            href={back ? `/calls?${back}` : "/calls"}
            className={kitStyles.back}
          >
            <ChevronLeft size={13} aria-hidden="true" />
            Calls
          </Link>
          <h1 className={kitStyles.title} title={call.rep.label}>
            {call.rep.label}
          </h1>
          <p className={kitStyles.context}>
            <span>{call.organisation.name}</span>
            <span>{when(call.uploadedAt)}</span>
            <span>{clock(durationMs)}</span>
            <span>{languageLabel(run?.language ?? null)}</span>
            <span>
              {[run?.model ?? run?.provider, run?.promptRevision]
                .filter(Boolean)
                .join(" · ") || "Model not recorded"}
            </span>
          </p>
        </div>
        <div className={styles.headActions}>
          <Badge tone={STATUS_TONE[call.status]}>
            {STATUS_LABEL[call.status]}
          </Badge>
          <button
            type="button"
            className={kitStyles.button}
            disabled
            title="Needs an admin re-run API. Today only the rep can retry a call from Sales Xray."
          >
            <RefreshCcw size={14} aria-hidden="true" />
            Re-run
          </button>
          {safety ? (
            <Link
              href={`/safety?recording=${call.recordingId}`}
              className={kitStyles.button}
              title="Withhold sensitive passages of this call"
            >
              <ShieldCheck size={14} aria-hidden="true" />
              Safety
            </Link>
          ) : null}
          <button
            type="button"
            className={kitStyles.button}
            disabled
            title="Training and test marks arrive with the gold-set store."
          >
            <FlaskConical size={14} aria-hidden="true" />
            Mark data
          </button>
          <Link
            href={neighbours.previous ? href({}, neighbours.previous) : "#"}
            className={kitStyles.button}
            data-variant="icon"
            aria-disabled={!neighbours.previous}
            aria-label="Previous call (P)"
            title="Previous call (P)"
            tabIndex={neighbours.previous ? undefined : -1}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </Link>
          <Link
            href={neighbours.next ? href({}, neighbours.next) : "#"}
            className={kitStyles.button}
            data-variant="icon"
            aria-disabled={!neighbours.next}
            aria-label="Next call (N)"
            title="Next call (N)"
            tabIndex={neighbours.next ? undefined : -1}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
          <button
            type="button"
            className={kitStyles.button}
            data-variant="icon"
            onClick={() => setHelp((value) => !value)}
            aria-label="Keyboard shortcuts (?)"
            aria-expanded={help}
            title="Keyboard shortcuts (?)"
          >
            <Keyboard size={16} aria-hidden="true" />
          </button>
        </div>
      </header>

      {help ? (
        <section className={styles.help} aria-label="Keyboard shortcuts">
          <dl>
            {SHORTCUTS.map(([keys, what]) => (
              <div key={keys}>
                <dt>
                  <Kbd>{keys}</Kbd>
                </dt>
                <dd>{what}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <div className={styles.grid}>
        <div className={styles.left}>
          <Player
            audio={audio}
            src={bundle.audioUrl}
            bars={bars}
            durationMs={durationMs}
            currentMs={currentMs}
            playing={playing}
            speed={speed}
            failed={failed}
            phases={bundle.report.story?.phases ?? []}
            onToggle={toggle}
            onSeek={seek}
            onSpeed={changeSpeed}
            onTime={setCurrentMs}
            onPlaying={setPlaying}
            onFailed={() => setFailed(true)}
          />
          <div
            className={styles.transcriptPanel}
            data-tab-active={tab === "transcript" ? "" : undefined}
          >
            <TranscriptPane
              segments={segments}
              names={names}
              active={active}
              focused={focused}
              onSeek={seek}
            />
          </div>
        </div>
        <div className={styles.right}>
          <nav className={styles.tabs} aria-label="Review views">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.tab}
                data-phone-only={item.phoneOnly ? "" : undefined}
                aria-pressed={tab === item.key}
                aria-keyshortcuts={item.key1}
                onClick={() => setTab(item.key)}
              >
                {item.label}
                <kbd>{item.key1}</kbd>
              </button>
            ))}
          </nav>
          <div
            className={styles.view}
            data-hidden-on-phone={tab === "transcript" ? "" : undefined}
          >
            {tab === "report" || tab === "transcript" ? (
              <CurrentReport report={bundle.report} onEvidence={playEvidence} />
            ) : tab === "pillars" ? (
              <Pillars
                report={bundle.report}
                durationMs={durationMs}
                onEvidence={playEvidence}
              />
            ) : tab === "coaching" ? (
              <Coaching report={bundle.report} onEvidence={playEvidence} />
            ) : tab === "metrics" ? (
              <Metrics bundle={bundle} names={names} />
            ) : (
              <Runs
                call={call}
                current={bundle}
                compare={compare}
                compareBundle={compareBundle}
                baseHref={href}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
