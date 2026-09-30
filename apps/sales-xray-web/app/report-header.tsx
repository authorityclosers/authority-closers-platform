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

type Box = { left: number; top: number; width: number; height: number };
/** Where the full waveform is and where its compact copy lands. */
type Fold = {
  /** Scroll offset when measured. */
  scrollTop: number;
  /** Scroll offset where the full waveform's top meets the pinned row. */
  start: number;
  /** Scroll distance the fold takes. */
  distance: number;
  source: Box;
  slot: Box;
};
type ScrollTimelineCtor = new (options: {
  source: Element;
  axis?: "block" | "inline";
}) => AnimationTimeline;

/** Path samples; the error between samples stays far below a pixel. */
const FOLD_STEPS = 24;

function clamp(value: number) {
  return Math.min(1, Math.max(0, value));
}

function scrollParent(node: HTMLElement): HTMLElement | null {
  for (let parent = node.parentElement; parent; parent = parent.parentElement) {
    const { overflowY } = window.getComputedStyle(parent);
    if (overflowY === "auto" || overflowY === "scroll") return parent;
  }
  return null;
}

/**
 * The compact copy's transform at fold progress p: at 0 it covers the full
 * waveform exactly (which by then has scrolled p·distance further up); at 1
 * it sits in its slot untouched.
 */
