"use client";

import {
  Clock3,
  Download,
  Ellipsis,
  Link2,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

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
  /** An optional picture of the call (the call map) below the title. */
  visual?: ReactNode;
  /**
   * A compact version of the visual. Once the full one scrolls under the
   * pinned title row, this one grows into the space beside the title.
   */
  compactVisual?: ReactNode;
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
 * The report header: a pinned row with the title, measured facts and one
 * overflow menu (actions and provenance), then the call map below it. When
 * the map scrolls under the row, a compact map takes its place in the row.
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
  visual,
  compactVisual,
}: ReportHeaderProps) {
  const menu = useRef<HTMLDetailsElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const visualBox = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);
  const hasCompact = Boolean(visual && compactVisual);
  const [renaming, setRenaming] = useState(false);
  const [copied, setCopied] = useState(false);
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

  // Compact once the full call map has slid (mostly) under the pinned row.
  useEffect(() => {
    const target = visualBox.current;
    const header = bar.current;
    if (!hasCompact || !target || !header) return;
    if (typeof IntersectionObserver === "undefined") return;
    let root: HTMLElement | null = null;
    for (let node = target.parentElement; node; node = node.parentElement) {
      const { overflowY } = window.getComputedStyle(node);
      if (overflowY === "auto" || overflowY === "scroll") {
        root = node;
        break;
      }
    }
    let observer: IntersectionObserver | null = null;
    const watch = () => {
      observer?.disconnect();
      const inset = Math.round(header.getBoundingClientRect().height);
      observer = new IntersectionObserver(
        ([entry]) => {
          if (!entry) return;
          const top = entry.rootBounds?.top ?? 0;
          setCompact(
            entry.intersectionRatio < 0.4 &&
              entry.boundingClientRect.top < top + inset,
          );
        },
        {
          root,
          rootMargin: `-${inset}px 0px 0px 0px`,
          threshold: [0, 0.2, 0.4, 0.6, 1],
        },
      );
      observer.observe(target);
    };
    watch();
    const resize =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(watch);
    resize?.observe(header);
    return () => {
      observer?.disconnect();
      resize?.disconnect();
    };
  }, [hasCompact]);

  return (
    <>
      <div
        ref={bar}
        className={styles.reportHeader}
        data-report-sticky
        data-compact={compact ? "true" : undefined}
      >
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
              <h1
                onDoubleClick={canRename ? () => setRenaming(true) : undefined}
                title={canRename ? "Double-click to rename" : undefined}
              >
                {title}
              </h1>
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
        {hasCompact ? (
          <div
            className={styles.reportCompact}
            aria-hidden={!compact}
            inert={!compact}
          >
            {compactVisual}
          </div>
        ) : null}
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
          {/* Every action lives in one calm menu; "New analysis" is in the app header. */}
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
              {canRename ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={(event) => {
                    closeMenu(event);
                    setRenaming(true);
                  }}
                >
                  <Pencil size={16} aria-hidden="true" />
                  Rename call
                </button>
              ) : null}
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
                <small>.docx</small>
              </button>
              <button
                type="button"
                onClick={(event) => {
                  const url = new URL(window.location.href);
                  const call = url.searchParams.get("call");
                  url.search = "";
                  if (call) url.searchParams.set("call", call);
                  void navigator.clipboard
                    ?.writeText(url.toString())
                    .then(() => {
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1200);
                    })
                    .catch(() => {});
                  closeMenu(event);
                }}
              >
                <Link2 size={16} aria-hidden="true" />
                {copied ? "Link copied" : "Copy link"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={(event) => {
                  closeMenu(event);
                  onAnalyseAnother();
                }}
              >
                <Plus size={16} aria-hidden="true" />
                Analyse another call
              </button>
              <details className={styles.reportAbout}>
                <summary>
                  <ShieldCheck size={16} aria-hidden="true" />
                  About this report
                </summary>
                <p>
                  {claimed ? "Private to your account. " : ""}Draft coaching;
                  not adjudicated by Dipak. Speaker labels are unverified.
                  Original quotes are preserved in the language spoken.
                </p>
                <p>
                  Source: {sourceLabel}. Measured duration:{" "}
                  {formatClock(durationMs)}.
                </p>
                <p>
                  Need the call removed?{" "}
                  <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20deletion%20request">
                    Contact the AC team.
                  </a>
                </p>
              </details>
              {canRequestDeletion && (
                <>
                  <span
                    className={styles.reportMenuSeparator}
                    aria-hidden="true"
                  />
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
                </>
              )}
            </div>
          </details>
        </div>
      </div>
      {visual ? (
        <div ref={visualBox} className={styles.reportVisual}>
          {visual}
        </div>
      ) : null}
    </>
  );
}
