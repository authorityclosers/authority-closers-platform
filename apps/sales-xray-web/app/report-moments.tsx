"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Flag,
  Maximize2,
  Search,
  X,
} from "lucide-react";
import {
  ClipListenButton,
  ClipPlayIcon,
  ClipPlayState,
} from "./source-waveform";
import type { Finding, ReportEvidence, SalesReport } from "./report-contract";
import { Glyph, type GlyphName } from "./lightbox/glyph";
import { sourceTextAttributes } from "./lightbox/script";
import { formatClipRange, formatClock } from "./lightbox/time";
import {
  useReportInline,
  useReportNavigation,
  useReportReading,
} from "./report-reading-context";
import styles from "./report-moments.module.css";

const PAGE_SIZE = 4;
const sources = {
  rewatch: { label: "Rewatch", glyph: "seek-moment", tone: "rewatch" },
  strengths: { label: "Strength", glyph: "strength", tone: "strength" },
  improvements: { label: "Improvement", glyph: "focus", tone: "focus" },
  missed_opportunities: {
    label: "Missed opportunity",
    glyph: "missed",
    tone: "missed",
  },
  objection_analysis: {
    label: "Objection analysis",
    glyph: "objection",
    tone: "objection",
  },
  // The glyph set has no closing mark; the flag keeps a distinct shape.
  closing_analysis: { label: "Closing analysis", glyph: null, tone: "closing" },
} as const satisfies Record<
  string,
  { label: string; glyph: GlyphName | null; tone: string }
>;
type SourceKind = keyof typeof sources;
type Moment = {
  id: string;
  kind: SourceKind;
  title: string;
  explanation?: string;
  purpose?: "must_watch" | "watch" | "repeat";
  evidence: ReportEvidence;
};
type LinkedFinding = {
  label: string;
  title: string;
  note?: { label: string; text: string };
};

/** Plain-language labels for the supplied rewatch purpose. */
export const rewatchPurposeLabels = {
  must_watch: "Must watch",
  watch: "Worth a watch",
  repeat: "Repeat this",
} as const;

/**
 * One readable clock for a clip. A sub-second span is a single location, so
 * rounding never shows a false interval; seeking keeps the exact milliseconds.
 */
export function formatClipTime({
  start_ms,
  end_ms,
}: Pick<ReportEvidence, "start_ms" | "end_ms">) {
  return formatClipRange(start_ms, end_ms);
}

/** Preserve report order and each finding's provenance, including shared clips. */
function suppliedMoments(report: SalesReport): Moment[] {
  if (report.overview) {
    return report.overview.rewatch.flatMap((note, index) =>
      note.evidence.map((evidence, excerpt) => ({
        id: `rewatch:${index}:${excerpt}`,
        kind: "rewatch" as const,
        title: note.text,
        purpose: note.purpose,
        evidence,
      })),
    );
  }
  const collections: [Exclude<SourceKind, "rewatch">, Finding[]][] = [
    ["strengths", report.strengths],
    ["improvements", report.improvements],
    ["missed_opportunities", report.missed_opportunities],
    ["objection_analysis", report.objection_analysis],
    ["closing_analysis", report.closing_analysis],
  ];
  return collections.flatMap(([kind, findings]) =>
    findings.flatMap((finding, index) =>
      finding.evidence.map((evidence, excerpt) => ({
        id: `${kind}:${index}:${excerpt}`,
        kind,
        title: finding.title,
        explanation: finding.explanation,
        evidence,
      })),
    ),
  );
}

/** One distinct replayable interval and every supplied finding that cites it. */
export type ReplayClip = { evidence: ReportEvidence; titles: string[] };

/**
 * The same supplied dataset as the moments browser, grouped by identical
 * interval and ordered by time. The count, replay strip and list share it.
 */
export function reportReplayClips(report: SalesReport): ReplayClip[] {
  const clips = new Map<string, ReplayClip>();
  for (const { evidence, title } of suppliedMoments(report)) {
    const key = `${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`;
    const clip = clips.get(key);
    if (!clip) clips.set(key, { evidence, titles: [title] });
    else if (!clip.titles.includes(title)) clip.titles.push(title);
  }
  return [...clips.values()].sort(
    (a, b) =>
      a.evidence.start_ms - b.evidence.start_ms ||
      a.evidence.end_ms - b.evidence.end_ms,
  );
}

/** Same supplied dataset as the browser; repeated citations retain their contexts. */
export function countReportMoments(report: SalesReport): number {
  return reportReplayClips(report).length;
}

const sameClip = (a: ReportEvidence, b: ReportEvidence) =>
  a.segment_id === b.segment_id &&
  a.start_ms === b.start_ms &&
  a.end_ms === b.end_ms;

/**
 * Detailed findings that cite this exact clip. A join on the saved source span,
 * never an inference; historical moments already carry their own finding.
 */
