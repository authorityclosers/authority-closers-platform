"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  FileText,
  Flag,
  Lightbulb,
  Maximize2,
  Play,
  Quote,
  Search,
  TrendingUp,
  X,
} from "lucide-react";
import type { Finding, ReportEvidence, SalesReport } from "./report-contract";
import { formatTranscriptTime } from "./report-transcript";
import { useReportReading } from "./report-reading-context";
import styles from "./report-moments.module.css";

const PAGE_SIZE = 4;
const sources = {
  rewatch: { label: "Rewatch", icon: FileText, tone: "teal" },
  strengths: { label: "Strength", icon: TrendingUp, tone: "blue" },
  improvements: { label: "Improvement", icon: Lightbulb, tone: "violet" },
  missed_opportunities: {
    label: "Missed opportunity",
    icon: Flag,
    tone: "orange",
  },
  objection_analysis: {
    label: "Objection analysis",
    icon: CircleHelp,
    tone: "violet",
  },
  closing_analysis: { label: "Closing analysis", icon: Flag, tone: "blue" },
} as const;
type SourceKind = keyof typeof sources;
type Moment = {
  id: string;
  kind: SourceKind;
  title: string;
  explanation?: string;
  purpose?: "must_watch" | "watch" | "repeat";
  evidence: ReportEvidence;
};
type MomentGroup = Moment & { contextId: string; contexts: Moment[] };
const purposes = { must_watch: "Must watch", watch: "Watch", repeat: "Repeat" };

