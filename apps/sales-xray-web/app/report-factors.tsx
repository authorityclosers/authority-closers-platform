"use client";

import { useEffect, useRef } from "react";
import type { ReportDimension } from "./report-contract";
import { getReportUiCopy, type ReportDisplayLanguage } from "./report-ui-copy";
import styles from "./report-factors.module.css";

export function ReportFactors({
  dimensions,
  language = "en",
}: {
  dimensions: ReportDimension[];
  language?: ReportDisplayLanguage;
}) {
  const copy = getReportUiCopy(language);
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
      aria-label={copy.factorsLabel}
    >
      <h2>{copy.factorsTitle}</h2>
      <p className={styles.note}>{copy.factorsNote}</p>
      <div className={styles.grid}>
        {dimensions.map((dimension) => (
          <details key={dimension.dimension_id} className={styles.factor}>
            <summary>
              <span>{dimension.label}</span>
              <small>
                {copy.factorStatus[dimension.status] ??
                  copy.factorStatus.unknown}
              </small>
            </summary>
            <p>{dimension.observation}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
