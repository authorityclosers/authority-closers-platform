"use client";

/**
 * Home's metric pages (owner, 31 Oct 2026: "a metric slider"): on a phone the
 * cards are page one and a swipe brings the next, its figures rising in.
 * Native scroll-snap carries the momentum; the dots show where you are and
 * move you. Every page is the same 2x2 shape, so the slider is exactly as
 * tall as its cards. From 1024 px every page shows at once, one row each,
 * titled. No motion when the person asks for less.
 */

import Link from "next/link";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { breakLength } from "./home-today";
import styles from "./metric-pager.module.css";

export type Page = { key: string; label: string; content: ReactNode };

export function MetricPager({
  pages,
  label,
}: {
  pages: Page[];
  label: string;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(0);
  useEffect(() => {
    const node = track.current;
    if (!node) return;
    const onScroll = () => {
      const width = node.clientWidth || 1;
      setPage(
        Math.max(
          0,
          Math.min(pages.length - 1, Math.round(node.scrollLeft / width)),
        ),
      );
    };
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, [pages.length]);
  const go = (index: number) => {
    const node = track.current;
    if (!node) return;
    setPage(index);
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    node.scrollTo({
      left: index * node.clientWidth,
      behavior: reduce ? "auto" : "smooth",
    });
  };
  return (
    <section
      className={styles.pager}
      aria-roledescription="carousel"
      aria-label={label}
    >
      <div ref={track} className={styles.track}>
        {pages.map((item, index) => (
          <div
            key={item.key}
            className={styles.page}
            aria-roledescription="slide"
            aria-label={`${index + 1} of ${pages.length}: ${item.label}`}
            data-active={index === page || undefined}
          >
            {pages.length > 1 ? (
              <h3 className={styles.pageTitle}>{item.label}</h3>
            ) : null}
            {item.content}
          </div>
        ))}
      </div>
      {pages.length > 1 ? (
        <div
          className={styles.dots}
          role="tablist"
          aria-label={`${label}, pages`}
        >
          {pages.map((item, index) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={index === page}
              aria-label={item.label}
              className={styles.dot}
              onClick={() => go(index)}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** One figure: a big number and what it is. */
export type More = {
  label: string;
  value: string | null;
  /** A second line: the other side's figure. */
  note?: string;
  /** Needs someone: the number goes red, with a small dot. */
  red?: boolean;
  /** The exact list behind the number, one tap away. */
  href?: string;
  /** What the number means, on hover (computers). */
  help?: string;
  /** For tests and the screen's own links. */
  key?: string;
};

export function MoreFigures({ figures }: { figures: More[] }) {
  return (
    <ul className={styles.more}>
      {figures.map((figure, index) => {
        const body = (
          <>
            <span className={styles.figureLabel}>{figure.label}</span>
            <strong aria-busy={figure.value === null || undefined}>
              {figure.value === null ? " " : <Count value={figure.value} />}
            </strong>
            {figure.note ? (
              <span className={styles.figureNote}>{figure.note}</span>
            ) : null}
          </>
        );
        const look = {
          className: styles.figure,
          "data-red": figure.red || undefined,
          "data-figure": figure.key,
          title: figure.help,
          style: { "--i": index } as CSSProperties,
        };
        return (
          <li key={figure.key ?? figure.label}>
            {figure.href ? (
              <Link href={figure.href} {...look}>
                {body}
              </Link>
            ) : (
              <div {...look}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * A number that counts up to its value (owner, 31 Oct 2026: "numbers count
 * up"), from where it was or from 0, in 0.7 s; text that is not a number, and
 * every number for someone who asks for less motion, shows at once. The span
 * is written directly, so React never holds a stale text node.
 */
export function Count({ value }: { value: string }) {
  const node = useRef<HTMLSpanElement>(null);
  const last = useRef<number | null>(null);
  useLayoutEffect(() => {
    const element = node.current;
    if (!element) return;
    const match = /^(\d+)(.*)$/.exec(value);
    const from = last.current;
    const target = match ? Number(match[1]) : null;
    last.current = target;
    const still =
      target === null ||
      from === target ||
      // Tests read the figure, not the motion.
      process.env.NODE_ENV === "test" ||
      typeof window.matchMedia !== "function" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !match) {
      element.textContent = value;
      return;
    }
    const start = from ?? 0;
    const rest = match[2];
    const began = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - began) / 700);
      const eased = 1 - (1 - t) ** 3;
      element.textContent = `${Math.round(start + (target - start) * eased)}${rest}`;
      if (t < 1) frame = requestAnimationFrame(step);
    };
    element.textContent = `${start}${rest}`;
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      element.textContent = value;
    };
  }, [value]);
  return <span ref={node} />;
}

export const share = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";

export const minutes = (seconds: number) =>
  breakLength(Math.round(seconds / 60));
