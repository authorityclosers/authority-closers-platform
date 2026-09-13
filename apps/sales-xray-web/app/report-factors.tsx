"use client";

import { useEffect, useRef } from "react";
import type { ReportDimension } from "./report-contract";
import styles from "./report-factors.module.css";

const STATUS: Record<string, string> = {
  observed: "Evidence found",
  insufficient_evidence: "Need more evidence",
  not_applicable: "Not relevant here",
  conflicted: "Mixed evidence",
  unknown: "Not assessed",
};

export function ReportFactors({
  dimensions,
}: {
  dimensions: ReportDimension[];
}) {
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    let previous: Map<HTMLDetailsElement, boolean> | null = null;
    const expandForPrint = () => {
      if (previous) return;
      previous = new Map(
        [...(section.current?.querySelectorAll("details") ?? [])].map(
          (detail) => [detail, detail.open],
        ),
      );
      previous.forEach((_, detail) => {
        detail.open = true;
      });
    };
    const restore = () => {
      previous?.forEach((open, detail) => {
        detail.open = open;
      });
      previous = null;
    };
    window.addEventListener("beforeprint", expandForPrint);
    window.addEventListener("afterprint", restore);
    return () => {
      window.removeEventListener("beforeprint", expandForPrint);
      window.removeEventListener("afterprint", restore);
      restore();
    };
  }, []);
  if (!dimensions.length) return null;
  return (
    <section
      ref={section}
      className={styles.section}
      aria-label="Sales factors"
    >
      <h2>Explore the sales factors</h2>
      <p className={styles.note}>
        Open a factor to read the draft observation. Evidence found does not
        mean a positive or negative score.
      </p>
      <div className={styles.grid}>
        {dimensions.map((dimension) => (
          <details key={dimension.dimension_id} className={styles.factor}>
            <summary>
              <span>{dimension.label}</span>
              <small>{STATUS[dimension.status] ?? "Not assessed"}</small>
            </summary>
            <p>{dimension.observation}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
