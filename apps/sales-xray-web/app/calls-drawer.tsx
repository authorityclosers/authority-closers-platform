"use client";

/* Calls workspace preview drawer (AUT-999 v2): the call at a glance, its key
   moments playable in place, and the next step, without leaving the list. */
import {
  ArrowRight,
  CalendarCheck,
  Check,
  Copy,
  Handshake,
  IndianRupee,
  MessageCircleQuestion,
  Pencil,
  Play,
  Target,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { callHref } from "./acquisition-client";
import { audioSource, type CallInsight } from "./calls-insights";
import { formatClock } from "./lightbox/time";
import styles from "./calls-library.module.css";

export function CallsDrawer({
  id,
  title,
  meta,
  status,
  tone,
  insight,
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
  hasReport: boolean;
  canRename: boolean;
  onOpen: () => void;
  onRename: () => void;
  onClose: () => void;
}) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
              <span title="Promises made">
                <Handshake size={14} aria-hidden="true" />
                {insight.signals.promises}
              </span>
              <span title="Next steps">
                <CalendarCheck size={14} aria-hidden="true" />
                {insight.signals.nextStep}
              </span>
              <span title="Money talked about">
                <IndianRupee size={14} aria-hidden="true" />
                {insight.signals.money}
              </span>
              <span title="Questions asked">
                <MessageCircleQuestion size={14} aria-hidden="true" />
                {insight.questions ?? 0}
              </span>
              <span title="Strengths and missed chances">
                {insight.strengths} strengths · {insight.missed} missed
              </span>
            </section>
          ) : hasReport ? (
            <p className={styles.drawerLoading}>Reading this call’s report…</p>
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
