"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  Eye,
  Hand,
  Lightbulb,
  Play,
  Search,
  ThumbsUp,
  X,
} from "lucide-react";

import { voicesOf } from "./call-data";
import { formatClock } from "./lightbox/time";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import { RichText } from "./report-entities";
import { confirmedRoles } from "./sales-signals";
import { getShellState } from "./shell/shell-store";
import {
  ROLE_WORDS,
  speakerName,
  useSpeakerProfiles,
  voiceStyle,
  type SpeakerRole,
} from "./speaker-profiles";
import { useSourceWaveform } from "./source-waveform";
import styles from "./transcript-reader.module.css";

const TRANSCRIPT_KINDS = [
  "brand",
  "program",
  "money",
  "place",
  "document",
  "video",
  "team",
] as const;

export type FindingHighlightKind = "good" | "objection" | "missed" | "change";

export type FindingHighlight = {
  id: string;
  kind: FindingHighlightKind;
  badge: string;
  title: string;
  explanation?: string;
  quote?: string;
  evidence: ReportEvidence;
};

export function extractReportFindings(
  report?: SalesReport | null,
): FindingHighlight[] {
  if (!report) return [];
  const list: FindingHighlight[] = [];

  if (Array.isArray(report.strengths)) {
    report.strengths.forEach((f, fi) => {
      f.evidence?.forEach((e, ei) => {
        list.push({
          id: `good-${fi}-${ei}`,
          kind: "good",
          badge: "Done well",
          title: f.title,
          explanation: f.explanation,
          quote: e.quote,
          evidence: e,
        });
      });
    });
  }

  if (Array.isArray(report.objection_analysis)) {
    report.objection_analysis.forEach((f, fi) => {
      f.evidence?.forEach((e, ei) => {
        list.push({
          id: `objection-${fi}-${ei}`,
          kind: "objection",
          badge: "Pushback",
          title: f.title,
          explanation: f.explanation,
          quote: e.quote,
          evidence: e,
        });
      });
    });
  }

  if (Array.isArray(report.missed_opportunities)) {
    report.missed_opportunities.forEach((f, fi) => {
      f.evidence?.forEach((e, ei) => {
        list.push({
          id: `missed-${fi}-${ei}`,
          kind: "missed",
          badge: "Missed chance",
          title: f.title,
          explanation: f.explanation,
          quote: e.quote,
          evidence: e,
        });
      });
    });
  }

  if (Array.isArray(report.improvements)) {
    report.improvements.forEach((f, fi) => {
      f.evidence?.forEach((e, ei) => {
        list.push({
          id: `change-${fi}-${ei}`,
          kind: "change",
          badge: "Development area",
          title: f.title,
          explanation: f.explanation,
          quote: e.quote,
          evidence: e,
        });
      });
    });
  }

  return list.sort((a, b) => a.evidence.start_ms - b.evidence.start_ms);
}

export type TranscriptReaderProps = {
  isOpen: boolean;
  onClose: () => void;
  transcript?: Transcript | null;
  report?: SalesReport | null;
  callId?: string | null;
  callTitle?: string;
  onSeek?: (ms: number) => void;
  audioAvailable?: boolean;
};

type GroupedTurn = {
  id: string;
  speakerId: string | null;
  start_ms: number;
  end_ms: number;
  segments: TranscriptSegment[];
};

