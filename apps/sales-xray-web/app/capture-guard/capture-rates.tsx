"use client";
import { useEffect, useState } from "react";
import { Panel } from "../ui/kit";
import { displayName } from "../display-name";
import {
  readCaptureGuard,
  type CaptureRate,
} from "../leads/capture-guard-client";
import styles from "./capture-guard.module.css";

export function CaptureRatesView({ rates }: { rates: CaptureRate[] }) {
  return (
    <Panel title="Call capture" sub="Daily · India time">
      <div className={styles.content}>
        <p>
          Calls made · recordings received · reports ready. Red means fewer than
          90% of calls have a recording.
        </p>
        {rates.length ? (
          <ul className={styles.rows}>
            {rates.map((row) => (
              <li
                className={styles.rate}
                data-missing={row.needs_fix}
                key={`${row.person_id}-${row.day}`}
              >
                <strong>
                  {displayName(row.name)} ·{" "}
                  {new Date(`${row.day}T12:00:00Z`).toLocaleDateString(
                    "en-IN",
                    {
                      day: "numeric",
                      month: "short",
                    },
                  )}
                </strong>
                <span>
                  {row.calls} calls · {row.received} recordings · {row.analysed}{" "}
                  analysed
                </span>
                <span>
                  {row.rate}% recorded
                  {row.needs_fix ? " · Capture needs fixing" : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p>No call events in the last 7 days.</p>
        )}
      </div>
    </Panel>
  );
}
export function CaptureRates({ personId }: { personId?: string } = {}) {
  const [rates, setRates] = useState<CaptureRate[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    const read = () =>
      void readCaptureGuard().then((value) => {
        if (active) {
          setRates(value?.rates ?? null);
          setFailed(!value);
        }
      });
    read();
    const timer = setInterval(read, 60_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  if (rates)
    return (
      <CaptureRatesView
        rates={
          personId ? rates.filter((row) => row.person_id === personId) : rates
        }
      />
    );
  return (
    <Panel title="Call capture">
      <p>
        {failed
          ? "Capture counts are unavailable. Try again shortly."
          : "Checking recordings…"}
      </p>
    </Panel>
  );
}
