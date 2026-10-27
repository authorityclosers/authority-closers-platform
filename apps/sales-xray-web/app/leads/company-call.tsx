"use client";

/**
 * The lead sheet's Call through the company number (owner, 27 Oct 2026).
 *
 * When the workspace calls from its company number and this lead asked to be
 * contacted, Call rings the seller's own phone first, then the lead; the line
 * under Call follows the call, and the ended call's recording is offered to
 * the recording panel like one the phone found. Every other lead is called
 * from the seller's own phone, as before, and so is any call the company
 * number can't place ("Call from my phone").
 */

import { PhoneMissed, PhoneOutgoing, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { NativeRecording } from "./native-phone";
import {
  callLine,
  checkLead,
  CompanyCallError,
  LIVE_STATUSES,
  readCompanyCall,
  readCompanyRecording,
  startCompanyCall,
  type CompanyCall,
} from "./company-call-client";
import styles from "./company-call.module.css";

const POLL_MS = 2500;
// A call nobody heard the end of: stop asking after this long.
const GIVE_UP_MS = 20 * 60 * 1000;

export type CompanyCalling = {
  /** Call goes through the company number for this lead. */
  ready: boolean;
  call: CompanyCall | null;
  busy: boolean;
  error: string | null;
  start: () => Promise<void>;
  /** The ended call's recording, shaped like one the phone found. */
  found: NativeRecording | null;
  readRecording: () => Promise<File>;
  dismiss: () => void;
};

export function useCompanyCall(
  leadId: string,
  enabled: boolean,
  onEnded?: () => void,
): CompanyCalling {
  const [checked, setChecked] = useState<{ leadId: string; ok: boolean }>({
    leadId: "",
    ok: false,
  });
  const [call, setCall] = useState<CompanyCall | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ended = useRef(onEnded);
  useEffect(() => {
    ended.current = onEnded;
  });

  // Whether this lead may be called from the company number, once per lead.
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    checkLead(leadId, controller.signal).then(
      (answer) => setChecked({ leadId, ok: answer.available }),
      () => {
        if (!controller.signal.aborted) setChecked({ leadId, ok: false });
      },
    );
    return () => controller.abort();
  }, [leadId, enabled]);

  // Follow the call while it rings and talks.
  useEffect(() => {
    if (!call || call.final) return;
    const controller = new AbortController();
    const since = Date.parse(call.requestedAt) || Date.now();
    const timer = window.setTimeout(() => {
      if (Date.now() - since > GIVE_UP_MS) return;
      readCompanyCall(call.id, controller.signal).then(
        (next) => {
          setCall(next);
          if (next.final) ended.current?.();
        },
        // Not read this time: ask again on the next beat.
        () => {
          if (!controller.signal.aborted)
            setCall((now) => (now ? { ...now } : now));
        },
      );
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [call]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await startCompanyCall(leadId, crypto.randomUUID());
      setCall(next);
      if (next.final) ended.current?.();
    } catch (reason) {
      setError(
        reason instanceof CompanyCallError
          ? reason.message
          : "The call didn't start. Try again.",
      );
      // Refused for this lead (not asked, paused…): Call is the phone's again.
      if (reason instanceof CompanyCallError && reason.reason)
        setChecked({ leadId, ok: false });
    } finally {
      setBusy(false);
    }
  }, [leadId]);

  const found = useMemo<NativeRecording | null>(
    () =>
      call && call.final && call.recording && call.eventId
        ? {
            source: "company",
            name: `Call at ${new Date(call.requestedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`,
            size: 0,
            durationMs: (call.talkSeconds ?? 0) * 1000,
            ext: "mp3",
            mime: "audio/mpeg",
            supported: true,
            addedMs: Date.parse(call.requestedAt),
          }
        : null,
    [call],
  );

  const readRecording = useCallback(() => {
    if (!call) return Promise.reject(new Error("No call yet."));
    return readCompanyRecording(call);
  }, [call]);

  const dismiss = useCallback(() => {
    setError(null);
    setCall((now) => (now && now.final ? null : now));
  }, []);

  return {
    ready: enabled && checked.leadId === leadId && checked.ok,
    call,
    busy,
    error,
    start,
    found,
    readRecording,
    dismiss,
  };
}

function talk(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60
    ? `${whole} s`
    : `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

/** The line under Call while a company-number call goes on, and after it. */
export function CompanyCallStrip({
  company,
  name,
  phone,
}: {
  company: CompanyCalling;
  name: string;
  phone: string | null;
}) {
  const { call, error } = company;
  if (!call && !error) return null;
  const live = call ? LIVE_STATUSES.has(call.status) : false;
  const reached = !!call && call.final && call.connected === true;
  const state = live ? "live" : reached ? "done" : "missed";
  const title = error
    ? "Not called from the company number"
    : live
      ? "Calling from the company number"
      : reached
        ? `Call ended · ${talk(call?.talkSeconds ?? 0)}`
        : "Not connected";
  return (
    <div
      className={styles.strip}
      data-state={state}
      role="status"
      aria-live="polite"
    >
      <span className={styles.icon} aria-hidden="true">
        {state === "missed" ? (
          <PhoneMissed size={18} />
        ) : (
          <PhoneOutgoing size={18} />
        )}
      </span>
      <span className={styles.text}>
        <strong>{title}</strong>
        <span>{error ?? (call ? callLine(call, name) : "")}</span>
      </span>
      {error && phone ? (
        <a className={styles.action} href={`tel:${phone}`}>
          Call from my phone
        </a>
      ) : null}
      {!live ? (
        <button
          type="button"
          className={styles.close}
          aria-label="Hide"
          onClick={company.dismiss}
        >
          <X size={16} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
