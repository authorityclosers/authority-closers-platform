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
              {figure.value ?? " "}
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

export const share = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";

export const minutes = (seconds: number) =>
  breakLength(Math.round(seconds / 60));
