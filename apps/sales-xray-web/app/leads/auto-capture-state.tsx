"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { autoCaptureStates, onPhoneSignal } from "./native-phone";
import { readCaptureGuard, type CaptureCall } from "./capture-guard-client";
import styles from "../capture-guard/capture-guard.module.css";

const labels: Record<string, string> = {
  waiting: "Waiting for recording",
  unavailable: "Recording status unavailable",
  uploading: "Uploading",
  uploaded: "Uploaded",
  analysing: "Analysing",
  report_ready: "Report ready",
  missing: "No recording after 30 minutes",
  cancelled: "Upload cancelled",
  held: "Upload paused · review this call",
};
export function CaptureStateLabel({
  state,
  attention = false,
}: {
  state: string;
  attention?: boolean;
}) {
  return (
    <span className={styles.state} data-missing={state === "missing"}>
      <small role="status">
        {labels[state]}
        {attention ? " · Analysis needs attention" : ""}
      </small>
      {state === "missing" || state === "cancelled" || state === "held" ? (
        <Link href="/settings/privacy#calls-setup">Fix recording</Link>
      ) : null}
    </span>
  );
}
export function AutoCaptureState({ eventId }: { eventId?: string | null }) {
  const [state, setState] = useState<string | null>(null);
  const [readId, setReadId] = useState<string | null>(null);
  const [call, setCall] = useState<CaptureCall | null>(null);
  useEffect(() => {
    if (!eventId) return;
    let active = true;
    const read = async () => {
      const [items, recent] = await Promise.all([
        autoCaptureStates(),
        readCaptureGuard(),
      ]);
      const server =
        recent && !recent.calls.some((item) => item.event_id === eventId)
          ? await readCaptureGuard(eventId)
          : recent;
      if (!active) return;
      const found =
        server?.calls.find((item) => item.event_id === eventId) ?? null;
      const native =
        items.find((item) => item.eventId === eventId)?.state ?? null;
      // Server receipts outrank a stale native queue; missing stays visible after the deadline.
      setState(
        found && (found.state !== "waiting" || !native)
          ? found.state
          : (native ?? (server === null ? "unavailable" : null)),
      );
      setCall(found);
      setReadId(eventId);
    };
    void read();
    const stop = onPhoneSignal((signal) => {
      if (signal === "recordings" || signal === "resume") void read();
    });
    const timer = setInterval(() => void read(), 30_000);
    return () => {
      active = false;
      stop();
      clearInterval(timer);
    };
  }, [eventId]);
  return readId === eventId && state && labels[state] ? (
    <CaptureStateLabel state={state} attention={call?.attention} />
  ) : null;
}