function linkedFindings(
  report: SalesReport,
  evidence: ReportEvidence,
): LinkedFinding[] {
  const detail = report.overview;
  if (!detail) return [];
  const cites = (finding: Finding) =>
    finding.evidence.some((item) => sameClip(item, evidence));
  return [
    ...report.strengths.flatMap((finding, index) => {
      if (!cites(finding)) return [];
      const golden = detail.golden_moments.find((moment) => {
        const cited = finding.evidence[moment.evidence_index];
        return (
          moment.strength_index === index &&
          cited !== undefined &&
          sameClip(cited, evidence)
        );
      });
      return [
        golden
          ? {
              label: "Golden moment",
              title: finding.title,
              note: { label: "Why it worked", text: golden.why_effective },
            }
          : { label: "Strength", title: finding.title },
      ];
    }),
    ...report.improvements.flatMap((finding, index) => {
      if (!cites(finding)) return [];
      const fix = detail.improvement_details.find(
        (item) => item.finding_index === index,
      );
      return [
        {
          label: index === 0 ? "Change first" : "Priority fix",
          title: finding.title,
          ...(fix && {
            note: { label: "Try this", text: fix.replacement_behavior },
          }),
        },
      ];
    }),
    ...report.missed_opportunities.flatMap((finding, index) => {
      if (!cites(finding)) return [];
      const missed = detail.missed_details.find(
        (item) => item.finding_index === index,
      );
      return [
        {
          label: "Missed opportunity",
          title: finding.title,
          ...(missed && {
            note: { label: "Explore next", text: missed.follow_up },
          }),
        },
      ];
    }),
    ...report.objection_analysis
      .filter(cites)
      .map((finding) => ({ label: "Objection", title: finding.title })),
    ...report.closing_analysis
      .filter(cites)
      .map((finding) => ({ label: "Closing", title: finding.title })),
  ];
}

function MomentIcon({ kind }: { kind: SourceKind }) {
  const { glyph, tone } = sources[kind];
  return (
    <span className={styles.icon} data-tone={tone} aria-hidden="true">
      {glyph ? (
        <Glyph name={glyph} size={20} />
      ) : (
        <Flag size={20} strokeWidth={1.75} />
      )}
    </span>
  );
}

function KindLabel({ moment }: { moment: Moment }) {
  return (
    <span className={styles.kind} data-tone={sources[moment.kind].tone}>
      {sources[moment.kind].label}
      {moment.purpose ? ` · ${rewatchPurposeLabels[moment.purpose]}` : ""}
    </span>
  );
}

