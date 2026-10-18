"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ProspectInformation } from "../prospect-information";
import { readCallProspect } from "../prospect-report-facts";
import type { ProspectSummary } from "../prospects-client";
import type { DocumentReportData } from "../report-document-data";
import styles from "./xray.module.css";

/** A stand-in for a call not yet saved to a prospect: this call's facts only. */
function callOnlyProspect(callId: string): ProspectSummary {
  return {
    prospect_id: callId,
    name: "This prospect",
    revision: 0,
    owner_person_id: "",
    stage: null,
    tags: [],
    photo_url: null,
    contact: null,
    fields: [],
    buyer_intent: null,
    next_step: null,
    last_promise: null,
    call_count: 1,
    last_call: null,
    profile_fields: {},
    can_edit: false,
  };
}

type Loaded =
  | { callId: string; state: "linked"; prospect: ProspectSummary }
  | { callId: string; state: "call_only" | "unavailable" };

/**
 * 4. Prospect's Information (Dipak's priority structure, 9 Oct; owner 18 Oct):
 * the six buyer sections for this call's prospect. The saved prospect's facts
 * (a person's edit wins) come first; this call's Report fills the rest, each
 * fact labelled Observed, Inferred or Unknown. Nothing is scored.
 */
export function ProspectPart({
  data,
  callId,
}: {
  data: DocumentReportData;
  callId: string | null;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!callId) return;
    const controller = new AbortController();
    readCallProspect(callId, controller.signal)
      .then((prospect) => {
        if (controller.signal.aborted) return;
        setLoaded(
          prospect
            ? { callId, state: "linked", prospect }
            : { callId, state: "call_only" },
        );
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setLoaded({ callId, state: "unavailable" });
      });
    return () => controller.abort();
  }, [callId, attempt]);

  if (!data.report) return null;
  const current = loaded && loaded.callId === callId ? loaded : null;
  if (callId && !current)
    return (
      <p
        className={`${styles.card} ${styles.empty}`}
        role="status"
        aria-busy="true"
      >
        Reading this prospect&rsquo;s information&hellip;
      </p>
    );
  const latest = callId
    ? { callId, report: data.report, transcript: data.transcript }
    : undefined;
  const linked = current?.state === "linked" ? current.prospect : null;
  return (
    <div className={styles.xr} data-xray-part="prospect">
      {linked ? null : (
        <p className={`${styles.card} ${styles.empty}`}>
          {current?.state === "unavailable"
            ? "The saved prospect couldn’t be read just now, so this shows what this call established."
            : "This call isn’t saved to a prospect yet, so this shows what this call established."}{" "}
          <Link href="/prospects">Open Prospects</Link>
        </p>
      )}
      <ProspectInformation
        prospect={linked ?? callOnlyProspect(callId ?? "call")}
        latest={latest}
        {...(linked ? { onSaved: () => setAttempt((value) => value + 1) } : {})}
      />
    </div>
  );
}
