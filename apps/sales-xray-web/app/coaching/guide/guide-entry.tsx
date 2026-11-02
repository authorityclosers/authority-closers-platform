"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";

import summaryFile from "./content-summary.json";
import { parseSummary, summaryHint, type GuideSummary } from "./guide-content";
import { GUIDE } from "./guide-view";
import styles from "./guide.module.css";

const SUMMARY = parseSummary(summaryFile);

/**
 * The Coaching page's one row into Dipak's answers. It reads the small
 * summary bundled with the page, so it is there on the first paint, and it
 * draws nothing until real content is loaded.
 */
export function GuideEntry({
  summary = SUMMARY,
}: {
  summary?: GuideSummary | null;
}) {
  if (!summary?.shown) return null;
  return (
    <Link className={styles.entry} href="/coaching/guide">
      <span className={styles.face} aria-hidden="true" />
      <span>
        <strong>{GUIDE.title}</strong>
        <small>{summaryHint(summary)}</small>
      </span>
      <ChevronRight size={18} aria-hidden="true" />
    </Link>
  );
}
