"use client";

import { useId, type ReactNode } from "react";

/** Evidence and playback actions stay visible beside the finding in either view. */
export function FindingEvidence({
  count,
  children,
}: {
  count: number;
  children: ReactNode;
}) {
  const headingId = useId();
  if (!count) return null;
  return (
    <div
      className="studio-finding-evidence"
      role="group"
      aria-labelledby={headingId}
    >
      <p id={headingId} className="studio-finding-evidence-heading">
        <strong>Evidence from this call</strong>{" "}
        <span>
          {count} {count === 1 ? "moment" : "moments"}
        </span>
      </p>
      {children}
    </div>
  );
}
