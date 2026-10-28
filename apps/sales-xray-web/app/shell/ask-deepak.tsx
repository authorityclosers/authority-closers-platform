"use client";

/**
 * Ask Deepak (28 Oct 2026 meeting, "What the meeting decided"): the tab bar's
 * middle slot, with Deepak's face, where the + used to be. Answers will come
 * from Deepak's approved answer library (plan phase 6); until that ships, the
 * sheet says so plainly and opens what exists today, Coaching. It never shows
 * an invented answer.
 */

import { ChevronRight, GraduationCap } from "lucide-react";
import Link from "next/link";

import { Sheet } from "../ui/sheet";
import styles from "./ask-deepak.module.css";

export function AskDeepakSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Ask Deepak" wide="center">
      <div className={styles.body}>
        <span className={styles.face} aria-hidden="true" />
        <p className={styles.lead}>
          Ask Deepak what to say next: a price push-back, a lead who has gone
          quiet, how to open a call.
        </p>
        <p className={styles.soon}>
          Deepak&rsquo;s answers are coming here soon. Until then, his coaching
          on your own calls is in Coaching.
        </p>
        <Link className={styles.open} href="/coaching" onClick={onClose}>
          <GraduationCap size={18} aria-hidden="true" />
          <span>Open coaching</span>
          <ChevronRight size={18} aria-hidden="true" />
        </Link>
      </div>
    </Sheet>
  );
}