function Linked({ items }: { items: LinkedFinding[] }) {
  if (!items.length) return null;
  return (
    <div className={styles.linked}>
      <p className={styles.linkedHeading}>Also noted in this report</p>
      <ul>
        {items.map((item, index) => (
          <li key={`${item.label}:${index}`}>
            <span className={styles.linkedLabel}>{item.label}</span>
            <span className={styles.linkedTitle}>{item.title}</span>
            {item.note && (
              <span className={styles.linkedNote}>
                <strong>{item.note.label}:</strong> {item.note.text}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Native modality keeps search inputs, background inertness and focus together. */
function MomentsSheet({
  open,
  title,
  onClose,
  children,
  footer,
  contentKey,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  contentKey?: string;
}) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const lastContent = useRef(contentKey);
  useEffect(() => {
    if (!open || !dialog.current) return;
    const element = dialog.current;
    const previous = document.activeElement;
    element.showModal();
    close.current?.focus();
    return () => {
      element.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, [open]);
  useEffect(() => {
    if (open && contentKey !== lastContent.current && body.current) {
      body.current.scrollTop = 0;
      body.current.querySelector<HTMLElement>("h3")?.focus();
    }
    lastContent.current = contentKey;
  }, [open, contentKey]);

  return (
    <dialog
      ref={dialog}
      className={styles.sheet}
      aria-labelledby={id}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className={styles.sheetLayout}>
        <header className={styles.sheetHeader}>
          <h2 id={id}>{title}</h2>
          <button
            ref={close}
            type="button"
            className={styles.iconButton}
            aria-label={`Close ${title.toLowerCase()}`}
            onClick={onClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <div ref={body} className={styles.sheetBody}>
          {children}
        </div>
        {footer && <footer className={styles.sheetFooter}>{footer}</footer>}
      </div>
    </dialog>
  );
}

export type ReportMomentsProps = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  /** Mount the existing ReportTranscript here to retain exact-source search. */
  transcriptSlot?: ReactNode;
};

export function ReportMoments(props: ReportMomentsProps) {
  return (
    <MomentsBrowser
      key={JSON.stringify([
        props.report.source_sha256,
        props.report.transcript_revision,
      ])}
      {...props}
    />
  );
}

function MomentsBrowser({
  report,
  onSelectEvidence,
  transcriptSlot,
}: ReportMomentsProps) {
  const reading = useReportReading();
  const inline = useReportInline();
  const navigateToReport = useReportNavigation();
  const id = useId();
  const moments = suppliedMoments(report);
  const [filter, setFilter] = useState<SourceKind | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const kinds = [...new Set(moments.map((moment) => moment.kind))];
  const activeFilter =
    filter === "all" || kinds.includes(filter) ? filter : "all";
  const filtered = moments.filter(
    (moment) => activeFilter === "all" || moment.kind === activeFilter,
  );
  const index = Math.max(
    0,
    filtered.findIndex((moment) => moment.id === selectedId),
  );
  const moment = filtered[index];
  const page = Math.floor(index / PAGE_SIZE);
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const hasTranscript =
    Boolean(navigateToReport) ||
    (transcriptSlot !== undefined && transcriptSlot !== null);

  function select(next: number) {
    const target = filtered[next];
    if (target) setSelectedId(target.id);
  }
  function listen() {
    if (!moment) return;
    setReviewOpen(false);
    onSelectEvidence(moment.evidence, moment.title);
  }
  const navigation = (inSheet = false) => (
    <div
      className={styles.navigation}
      aria-label={inSheet ? "Review navigation" : "Moment navigation"}
    >
      <span role="status" aria-live="polite" aria-atomic="true">
        Moment {index + 1} of {filtered.length}
      </span>
      <div>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Previous moment"
          disabled={index === 0}
          onClick={() => select(index - 1)}
        >
          <ArrowLeft size={19} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Next moment"
          disabled={index === filtered.length - 1}
          onClick={() => select(index + 1)}
        >
          <ArrowRight size={19} aria-hidden="true" />
        </button>
      </div>
    </div>
  );

  return (
    <section
      className={styles.root}
      aria-label="Source moments"
      data-report-moments
      data-reading={reading || undefined}
      data-inline={inline || undefined}
    >
      <div className={styles.screen}>
        <header className={styles.toolbar}>
          <div className={styles.toolbarTitle}>
            <p className={styles.toolbarHeading}>
              Key moments <span>({moments.length})</span>
            </p>
            {kinds.length > 1 && (
              <label className={styles.filter}>
                <span className={styles.visuallyHidden}>Moment source</span>
                <select
                  aria-label="Moment source"
                  value={activeFilter}
                  onChange={(event) => {
                    setFilter(event.target.value as SourceKind | "all");
                    setSelectedId(null);
                  }}
                >
                  <option value="all">All sources</option>
                  {kinds.map((kind) => (
                    <option key={kind} value={kind}>
                      {sources[kind].label}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {hasTranscript && (
            <button
              type="button"
              className={styles.transcriptButton}
              onClick={() => {
                if (navigateToReport) navigateToReport("transcript");
                else setTranscriptOpen(true);
              }}
              aria-label="Search full transcript"
            >
              <Search size={17} aria-hidden="true" /> Transcript
            </button>
          )}
        </header>
        {moment ? (
          <div className={styles.workspace}>
            <aside className={styles.listPanel} aria-label="Moment list">
              <div className={styles.listHeading}>
                <span>Source moments</span>
                <span>Report order</span>
              </div>
              <ol className={styles.list} start={page * PAGE_SIZE + 1}>
                {visible.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={styles.row}
                      data-moment-id={item.id}
                      aria-current={item.id === moment.id ? "true" : undefined}
                      aria-controls={`${id}-detail`}
                      onClick={() => setSelectedId(item.id)}
                    >
                      <MomentIcon kind={item.kind} />
                      <span className={styles.rowCopy}>
                        <strong>{item.title}</strong>
                        <span>
                          {sources[item.kind].label} ·{" "}
                          {formatClock(item.evidence.start_ms)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              <nav className={styles.pagination} aria-label="Moment pages">
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label="Previous moment page"
                  disabled={page === 0}
                  onClick={() => select((page - 1) * PAGE_SIZE)}
                >
                  <ArrowLeft size={18} aria-hidden="true" />
                </button>
                <span>
                  Page {page + 1} of {pageCount}
                </span>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label="Next moment page"
                  disabled={page + 1 === pageCount}
                  onClick={() => select((page + 1) * PAGE_SIZE)}
                >
                  <ArrowRight size={18} aria-hidden="true" />
                </button>
              </nav>
            </aside>
            <article
              className={styles.detail}
              id={`${id}-detail`}
              aria-labelledby={`${id}-title`}
              data-focused-moment={moment.id}
            >
              {navigation()}
              <div className={styles.momentHeading}>
                <MomentIcon kind={moment.kind} />
                <div>
                  <KindLabel moment={moment} />
                  <h3 id={`${id}-title`}>{moment.title}</h3>
                  <span className={styles.time}>
                    {formatClipTime(moment.evidence)}
                  </span>
                </div>
              </div>
              <blockquote className={styles.quote}>
                <p {...sourceTextAttributes(moment.evidence.quote)}>
                  {moment.evidence.quote}
                </p>
              </blockquote>
              {moment.explanation && (
                <div className={styles.observation}>
                  <h4>Report observation</h4>
                  <p>{moment.explanation}</p>
                </div>
              )}
              <Linked items={linkedFindings(report, moment.evidence)} />
              <div className={styles.actions}>
                <ClipPlayState
                  startMs={moment.evidence.start_ms}
                  endMs={moment.evidence.end_ms}
                >
                  {(playing) => (
                    <button
                      type="button"
                      className={styles.listen}
                      onClick={listen}
                      aria-pressed={playing}
                    >
                      <ClipPlayIcon playing={playing} size={17} />{" "}
                      {playing ? "Pause" : "Listen"}
                    </button>
                  )}
                </ClipPlayState>
                {!inline && (
                  <button
                    type="button"
                    className={styles.review}
                    onClick={() => setReviewOpen(true)}
                  >
                    <Maximize2 size={17} aria-hidden="true" /> Open review
                  </button>
                )}
              </div>
            </article>
          </div>
        ) : (
          <div className={styles.empty}>
            <FileText size={28} aria-hidden="true" />
            <h3>No source moments supplied</h3>
            <p>
              {report.overview
                ? "No rewatch moments were selected for this report."
                : "No linked source excerpts were supplied for the report findings."}
              {hasTranscript
                ? " You can still search the full transcript."
                : " A transcript has not been provided in this view."}
            </p>
          </div>
        )}
      </div>

      {moment && !inline && (
        <MomentsSheet
          open={reviewOpen}
          contentKey={moment.id}
          title="Review moment"
          onClose={() => setReviewOpen(false)}
          footer={navigation(true)}
        >
          <div className={styles.fullMoment} data-full-moment={moment.id}>
            <KindLabel moment={moment} />
            <h3 tabIndex={-1}>{moment.title}</h3>
            <p className={styles.time}>{formatClipTime(moment.evidence)}</p>
            <blockquote {...sourceTextAttributes(moment.evidence.quote)}>
              {moment.evidence.quote}
            </blockquote>
            {moment.explanation && (
              <>
                <h4>Report observation</h4>
                <p>{moment.explanation}</p>
              </>
            )}
            <Linked items={linkedFindings(report, moment.evidence)} />
            <p className={styles.provenance}>From this call</p>
            <ClipPlayState
              startMs={moment.evidence.start_ms}
              endMs={moment.evidence.end_ms}
            >
              {(playing) => (
                <button
                  type="button"
                  className={styles.listen}
                  onClick={listen}
                  aria-pressed={playing}
                >
                  <ClipPlayIcon playing={playing} size={17} />{" "}
                  {playing ? "Pause this excerpt" : "Listen to this excerpt"}
                </button>
              )}
            </ClipPlayState>
          </div>
        </MomentsSheet>
      )}
      {hasTranscript && !navigateToReport && (
        <MomentsSheet
          open={transcriptOpen}
          title="Full transcript"
          onClose={() => setTranscriptOpen(false)}
        >
          {transcriptSlot}
        </MomentsSheet>
      )}

      {/* The reading flow and print: every supplied item, independent of filters and pages. */}
      <div className={styles.print} data-moments-print>
        {moments.length ? (
          <p className={styles.printIntro}>
            Quotes are exactly as spoken in this call. Listen plays that excerpt
            in the call player.
          </p>
        ) : (
          <p>No source moments supplied.</p>
        )}
        <ol className={styles.timeline}>
          {moments.map((item) => {
            const clip = formatClipTime(item.evidence);
            return (
              <li key={item.id} data-tone={sources[item.kind].tone}>
                <article className={styles.card}>
                  <p className={styles.cardMeta}>
                    <MomentIcon kind={item.kind} />
                    <KindLabel moment={item} />
                  </p>
                  <h3>{item.title}</h3>
                  <blockquote className={styles.cardQuote}>
                    <p {...sourceTextAttributes(item.evidence.quote)}>
                      {item.evidence.quote}
                    </p>
                  </blockquote>
                  {item.explanation && (
                    <p className={styles.cardNote}>{item.explanation}</p>
                  )}
                  <Linked items={linkedFindings(report, item.evidence)} />
                  <ClipListenButton
                    className={styles.readingListen}
                    startMs={item.evidence.start_ms}
                    endMs={item.evidence.end_ms}
                    iconSize={15}
                    onClick={() => onSelectEvidence(item.evidence, item.title)}
                    label={`${clip}: ${item.title}`}
                  >
                    {" "}
                    <span className={styles.clock}>{clip}</span>
                  </ClipListenButton>
                </article>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