/** Group exact excerpts, preserving shortlist order and every supplied context. */
function suppliedMoments(report: SalesReport): MomentGroup[] {
  const rewatch: Moment[] = (report.overview?.rewatch ?? []).flatMap(
    (note, index) =>
      note.evidence.map((evidence, excerpt) => ({
        id: `rewatch:${index}:${excerpt}`,
        kind: "rewatch" as const,
        title: note.text,
        purpose: note.purpose,
        evidence,
      })),
  );
  const collections: [Exclude<SourceKind, "rewatch">, Finding[]][] = [
    ["strengths", report.strengths],
    ["improvements", report.improvements],
    ["missed_opportunities", report.missed_opportunities],
    ["objection_analysis", report.objection_analysis],
    ["closing_analysis", report.closing_analysis],
  ];
  const findings = collections.flatMap(([kind, findings]) =>
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
  const groups = new Map<string, MomentGroup>();
  for (const context of [...rewatch, ...findings]) {
    const { segment_id, start_ms, end_ms, quote } = context.evidence;
    const key = JSON.stringify([segment_id, start_ms, end_ms, quote]);
    const group = groups.get(key);
    if (group) group.contexts.push(context);
    else
      groups.set(key, {
        ...context,
        contextId: context.id,
        contexts: [context],
      });
  }
  return [...groups.values()];
}

/** Exact excerpt count, not a score or a count of independent sales insights. */
export function countReportMoments(report: SalesReport): number {
  return suppliedMoments(report).length;
}

function RelatedObservations({ moment }: { moment: MomentGroup }) {
  const related = moment.contexts.filter(
    (context) => context.id !== moment.contextId,
  );
  if (!related.length) return null;
  return (
    <section aria-label="Other report observations for this excerpt">
      {related.map((context) => (
        <div key={context.id}>
          <h4>
            {sources[context.kind].label} · {context.title}
            {context.purpose ? ` · ${purposes[context.purpose]}` : ""}
          </h4>
          {context.explanation && <p>{context.explanation}</p>}
        </div>
      ))}
    </section>
  );
}

function timeRange(evidence: ReportEvidence) {
  return `${formatTranscriptTime(evidence.start_ms)} – ${formatTranscriptTime(evidence.end_ms)}`;
}

function MomentIcon({ kind }: { kind: SourceKind }) {
  const { icon: Icon, tone } = sources[kind];
  return (
    <span className={styles.icon} data-tone={tone} aria-hidden="true">
      <Icon size={21} strokeWidth={1.8} />
    </span>
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
  const id = useId();
  const moments = suppliedMoments(report);
  const [filter, setFilter] = useState<SourceKind | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const kinds = [
    ...new Set(
      moments.flatMap((moment) =>
        moment.contexts.map((context) => context.kind),
      ),
    ),
  ];
  const activeFilter =
    filter === "all" || kinds.includes(filter) ? filter : "all";
  const filtered = moments.flatMap((moment) => {
    if (activeFilter === "all") return [moment];
    const context = moment.contexts.find((item) => item.kind === activeFilter);
    return context
      ? [{ ...moment, ...context, id: moment.id, contextId: context.id }]
      : [];
  });
  const index = Math.max(
    0,
    filtered.findIndex((moment) => moment.id === selectedId),
  );
  const moment = filtered[index];
  const page = Math.floor(index / PAGE_SIZE);
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const hasTranscript = transcriptSlot !== undefined && transcriptSlot !== null;

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
    >
      <div className={styles.screen}>
        <header className={styles.toolbar}>
          <div className={styles.toolbarTitle}>
            <h2>
              Key moments <span>({moments.length})</span>
            </h2>
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
              onClick={() => setTranscriptOpen(true)}
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
                          {formatTranscriptTime(item.evidence.start_ms)}
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
                  <span
                    className={styles.kind}
                    data-tone={sources[moment.kind].tone}
                  >
                    {sources[moment.kind].label}
                    {moment.purpose ? ` · ${purposes[moment.purpose]}` : ""}
                  </span>
                  <h3 id={`${id}-title`}>{moment.title}</h3>
                  <span className={styles.time}>
                    {timeRange(moment.evidence)}
                    {moment.contexts.length > 1
                      ? ` · ${moment.contexts.length} linked observations`
                      : ""}
                  </span>
                </div>
              </div>
              <div className={styles.preview}>
                <blockquote className={styles.quote}>
                  <Quote size={23} aria-hidden="true" />
                  <p>{moment.evidence.quote}</p>
                </blockquote>
                {moment.explanation && (
                  <div className={styles.observation}>
                    <h4>Report observation</h4>
                    <p>{moment.explanation}</p>
                  </div>
                )}
              </div>
              <p
                className={styles.provenance}
                title={`Source: ${report.source_label}`}
              >
                Source: {report.source_label}
              </p>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.listen}
                  onClick={listen}
                >
                  <Play size={17} fill="currentColor" aria-hidden="true" />{" "}
                  Listen
                </button>
                <button
                  type="button"
                  className={styles.review}
                  onClick={() => setReviewOpen(true)}
                >
                  <Maximize2 size={17} aria-hidden="true" /> Open review
                </button>
              </div>
            </article>
          </div>
        ) : (
          <div className={styles.empty}>
            <FileText size={28} aria-hidden="true" />
            <h3>No source moments supplied</h3>
            <p>
              No linked source excerpts were supplied for the report findings or
              rewatch notes.
              {hasTranscript
                ? " You can still search the full transcript."
                : " A transcript has not been provided in this view."}
            </p>
          </div>
        )}
      </div>

      {moment && (
        <MomentsSheet
          open={reviewOpen}
          contentKey={moment.id}
          title="Review moment"
          onClose={() => setReviewOpen(false)}
          footer={navigation(true)}
        >
          <div className={styles.fullMoment} data-full-moment={moment.id}>
            <span className={styles.kind} data-tone={sources[moment.kind].tone}>
              {sources[moment.kind].label}
              {moment.purpose ? ` · ${purposes[moment.purpose]}` : ""}
            </span>
            <h3 tabIndex={-1}>{moment.title}</h3>
            <p className={styles.time}>{timeRange(moment.evidence)}</p>
            <blockquote>{moment.evidence.quote}</blockquote>
            {moment.explanation && (
              <>
                <h4>Report observation</h4>
                <p>{moment.explanation}</p>
              </>
            )}
            <RelatedObservations moment={moment} />
            <dl className={styles.sourceDetails}>
              <dt>Source</dt>
              <dd>{report.source_label}</dd>
              <dt>Transcript revision</dt>
              <dd>{report.transcript_revision}</dd>
              <dt>Source segment</dt>
              <dd>{moment.evidence.segment_id}</dd>
              <dt>Source fingerprint</dt>
              <dd>{report.source_sha256}</dd>
            </dl>
            <button type="button" className={styles.listen} onClick={listen}>
              <Play size={17} aria-hidden="true" /> Listen to this excerpt
            </button>
          </div>
        </MomentsSheet>
      )}
      {hasTranscript && (
        <MomentsSheet
          open={transcriptOpen}
          title="Full transcript"
          onClose={() => setTranscriptOpen(false)}
        >
          {transcriptSlot}
        </MomentsSheet>
      )}

      {/* Independent of interactive filters/pages, so printing retains every supplied item. */}
      <div className={styles.print} data-moments-print>
        <h2>Source moments</h2>
        <p>
          Source: {report.source_label} · Transcript revision:{" "}
          {report.transcript_revision}
        </p>
        <p>Source fingerprint: {report.source_sha256}</p>
        {!moments.length && <p>No source moments supplied.</p>}
        {moments.map((item, position) => (
          <article key={item.id}>
            <h3>
              {position + 1}. {sources[item.kind].label}: {item.title}
            </h3>
            {item.purpose && <p>{purposes[item.purpose]}</p>}
            <p>
              {timeRange(item.evidence)} · Segment: {item.evidence.segment_id}
            </p>
            <blockquote>{item.evidence.quote}</blockquote>
            {item.explanation && <p>{item.explanation}</p>}
            <RelatedObservations moment={item} />
            <button
              type="button"
              className={styles.readingListen}
              onClick={() => onSelectEvidence(item.evidence, item.title)}
              aria-label={`Listen to ${item.title} at ${formatTranscriptTime(item.evidence.start_ms)}`}
            >
              <Play size={16} aria-hidden="true" /> Listen to this excerpt
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
