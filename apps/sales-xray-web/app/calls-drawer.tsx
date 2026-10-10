"use client";

/* Calls workspace preview drawer (AUT-999 v2): the call at a glance, its key
   moments playable in place, and the next step, without leaving the list. */
import {
  ArrowRight,
  CalendarCheck,
  Check,
  Copy,
  Handshake,
  FolderOpen,
  MessageCircleQuestion,
  Pencil,
  Play,
  Target,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { callHref } from "./acquisition-client";
import {
  audioSource,
  type CallInsight,
  type InsightReadState,
} from "./calls-insights";
import { formatClock } from "./lightbox/time";
import styles from "./calls-drawer.module.css";

export function CallsDrawer({
  id,
  title,
  meta,
  status,
  tone,
  insight,
  readState,
  onRetry,
  hasReport,
  canRename,
  onOpen,
  onRename,
  onClose,
}: {
  id: string;
  title: string;
  meta: string;
  status: string;
  tone: string;
  insight: CallInsight | null;
  readState: InsightReadState;
  onRetry: () => void;
  hasReport: boolean;
  canRename: boolean;
  onOpen: () => void;
  onRename: () => void;
  onClose: () => void;
}) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const drawer = useRef<HTMLElement | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const previous = document.activeElement;
    closeButton.current?.focus();
    const containFocus = (event: FocusEvent) => {
      if (
        event.target instanceof Node &&
        !drawer.current?.contains(event.target)
      )
        closeButton.current?.focus();
    };
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("focusin", containFocus);
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        drawer.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], audio[controls], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter(
        (element) =>
          !element.closest("[hidden], [inert]") &&
          getComputedStyle(element).display !== "none" &&
          getComputedStyle(element).visibility !== "hidden",
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function play(startMs: number) {
    const element = audio.current;
    if (!element) return;
    element.currentTime = startMs / 1000;
    void element.play().catch(() => undefined);
  }

  async function copyLink() {
    const link = `${window.location.origin}${callHref(id)}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <>
      <div className={styles.scrim} onClick={onClose} aria-hidden="true" />
      <aside
        ref={drawer}
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-label={`Call preview: ${title}`}
      >
        <header className={styles.drawerHead}>
          <div className={styles.drawerTitle}>
            <strong>{title}</strong>
            <span>{meta}</span>
          </div>
          <button
            ref={closeButton}
            type="button"
            className={styles.iconButton}
            onClick={onClose}
            aria-label="Close preview"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className={styles.drawerBody}>
          <div className={styles.drawerStatus}>
            <span className={styles.statusChip} data-tone={tone}>
              {status}
            </span>
            {insight?.callType ? (
              <span className={styles.typeChip}>
                {insight.callType.replace(/_/g, " ")}
              </span>
            ) : null}
          </div>

          {hasReport ? (
            <audio
              ref={audio}
              className={styles.audio}
              controls
              preload="none"
              src={audioSource(id)}
            />
          ) : null}

          {insight?.assessment ? (
            <section className={styles.drawerBlock}>
              <h3>
                <Target size={14} aria-hidden="true" /> Assessment
              </h3>
              <p>{insight.assessment}</p>
            </section>
          ) : null}

          {insight?.fixFirst ? (
            <section className={styles.drawerBlock} data-kind="fix">
              <h3>
                <Wrench size={14} aria-hidden="true" /> Fix first
              </h3>
              <p>{insight.fixFirst}</p>
            </section>
          ) : null}

          {insight?.nextFocus ? (
            <section className={styles.drawerBlock} data-kind="next">
              <h3>
                <CalendarCheck size={14} aria-hidden="true" /> Next call focus
              </h3>
              <p>{insight.nextFocus}</p>
            </section>
          ) : null}

          {insight && insight.moments.length > 0 ? (
            <section className={styles.drawerBlock}>
              <h3>
                <Play size={14} aria-hidden="true" /> Listen to these
              </h3>
              <ul className={styles.moments}>
                {insight.moments.map((moment) => (
                  <li key={`${moment.startMs}-${moment.label}`}>
                    <button
                      type="button"
                      className={styles.momentButton}
                      onClick={() => play(moment.startMs)}
                    >
                      <span className={styles.momentTime}>
                        <Play size={12} aria-hidden="true" />
                        {formatClock(moment.startMs)}
                      </span>
                      <span className={styles.momentLabel}>{moment.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {insight && insight.speakers.length > 0 ? (
            <section className={styles.drawerBlock}>
              <h3>Talk split</h3>
              <div className={styles.split} aria-hidden="true">
                {insight.speakers.map((speaker, index) => (
                  <span
                    key={index}
                    style={{ flex: Math.max(0.02, speaker.share) }}
                    data-index={index % 4}
                  />
                ))}
              </div>
              <ul className={styles.splitLegend}>
                {insight.speakers.map((speaker, index) => (
                  <li key={index} data-index={index % 4}>
                    Voice {index + 1} · {Math.round(speaker.share * 100)}% ·{" "}
                    {speaker.questions} questions
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {insight ? (
            <section className={styles.signalsRow}>
              <span title="Next steps and commitments">
                <Handshake size={14} aria-hidden="true" />
                {insight.signals.commitments ?? "—"}
              </span>
              <span title="Concerns">
                <MessageCircleQuestion size={14} aria-hidden="true" />
                {insight.signals.concerns ?? "—"}
              </span>
              <span title="Business details">
                <FolderOpen size={14} aria-hidden="true" />
                {insight.signals.business ?? "—"}
              </span>
              <span title="Questions asked">
                <MessageCircleQuestion size={14} aria-hidden="true" />
                {insight.questions ?? "—"}
              </span>
              <span title="Strengths and missed chances">
                {insight.strengths ?? "—"} strengths · {insight.missed ?? "—"}{" "}
                missed
              </span>
            </section>
          ) : hasReport ? (
            <p className={styles.drawerLoading}>
              {readState === "error"
                ? "This report could not be read."
                : readState === "unavailable"
                  ? "Report insights unavailable."
                  : "Reading this call’s report…"}
            </p>
          ) : null}
          {hasReport && readState === "error" ? (
            <button
              type="button"
              className={styles.ghostButton}
              onClick={onRetry}
            >
              Retry report
            </button>
          ) : null}
        </div>

        <footer className={styles.drawerFoot}>
          <button type="button" className="primary-button" onClick={onOpen}>
            {hasReport ? "Open full report" : "View progress"}{" "}
            <ArrowRight size={15} aria-hidden="true" />
          </button>
          {canRename ? (
            <button
              type="button"
              className={styles.ghostButton}
              onClick={onRename}
            >
              <Pencil size={14} aria-hidden="true" /> Rename
            </button>
          ) : null}
          <button
            type="button"
            className={styles.ghostButton}
            onClick={() => void copyLink()}
          >
            {copied ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              <Copy size={14} aria-hidden="true" />
            )}{" "}
            {copied ? "Copied" : "Copy link"}
          </button>
        </footer>
      </aside>
    </>
  );
}
