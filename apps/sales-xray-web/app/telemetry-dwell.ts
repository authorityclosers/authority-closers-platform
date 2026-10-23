"use client";

/**
 * How long a Report section is read (owner, 22 Oct 2026: optimise on how people use the
 * app; the cost optimiser reads which sections are read). A section counts while it
 * crosses the middle band of the screen and the page is shown; one `sx.section_read`
 * carries the time when the section unmounts, the call changes or the page is hidden.
 * Reads under a second (a section scrolled past) are not sent.
 *
 * Usage, in a section's component:
 *   const dwell = useSectionDwell("analysis", { callId, look: "brain4" });
 *   return <section ref={dwell}>…</section>;
 */
import { useEffect, useState } from "react";

import {
  readBand,
  telemetry,
  track,
  type ReportLookName,
  type SkillKey,
  type TelemetrySection,
} from "./telemetry";

/** Shortest read that is sent, and the longest one counted. */
export const MIN_READ_MS = 1_000;
export const MAX_READ_MS = 600_000;

/** The section is "being read" while it crosses this middle band of the screen. */
const READING_BAND = "-40% 0px -40% 0px";

/** Time a section was readable, across any number of times it came and went. */
export class DwellClock {
  private since: number | null = null;
  private total = 0;

  constructor(private readonly now: () => number) {}

  /** The section starts (true) or stops (false) being readable. */
  set(readable: boolean) {
    const at = this.now();
    if (readable && this.since === null) this.since = at;
    else if (!readable && this.since !== null) {
      this.total += at - this.since;
      this.since = null;
    }
  }

  /** The time read so far, capped; counting starts again from zero. */
  take(): number {
    const at = this.now();
    let total = this.total;
    if (this.since !== null) {
      total += at - this.since;
      this.since = at;
    }
    this.total = 0;
    return Math.min(Math.max(0, Math.round(total)), MAX_READ_MS);
  }
}

type DwellContext = Readonly<{
  /** The report's call id; nothing is sent without one. */
  callId: string | null;
  skill?: SkillKey;
  look?: ReportLookName;
}>;

/** A ref callback for a Report section; it sends one `sx.section_read` per read. */
export function useSectionDwell(
  section: TelemetrySection,
  { callId, skill, look }: DwellContext,
): (element: Element | null) => void {
  const [element, setElement] = useState<Element | null>(null);

  useEffect(() => {
    if (!element || !callId || typeof IntersectionObserver === "undefined")
      return;
    const clock = new DwellClock(() => performance.now());
    const shown = () => document.visibilityState !== "hidden";
    let inBand = false;

    const send = () => {
      const milliseconds = clock.take();
      if (milliseconds < MIN_READ_MS) return;
      track("sx.section_read", {
        call_id: callId,
        section,
        read_band: readBand(milliseconds),
        dwell_ms: milliseconds,
        ...(skill ? { skill } : {}),
        ...(look ? { look } : {}),
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        const latest = entries[entries.length - 1];
        if (!latest) return;
        inBand = latest.isIntersecting;
        clock.set(inBand && shown());
      },
      { rootMargin: READING_BAND, threshold: 0 },
    );
    observer.observe(element);

    const onVisibility = () => {
      if (shown()) {
        clock.set(inBand);
        return;
      }
      clock.set(false);
      send();
      // The page may not come back: send what is queued now.
      void telemetry.flush(true);
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      clock.set(false);
      send();
    };
  }, [element, section, callId, skill, look]);

  return setElement;
}
