"use client";

import {
  ArrowRight,
  Clock3,
  Download,
  Ellipsis,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type MouseEvent } from "react";

import { callTitle, type CallLabel } from "./call-label";
import { CallLabelEditor, RenameCallButton } from "./call-label-editor";
import { formatClock } from "./lightbox/time";
import styles from "./acquisition-studio.module.css";

export type ReportHeaderProps = {
  /** Measured recording duration from the saved transcript. */
  durationMs: number;
  /** Shown only when the saved plan binds a language to this report run. */
  languageLabel?: string | null;
  /** The saved source label; kept for audit in the collapsed details. */
  sourceLabel: string;
  /** True once the report is saved to a signed-in account. */
  claimed: boolean;
  busy: boolean;
  /** Download needs a saved submission. */
  canDownload: boolean;
  /** Deletion is offered only for a saved submission. */
  canRequestDeletion: boolean;
  deletionDisabled: boolean;
  onAnalyseAnother: () => void;
  onDownload: () => void;
  onRequestDeletion: () => void;
  /** Server-confirmed owner call name (C1); null/absent on older servers. */
  label?: CallLabel | null;
  /** Rename wiring; offered only for a claimed call with a server label. */
  rename?: {
    save: (
      displayName: string | null,
      revision: number,
      signal: AbortSignal,
    ) => Promise<CallLabel>;
    refresh: (signal: AbortSignal) => Promise<CallLabel | null>;
    confirmed: (label: CallLabel) => void;
  };
};

function closeMenu(event: MouseEvent<HTMLElement>) {
  event.currentTarget.closest("details")?.removeAttribute("open");
}

/**
 * The compact report header: title and measured facts, one primary action,
 * secondary actions in an overflow, and provenance in a collapsed disclosure.
 */
export function ReportHeader({
  durationMs,
  languageLabel,
  sourceLabel,
  claimed,
  busy,
  canDownload,
  canRequestDeletion,
  deletionDisabled,
  onAnalyseAnother,
  onDownload,
  onRequestDeletion,
  label = null,
  rename,
}: ReportHeaderProps) {
  const menu = useRef<HTMLDetailsElement>(null);
  const [renaming, setRenaming] = useState(false);
  const title = callTitle(label, "Sales call report");
  const canRename = claimed && label !== null && rename !== undefined;

  useEffect(() => {
    const dismissOutside = (event: Event) => {
      const details = menu.current;
      if (
        details?.open &&
        event.target instanceof Node &&
        !details.contains(event.target)
      )
        details.open = false;
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("focusin", dismissOutside);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("focusin", dismissOutside);
    };
  }, []);

  return (
    <>
      <div className={styles.reportHeader}>
        <div className={styles.reportHeading}>
          {renaming && canRename && label ? (
            <CallLabelEditor
              label={label}
              onSave={rename.save}
              onRefresh={rename.refresh}
              onConfirmed={rename.confirmed}
              onClose={() => setRenaming(false)}
            />
          ) : (
            <div className={styles.reportTitleRow}>
              <h1>{title}</h1>
              {canRename ? (
                <RenameCallButton
                  callTitle={title}
                  onClick={() => setRenaming(true)}
                />
              ) : null}
            </div>
          )}
          <p className={styles.reportMetadata}>
            <span>
              <Clock3 size={14} aria-hidden="true" />
              {formatClock(durationMs)}
            </span>
            {languageLabel ? (
              <span>Report language: {languageLabel}</span>
            ) : null}
            <span className={styles.reportDraft}>Draft coaching</span>
          </p>
        </div>
        <div
          className={styles.reportActions}
          role="group"
          aria-label="Report actions"
        >
          {!claimed && (
            <Link className={styles.reportAction} href="/login">
              Sign in to save
            </Link>
          )}
          <button
            className={`${styles.reportAction} ${styles.reportActionPrimary}`}
            type="button"
            disabled={busy}
            onClick={onAnalyseAnother}
          >
            <ArrowRight size={16} aria-hidden="true" />
            Analyse another call
          </button>
          {/* Secondary actions stay reachable without crowding the report. */}
          <details
            ref={menu}
            className={styles.reportMore}
            onKeyDown={(event) => {
              if (event.key !== "Escape" || !event.currentTarget.open) return;
              event.preventDefault();
              event.stopPropagation();
              event.currentTarget.open = false;
              event.currentTarget.querySelector("summary")?.focus();
            }}
          >
            <summary
              className={styles.reportAction}
              aria-label="More report actions"
              title="More report actions"
            >
              <Ellipsis size={18} aria-hidden="true" />
            </summary>
            <div className={styles.reportMenu}>
              <button
                type="button"
                disabled={busy || !canDownload}
                onClick={(event) => {
                  closeMenu(event);
                  onDownload();
                }}
              >
                <Download size={16} aria-hidden="true" />
                Download report
              </button>
              {canRequestDeletion && (
                <button
                  type="button"
                  className={styles.reportMenuSupport}
                  disabled={busy || deletionDisabled}
                  onClick={(event) => {
                    closeMenu(event);
                    onRequestDeletion();
                  }}
                >
                  <Trash2 size={16} aria-hidden="true" />
                  Request deletion
                </button>
              )}
            </div>
          </details>
        </div>
      </div>
      <details className={styles.reportDisclosure}>
        <summary>
          <ShieldCheck size={14} aria-hidden="true" />
          {claimed
            ? "Private to your account · Source details"
            : "Source details"}
        </summary>
        <p>
          Draft coaching; not adjudicated by Dipak. Speaker labels are
          unverified. Original quotes are preserved in the language spoken.
        </p>
        <p>
          Source: {sourceLabel}. Measured duration: {formatClock(durationMs)}.
        </p>
        <p>
          Need the call removed?{" "}
          <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20deletion%20request">
            Contact the AC team.
          </a>
        </p>
      </details>
    </>
  );
}
