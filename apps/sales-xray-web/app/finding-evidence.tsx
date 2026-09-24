"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useReportReading } from "./report-reading-context";

/** Keep full source quotations available without crowding the finding itself. */
export function FindingEvidence({
  count,
  children,
}: {
  count: number;
  children: ReactNode;
}) {
  const reading = useReportReading();
  const details = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (details.current) details.current.open = reading;
  }, [reading]);
  useEffect(() => {
    let previous: boolean | null = null;
    const beforePrint = () => {
      if (!details.current || previous !== null) return;
      previous = details.current.open;
      details.current.open = true;
    };
    const afterPrint = () => {
      if (details.current && previous !== null) details.current.open = previous;
      previous = null;
    };
    window.addEventListener("beforeprint", beforePrint);
    window.addEventListener("afterprint", afterPrint);
    return () => {
      window.removeEventListener("beforeprint", beforePrint);
      window.removeEventListener("afterprint", afterPrint);
      afterPrint();
    };
  }, []);
  if (!count) return null;
  return (
    <details ref={details} className="studio-finding-evidence">
      <summary>
        Listen &amp; read evidence{" "}
        <span>
          {count} {count === 1 ? "moment" : "moments"}
        </span>
      </summary>
      {children}
    </details>
  );
}