function foldTransform(fold: Fold, p: number) {
  const scrolled = fold.start + p * fold.distance - fold.scrollTop;
  const sourceTop = fold.source.top - scrolled;
  const left = fold.source.left + (fold.slot.left - fold.source.left) * p;
  const top = sourceTop + (fold.slot.top - sourceTop) * p;
  const width = fold.source.width + (fold.slot.width - fold.source.width) * p;
  const height =
    fold.source.height + (fold.slot.height - fold.source.height) * p;
  return `translate(${left - fold.slot.left}px, ${top - fold.slot.top}px) scale(${width / fold.slot.width}, ${height / fold.slot.height})`;
}

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
  const [copyFailed, setCopyFailed] = useState(false);
  const title = callTitle(label, "Untitled call");
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

  // The full waveform folds into the pinned row pixel for pixel. The moment
  // its top meets the row, it hands over to the compact copy (drawn bar for
  // bar the same), placed exactly on top of it; the copy then travels and
  // shrinks along the measured path into its slot. A scroll timeline drives
  // this on the compositor, so it can never lag the page; browsers without
  // scroll timelines get the same path set on each scroll event.
  useEffect(() => {
    const visual = visualBox.current;
    const header = bar.current;
    if (!hasCompact || !visual || !header) return;
    const scroller = scrollParent(visual);
    if (!scroller) return;
    const Timeline = (globalThis as { ScrollTimeline?: ScrollTimelineCtor })
      .ScrollTimeline;
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let animations: Animation[] = [];
    let fold: Fold | null = null;
    let frame = 0;
    // The scroll timeline's path is laid out in fractions of this range, so
    // any change in the report's height (views, tabs, late content) rebuilds.
    let builtRange = -1;

    function schedule() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(build);
    }
    const parts = () => ({
      source: visual.querySelector<HTMLElement>("[data-morph-source]"),
      wave: visual.querySelector<HTMLElement | SVGElement>("[data-morph-wave]"),
      slot: header.querySelector<HTMLElement>("[data-morph-slot]"),
      layer: header.querySelector<HTMLElement>("[data-morph-layer]"),
      chrome: Array.from(
        header.querySelectorAll<HTMLElement | SVGElement>(
          "[data-morph-chrome]",
        ),
      ),
    });
    const progressAt = (top: number) =>
      fold ? clamp((top - fold.start) / fold.distance) : 0;

    const paint = () => {
      if (scroller.scrollHeight - scroller.clientHeight !== builtRange)
        schedule();
      const p = progressAt(scroller.scrollTop);
      const value = p.toFixed(4);
      header.style.setProperty("--fold", value);
      visual.style.setProperty("--fold", value);
      setCompact(p >= 0.999);
      if (animations.length) return;
      // No scroll timeline (or reduced motion): set the same path directly.
      const { wave, layer, chrome } = parts();
      const started = fold !== null && scroller.scrollTop >= fold.start;
      const morph = !reduce && fold !== null;
      if (layer) {
        layer.style.transform = morph && fold ? foldTransform(fold, p) : "";
        layer.style.opacity = (morph ? started : p >= 0.999) ? "1" : "0";
      }
      if (wave) wave.style.opacity = morph && started ? "0" : "";
      const shown = morph ? clamp((p - 0.6) / 0.4) : p >= 0.999 ? 1 : 0;
      for (const element of chrome) element.style.opacity = String(shown);
    };

    const build = () => {
      for (const animation of animations) animation.cancel();
      animations = [];
      const { source, wave, slot, layer, chrome } = parts();
      if (layer) layer.style.transform = "";
      if (!source || !slot || !layer) {
        fold = null;
        paint();
        return;
      }
      const port = scroller.getBoundingClientRect();
      const row = header.getBoundingClientRect();
      // Measure the slot where it sits once the row is pinned.
      const unpinned = Math.max(0, row.top - port.top - scroller.clientTop);
      const s = source.getBoundingClientRect();
      const t = slot.getBoundingClientRect();
      const rowBottom = row.bottom - unpinned;
      const scrollTop = scroller.scrollTop;
      fold = {
        scrollTop,
        start: scrollTop + (s.top - rowBottom),
        distance: Math.max(96, Math.min(200, s.height * 2.6)),
        source: { left: s.left, top: s.top, width: s.width, height: s.height },
        slot: {
          left: t.left,
          top: t.top - unpinned,
          width: t.width,
          height: t.height,
        },
      };
      const range = scroller.scrollHeight - scroller.clientHeight;
      builtRange = range;
      if (Timeline && !reduce && range > 0 && t.width > 0 && t.height > 0) {
        const current = fold;
        const at = (p: number) =>
          clamp((current.start + p * current.distance) / range);
        const begin = at(0);
        if (at(1) > begin) {
          const timeline = new Timeline({ source: scroller, axis: "block" });
          const options = { timeline, fill: "both" as const };
          const path: Keyframe[] = [
            { offset: 0, transform: foldTransform(current, 0) },
          ];
          for (let step = 0; step <= FOLD_STEPS; step += 1) {
            const p = step / FOLD_STEPS;
            path.push({ offset: at(p), transform: foldTransform(current, p) });
          }
          path.push({ offset: 1, transform: foldTransform(current, 1) });
          const swap = (from: number, to: number): Keyframe[] => [
            { offset: 0, opacity: from },
            { offset: Math.max(0, begin - 1e-6), opacity: from },
            { offset: begin, opacity: to },
            { offset: 1, opacity: to },
          ];
          animations.push(layer.animate(path, options));
          animations.push(layer.animate(swap(0, 1), options));
          if (wave) animations.push(wave.animate(swap(1, 0), options));
          const fade: Keyframe[] = [
            { offset: 0, opacity: 0 },
            { offset: at(0.6), opacity: 0 },
            { offset: at(1), opacity: 1 },
            { offset: 1, opacity: 1 },
          ];
          for (const element of chrome)
            animations.push(element.animate(fade, options));
        }
      }
      paint();
    };

    build();
    scroller.addEventListener("scroll", paint, { passive: true });
    window.addEventListener("resize", schedule);
    const resize =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(schedule);
    for (const element of [
      header,
      visual,
      visual.parentElement,
      scroller,
      ...Array.from(scroller.children),
    ])
      if (element) resize?.observe(element);
    const mutations = new MutationObserver(schedule);
    mutations.observe(visual, { childList: true, subtree: true });
    mutations.observe(header, { childList: true, subtree: true });
    return () => {
      cancelAnimationFrame(frame);
      for (const animation of animations) animation.cancel();
      scroller.removeEventListener("scroll", paint);
      window.removeEventListener("resize", schedule);
      resize?.disconnect();
      mutations.disconnect();
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
                onClick={async () => {
                  const url = new URL(window.location.href);
                  const call = url.searchParams.get("call");
                  url.search = "";
                  if (call) url.searchParams.set("call", call);
                  setCopyFailed(false);
                  setCopied(false);
                  try {
                    await navigator.clipboard.writeText(url.toString());
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1200);
                    if (menu.current) menu.current.open = false;
                  } catch {
                    setCopyFailed(true);
                  }
                }}
              >
                <Link2 size={16} aria-hidden="true" />
                {copied ? "Link copied" : "Copy link"}
              </button>
              {copyFailed && (
                <p role="alert" className={styles.reportMenuSupport}>
                  Couldn’t copy the link. Try again or copy the address from
                  your browser.
                </p>
              )}
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
