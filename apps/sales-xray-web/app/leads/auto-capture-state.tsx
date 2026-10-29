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
// Why the phone holds a call (app builds with autoCaptureHealth, 30 Oct 2026); it uploads by itself once fixed.
const holds: Record<string, { label: string; href: string }> = {
  profile: {
    label: "Waiting · complete your profile",
    href: "/settings/profile",
  },
  allowance: {
    label: "Waiting for call minutes",
    href: "/settings/privacy#calls-setup",
  },
  signed_out: {
    label: "Waiting · sign in on your phone",
    href: "/settings/privacy#calls-setup",
  },
  workspace: {
    label: "Waiting · switch to your organisation",
    href: "/settings/privacy#calls-setup",
  },
  folder: {
    label: "Waiting · pick the recordings folder",
    href: "/settings/privacy#calls-setup",
  },
  network: {
    label: "Waiting · phone blocks background uploads",
    href: "/settings/privacy#calls-setup",
  },
  access: {
    label: "Waiting · tried again every hour",
    href: "/settings/privacy#calls-setup",
  },
  consent: {
    label: "Paused · automatic uploads are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  notices: {
    label: "Paused · upload notices are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  off: {
    label: "Paused · uploads are off",
    href: "/settings/privacy#automatic-call-uploads",
  },
  expired: {
    label: "Too old to upload by itself",
    href: "/settings/privacy#calls-setup",
  },
};
export function CaptureStateLabel({
  state,
  attention = false,
  hold,
}: {
  state: string;
  attention?: boolean;
  /** Why the phone holds this call (newer app builds). */
  hold?: string | null;
}) {
  const held = state === "held" && hold ? holds[hold] : undefined;
  return (
    <span className={styles.state} data-missing={state === "missing"}>
      <small role="status">
        {held?.label ?? labels[state]}
        {attention ? " · Analysis needs attention" : ""}
      </small>
      {held ? (
        <Link href={held.href}>
          {hold === "profile" ? "Open Profile" : "Fix uploads"}
        </Link>
      ) : state === "missing" || state === "cancelled" || state === "held" ? (
        <Link href="/settings/privacy#calls-setup">Fix recording</Link>
      ) : null}
    </span>
  );
}
export function AutoCaptureState({ eventId }: { eventId?: string | null }) {
  const [state, setState] = useState<string | null>(null);
  const [hold, setHold] = useState<string | null>(null);
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
      const item = items.find((entry) => entry.eventId === eventId);
      const native = item?.state ?? null;
      // Server receipts outrank a stale native queue; missing stays visible after the deadline.
      const shown =
        found && (found.state !== "waiting" || !native)
          ? found.state
          : (native ?? (server === null ? "unavailable" : null));
      setState(shown);
      setHold(shown === native ? (item?.hold ?? null) : null);
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
    <CaptureStateLabel state={state} attention={call?.attention} hold={hold} />
  ) : null;
}
