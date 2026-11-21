"use client";

/**
 * A team member's call capture in one card (sx-redesign fix round, owner 21
 * Nov 2026): one status line over the days the lead desk counts, and one Fix
 * button when recordings are missing. The day-by-day list stays on Sellers'
 * phones; this never says a number it did not read.
 */

import { Mic } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { openCaptureSetup } from "../../capture-setup/capture-setup-gate";
import {
  readCaptureGuard,
  type CaptureRate,
} from "../../leads/capture-guard-client";
import family from "../family.module.css";

const count = (value: number, one: string, many: string) =>
  `${value} ${value === 1 ? one : many}`;

export function captureSummary(rates: readonly CaptureRate[]): {
  line: string;
  needsFix: boolean;
} | null {
  if (!rates.length) return null;
  const calls = rates.reduce((sum, row) => sum + row.calls, 0);
  const received = rates.reduce((sum, row) => sum + row.received, 0);
  const days = new Set(rates.map((row) => row.day)).size;
  return {
    line: `${count(calls, "call", "calls")} · ${count(received, "recording", "recordings")} in the last ${count(days, "day", "days")}`,
    needsFix: rates.some((row) => row.needs_fix),
  };
}

export function PersonCapture({
  personId,
  isYou,
}: {
  personId: string;
  isYou: boolean;
}) {
  const [rates, setRates] = useState<CaptureRate[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    void readCaptureGuard().then((value) => {
      if (!live) return;
      setRates(value?.rates.filter((row) => row.person_id === personId) ?? []);
      setFailed(!value);
    });
    return () => {
      live = false;
    };
  }, [personId]);
  const summary = rates ? captureSummary(rates) : null;
  if (rates && !summary && !failed) return null;
  return (
    <section className={family.card} aria-label="Call capture">
      <div className={family.row}>
        <span className={family.tile}>
          <Mic aria-hidden="true" />
        </span>
        <span className={family.rowText}>
          <span className={family.rowTitle}>Call capture</span>
          <span className={family.rowSub} data-wrap="">
            {failed
              ? "Capture counts are unavailable. Try again shortly."
              : (summary?.line ?? "Checking recordings…")}
          </span>
          {summary ? (
            <span className={family.chips}>
              <span
                className={family.chip}
                data-tone={summary.needsFix ? "red" : "good"}
              >
                {summary.needsFix ? "Recordings missing" : "Recording OK"}
              </span>
            </span>
          ) : null}
        </span>
        {summary?.needsFix ? (
          isYou ? (
            <button
              type="button"
              className={family.outline}
              onClick={() => openCaptureSetup("recordings")}
            >
              Fix
            </button>
          ) : (
            <Link className={family.outline} href="/settings/phones">
              Fix
            </Link>
          )
        ) : (
          <span />
        )}
      </div>
    </section>
  );
}
