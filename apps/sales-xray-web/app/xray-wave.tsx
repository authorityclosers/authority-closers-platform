"use client";

import type { CSSProperties } from "react";

import styles from "./xray-wave.module.css";

// A decorative x-ray of a conversation. It shows what the analysis looks for,
// never a finding: bars are a fixed pattern (identical on server and client),
// the scan runs only while a stage is confirmed running, and otherwise the
// wave rests or breathes.
const BAR_COUNT = 72;
const SWEEP_SECONDS = 4.8;
const BARS = Array.from({ length: BAR_COUNT }, (_, index) => {
  const envelope = Math.abs(Math.sin(index * 0.19) * Math.cos(index * 0.043));
  const grain = ((index * 37) % 11) / 11;
  return Math.round(14 + 78 * (0.28 + 0.72 * envelope) * (0.6 + 0.4 * grain));
});
const TURNS = [0, 11, 24, 36, 49, 60] as const;
const MOMENTS = [
  { kind: "strength", from: 8, to: 11 },
  { kind: "objection", from: 27, to: 30 },
  { kind: "missed", from: 43, to: 46 },
  { kind: "next", from: 62, to: 65 },
] as const;
export const XRAY_LOOKING_FOR = [
  { kind: "strength", label: "Strong moments" },
  { kind: "objection", label: "Objections" },
  { kind: "missed", label: "Missed opportunities" },
  { kind: "next", label: "Next steps" },
] as const;

function delay(index: number) {
  return `${((index + 0.5) / BAR_COUNT) * SWEEP_SECONDS}s`;
}

export function XrayWave({
  mode,
  legend = true,
}: {
  /** scanning: a stage is confirmed running; resting: waiting or checking;
   *  still: paused, needs attention, hidden or offline. */
  mode: "scanning" | "resting" | "still";
  legend?: boolean;
}) {
  return (
    <div className={styles.xray} data-mode={mode}>
      <div className={styles.track} aria-hidden="true">
        {BARS.map((height, index) => {
          const moment = MOMENTS.find(
            (item) => index >= item.from && index <= item.to,
          );
          return (
            <span
              key={index}
              className={styles.bar}
              data-speaker={
                TURNS.filter((turn) => turn <= index).length % 2 ? "a" : "b"
              }
              data-kind={moment?.kind}
              style={
                {
                  "--h": `${height}%`,
                  "--d": delay(index),
                  "--i": index,
                } as CSSProperties
              }
            />
          );
        })}
        <span className={styles.beam} />
      </div>
      {legend && (
        <p className={styles.legend}>
          <span className={styles.legendLead}>Looking for</span>
          {XRAY_LOOKING_FOR.map((item) => (
            <span key={item.kind} className={styles.chip} data-kind={item.kind}>
              <i aria-hidden="true" />
              {item.label}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