function formatTurnTime(ms: number): string {
  return formatClock(ms);
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function attributeValue(value: string): string {
  return value.replace(/["\\]/g, "\\$&");
}

/** Where focus goes back to: the opener, or the summary of its closed menu. */
function returnFocusTarget(opener: HTMLElement | null): HTMLElement | null {
  if (!opener?.isConnected) return null;
  const closedMenu = opener.closest("details:not([open])");
  return closedMenu?.querySelector<HTMLElement>("summary") ?? opener;
}

export function TranscriptReader(props: TranscriptReaderProps) {
  return <CallTranscriptReader key={props.callId ?? "none"} {...props} />;
}

function CallTranscriptReader({
  isOpen,
  onClose,
  transcript,
  report,
  callId = null,
  callTitle,
  onSeek,
  audioAvailable = true,
}: TranscriptReaderProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [selectedSpeaker, setSelectedSpeaker] = useState("all");
  const [activeMatchIndex, setActiveMatchIndex] = useState(0);
  const [jumpTarget, setJumpTarget] = useState<{
    segmentId: string;
    nonce: number;
  } | null>(null);
  const [cornerError, setCornerError] = useState<string | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const { profiles } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const waveform = useSourceWaveform();

  // Modal behaviour: focus search on open, keep Tab inside the reader,
  // Escape closes, lock body scroll, and give focus back on close.
  useEffect(() => {
    if (!isOpen) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    searchInputRef.current?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = containerRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const inside = active instanceof Node && dialog.contains(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = originalOverflow;
      returnFocusTarget(opener)?.focus({ preventScroll: true });
    };
  }, [isOpen]);

  // Voices and roles
  const voices = useMemo(
    () => (transcript ? voicesOf(transcript) : []),
    [transcript],
  );
  const roles = useMemo(
    () =>
      confirmedRoles(
        voices,
        Object.fromEntries(voices.map((id) => [id, profiles[id]?.role])),
      ),
    [profiles, voices],
  );

  const getSpeakerLabel = useCallback(
    (speakerId: string | null): string => {
      if (!speakerId) return "Unlabelled speaker";
      const index = voices.indexOf(speakerId);
      const profile = profiles[speakerId];
      return speakerName(index >= 0 ? index : 0, profile, accountName);
    },
    [accountName, profiles, voices],
  );

  const getSpeakerRole = useCallback(
    (speakerId: string | null): string | null => {
      if (!speakerId) return null;
      const role: SpeakerRole | null =
        profiles[speakerId]?.role ??
        (roles?.seller === speakerId
          ? "salesperson"
          : roles?.prospect === speakerId
            ? "prospect"
            : null);
      return role ? ROLE_WORDS[role] : null;
    },
    [profiles, roles],
  );

  const getSpeakerStyle = useCallback(
    (speakerId: string | null) => {
      if (!speakerId) return undefined;
      const index = voices.indexOf(speakerId);
      return index >= 0 ? voiceStyle(index) : undefined;
    },
    [voices],
  );

  // Findings
  const findings = useMemo(() => extractReportFindings(report), [report]);

  const findingsBySegmentId = useMemo(() => {
    const map = new Map<string, FindingHighlight[]>();
    for (const f of findings) {
      const segId = f.evidence.segment_id;
      if (!map.has(segId)) map.set(segId, []);
      map.get(segId)!.push(f);
    }
    return map;
  }, [findings]);

  // Group consecutive segments into turns
  const turns = useMemo(() => {
    if (!transcript?.segments?.length) return [];
    const grouped: GroupedTurn[] = [];
    let current: GroupedTurn | null = null;

    for (const segment of transcript.segments) {
      if (!current || current.speakerId !== segment.speaker_id) {
        current = {
          id: `turn-${segment.id}`,
          speakerId: segment.speaker_id,
          start_ms: segment.start_ms,
          end_ms: segment.end_ms,
          segments: [segment],
        };
        grouped.push(current);
      } else {
        current.segments.push(segment);
        current.end_ms = segment.end_ms;
      }
    }
    return grouped;
  }, [transcript]);

  // Filtered turns based on speaker
  const visibleTurns = useMemo(() => {
    if (selectedSpeaker === "all") return turns;
    return turns.filter((t) => t.speakerId === selectedSpeaker);
  }, [selectedSpeaker, turns]);

  // Search matches only what the reader shows, so the count, the
  // highlights and Next/Previous always agree with the speaker filter.
  const searchMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return visibleTurns.flatMap((turn) =>
      turn.segments.filter((seg) => seg.text.toLowerCase().includes(q)),
    );
  }, [query, visibleTurns]);

  const search = (value: string) => {
    setQuery(value);
    setActiveMatchIndex(0);
  };

  const filterSpeaker = (value: string) => {
    setSelectedSpeaker(value);
    setActiveMatchIndex(0);
  };

  // Scroll after render, inside this reader only: the Document view's
  // transcript appendix carries the same segment ids behind the overlay.
  useEffect(() => {
    if (!jumpTarget) return;
    const target = containerRef.current?.querySelector<HTMLElement>(
      `[data-segment-id="${attributeValue(jumpTarget.segmentId)}"]`,
    );
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.setAttribute("data-arrived", "true");
    const timer = window.setTimeout(
      () => target.removeAttribute("data-arrived"),
      1500,
    );
    return () => window.clearTimeout(timer);
  }, [jumpTarget]);

  const jumpToSegment = (segmentId: string) =>
    setJumpTarget({ segmentId, nonce: Date.now() });

  // Jump to moment from dropdown
  const handleJumpToMoment = (startMsStr: string) => {
    const startMs = Number(startMsStr);
    if (Number.isNaN(startMs) || !transcript?.segments.length) return;
    const segment =
      transcript.segments.find(
        (s) => startMs >= s.start_ms && startMs <= s.end_ms,
      ) ?? transcript.segments.find((s) => s.start_ms >= startMs);
    if (!segment) return;
    // A moment hidden by the speaker filter is revealed, not skipped.
    if (selectedSpeaker !== "all" && segment.speaker_id !== selectedSpeaker) {
      filterSpeaker("all");
    }
    jumpToSegment(segment.id);
  };

  // Match navigation
  const jumpToMatch = (index: number) => {
    if (!searchMatches.length) return;
    const safeIndex = (index + searchMatches.length) % searchMatches.length;
    setActiveMatchIndex(safeIndex);
    const targetSegment = searchMatches[safeIndex];
    if (targetSegment) jumpToSegment(targetSegment.id);
  };

  const handlePlay = (startMs: number) => {
    if (!onSeek) {
      setCornerError("Audio playback is not configured for this report.");
      return;
    }
    try {
      onSeek(startMs);
    } catch {
      setCornerError("Could not play audio from this turn.");
    }
  };

  if (!isOpen) return null;

  const matchCount = searchMatches.length;
  const currentMatch =
    searchMatches[Math.min(activeMatchIndex, Math.max(matchCount - 1, 0))];

  return createPortal(
    <div
      ref={containerRef}
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-label="Transcript reader"
      data-transcript-reader
      data-lx-surface="light"
    >
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.headerTitleGroup}>
            <BookOpen
              size={18}
              className={styles.readerIcon}
              aria-hidden="true"
            />
            <h1 className={styles.readerTitle}>Transcript</h1>
            <div className={styles.readerMeta}>
              {callTitle && (
                <>
                  <span className={styles.metaDot}>·</span>
                  <span>{callTitle}</span>
                </>
              )}
              {transcript && (
                <>
                  <span className={styles.metaDot}>·</span>
                  <span>{formatClock(transcript.duration_ms)}</span>
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Close transcript reader"
          >
            <span>Close</span>
            <kbd className={styles.shortcutHint}>Esc</kbd>
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className={styles.controlsBar}>
          <div className={styles.searchGroup}>
            <div className={styles.searchWrapper}>
              <Search
                size={14}
                className={styles.searchIcon}
                aria-hidden="true"
              />
              <input
                ref={searchInputRef}
                type="search"
                className={styles.searchInput}
                value={query}
                onChange={(e) => search(e.target.value)}
                placeholder="Search transcript..."
                aria-label="Search transcript"
              />
              {query && (
                <button
                  type="button"
                  className={styles.clearSearch}
                  onClick={() => search("")}
                  aria-label="Clear search"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              )}
            </div>

            {query.trim() && (
              <span
                className={styles.matchBadge}
                role="status"
                aria-live="polite"
              >
                {matchCount === 0
                  ? "No matches"
                  : `${matchCount} ${matchCount === 1 ? "match" : "matches"}`}
              </span>
            )}

            {matchCount > 0 && (
              <div
                className={styles.matchNav}
                role="group"
                aria-label="Search match navigation"
              >
                <button
                  type="button"
                  className={styles.matchNavBtn}
                  onClick={() => jumpToMatch(activeMatchIndex - 1)}
                  aria-label="Previous match"
                  title="Previous match"
                >
                  <ChevronUp size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className={styles.matchNavBtn}
                  onClick={() => jumpToMatch(activeMatchIndex + 1)}
                  aria-label="Next match"
                  title="Next match"
                >
                  <ChevronDown size={14} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>

          {voices.length > 0 && (
            <select
              className={styles.filterSelect}
              value={selectedSpeaker}
              onChange={(e) => filterSpeaker(e.target.value)}
              aria-label="Filter by speaker"
            >
              <option value="all">All speakers ({voices.length})</option>
              {voices.map((v) => (
                <option key={v} value={v}>
                  {getSpeakerLabel(v)}
                </option>
              ))}
            </select>
          )}

          {findings.length > 0 && (
            <select
              className={styles.jumpSelect}
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) handleJumpToMoment(e.target.value);
                e.target.value = "";
              }}
              aria-label="Jump to moment"
            >
              <option value="" disabled>
                Jump to moment ({findings.length})...
              </option>
              {findings.map((f) => (
                <option key={f.id} value={f.evidence.start_ms}>
                  [{f.badge}] {f.title} ({formatClock(f.evidence.start_ms)})
                </option>
              ))}
            </select>
          )}
        </div>
      </header>

      <main className={styles.content}>
        {!transcript ? (
          <div className={styles.turnList} aria-label="Loading transcript">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className={styles.skeletonTurn}>
                <div className={styles.skeletonHeader}>
                  <div className={styles.skeletonAvatar} />
                  <div
                    className={styles.skeletonLine}
                    style={{ width: "120px" }}
                  />
                </div>
                <div className={styles.skeletonText}>
                  <div
                    className={styles.skeletonLine}
                    style={{ width: "90%" }}
                  />
                  <div
                    className={styles.skeletonLine}
                    style={{ width: "75%" }}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : visibleTurns.length === 0 ? (
          <div className={styles.emptyState}>
            <p className={styles.emptyStateTitle}>No transcript turns found</p>
            <p>Try clearing your search query or speaker filter.</p>
          </div>
        ) : (
          <div className={styles.turnList}>
            {visibleTurns.map((turn) => {
              const speakerStyle = getSpeakerStyle(turn.speakerId);
              const label = getSpeakerLabel(turn.speakerId);
              const role = getSpeakerRole(turn.speakerId);
              const initial = label ? label.charAt(0).toUpperCase() : "?";

              // Check if any segment in this turn is currently playing in audio
              const isTurnPlaying = Boolean(
                waveform.playing &&
                  waveform.currentTimeMs >= turn.start_ms &&
                  waveform.currentTimeMs <= turn.end_ms,
              );

              return (
                <article
                  key={turn.id}
                  id={turn.id}
                  className={styles.turn}
                  style={speakerStyle}
                  data-active-turn={isTurnPlaying || undefined}
                >
                  <div className={styles.turnHeader}>
                    <div className={styles.speakerInfo}>
                      <span className={styles.speakerAvatar} aria-hidden="true">
                        {initial}
                      </span>
                      <strong className={styles.speakerName}>{label}</strong>
                      {role && <span className={styles.roleBadge}>{role}</span>}
                    </div>

                    <div className={styles.turnActions}>
                      {audioAvailable && onSeek && (
                        <button
                          type="button"
                          className={styles.turnPlayBtn}
                          onClick={() => handlePlay(turn.start_ms)}
                          aria-label={`Play audio from ${formatTurnTime(turn.start_ms)}`}
                        >
                          <Play
                            size={10}
                            fill="currentColor"
                            aria-hidden="true"
                          />
                          <span>Play</span>
                        </button>
                      )}
                      <time
                        className={styles.turnTimestamp}
                        dateTime={`PT${Math.round(turn.start_ms / 1000)}S`}
                      >
                        {formatTurnTime(turn.start_ms)}
                      </time>
                    </div>
                  </div>

                  <div className={styles.turnBody}>
                    {turn.segments.map((segment) => {
                      const segFindings =
                        findingsBySegmentId.get(segment.id) ?? [];
                      const hasSearchMatch = query.trim()
                        ? segment.text
                            .toLowerCase()
                            .includes(query.trim().toLowerCase())
                        : false;
                      const isCurrentSearchMatch =
                        currentMatch && currentMatch.id === segment.id;

                      return (
                        <div
                          key={segment.id}
                          className={styles.segmentRow}
                          data-segment-id={segment.id}
                        >
                          <p className={styles.segmentText}>
                            {query.trim() && hasSearchMatch ? (
                              <HighlightedText
                                text={segment.text}
                                query={query.trim()}
                                isCurrentMatch={Boolean(isCurrentSearchMatch)}
                              />
                            ) : (
                              <RichText
                                text={segment.text}
                                kinds={TRANSCRIPT_KINDS}
                                brandMarks={
                                  roles?.prospect === segment.speaker_id
                                }
                              />
                            )}
                          </p>

                          {/* Contextual report findings */}
                          {segFindings.map((finding) => (
                            <aside
                              key={finding.id}
                              className={styles.findingCallout}
                              data-kind={finding.kind}
                              aria-label={`${finding.badge}: ${finding.title}`}
                            >
                              <div className={styles.findingHeader}>
                                <span className={styles.findingBadge}>
                                  {finding.kind === "good" && (
                                    <ThumbsUp size={11} aria-hidden="true" />
                                  )}
                                  {finding.kind === "objection" && (
                                    <Hand size={11} aria-hidden="true" />
                                  )}
                                  {finding.kind === "missed" && (
                                    <Eye size={11} aria-hidden="true" />
                                  )}
                                  {finding.kind === "change" && (
                                    <Lightbulb size={11} aria-hidden="true" />
                                  )}
                                  <span>{finding.badge}</span>
                                </span>
                                <strong className={styles.findingTitle}>
                                  {finding.title}
                                </strong>
                              </div>
                              {finding.explanation && (
                                <p className={styles.findingExplanation}>
                                  {finding.explanation}
                                </p>
                              )}
                            </aside>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </main>

      {/* Calm corner card error: strictly anchored in corner, no layout shift */}
      {cornerError && (
        <aside className={styles.cornerCardError} role="alert">
          <span>{cornerError}</span>
          <button
            type="button"
            className={styles.cornerDismissBtn}
            onClick={() => setCornerError(null)}
            aria-label="Dismiss error"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </aside>
      )}
    </div>,
    document.body,
  );
}

function HighlightedText({
  text,
  query,
  isCurrentMatch,
}: {
  text: string;
  query: string;
  isCurrentMatch: boolean;
}) {
  const parts = useMemo(() => {
    if (!query) return [text];
    const regex = new RegExp(
      `(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`,
      "gi",
    );
    return text.split(regex);
  }, [query, text]);

  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark
            key={i}
            className={
              isCurrentMatch
                ? styles.activeSearchHighlight
                : styles.searchHighlight
            }
          >
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}
