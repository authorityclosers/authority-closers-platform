"use client";

/* Calls workspace preview drawer (AUT-999 v2): the call at a glance, its key
   moments playable in place, and the next step, without leaving the list.
   Design system v2 (20 Oct): it is the kit Sheet, so a phone swipes it away
   and a computer gets the right-side panel; focus, Escape and the dimmed
   page are the sheet's. */
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
} from "lucide-react";
import { useRef, useState } from "react";

import { callHref } from "./acquisition-client";
import {
  audioSource,
  type CallInsight,
  type InsightReadState,
} from "./calls-insights";
import { formatClock } from "./lightbox/time";
import { Button } from "./ui/kit";
import { Sheet } from "./ui/sheet";
import styles from "./calls-drawer.module.css";

export function CallsDrawer({
  open = true,
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
  /** False while it slides away; the call stays on it until then. */
  open?: boolean;
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
  const [copied, setCopied] = useState(false);

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
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      description={meta}
      wide="right"
      className={styles.sheet}
      footer={
        <div className={styles.drawerFoot}>
          <Button
            variant="primary"
            className={styles.openButton}
            onClick={onOpen}
          >
            {hasReport ? "Open full report" : "View progress"}{" "}
            <ArrowRight size={15} aria-hidden="true" />
          </Button>
          {canRename ? (
            <Button className={styles.footButton} onClick={onRename}>
              <Pencil size={14} aria-hidden="true" /> Rename
            </Button>
          ) : null}
          <Button className={styles.footButton} onClick={() => void copyLink()}>
            {copied ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              <Copy size={14} aria-hidden="true" />
            )}{" "}
            {copied ? "Copied" : "Copy link"}
          </Button>
        </div>
      }
    >
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
            data-sheet-no-drag=""
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
    </Sheet>
  );
}
