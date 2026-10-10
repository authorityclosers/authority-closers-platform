"use client";

import Link from "next/link";
import { LockKeyhole } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  editProspectField,
  fetchProspectDetail,
  PROSPECTS_API,
  UUID_RE,
  type ProspectSummary,
} from "./prospects-client";
import {
  PROSPECT_FIELD_LABELS,
  profileValueText,
  type ProfileKey,
} from "./prospect-profile-contract";
import { useWorkspaceAccess } from "./workspace-access";
import { InlineEdit } from "./ui/kit";
import { dismissNotice, notify } from "./notice-center";
import { formatClock } from "./lightbox/time";
import styles from "./prospect-information.module.css";

export const PROSPECT_FACTS_CHANGED = "ac:prospect-facts-changed";
const KEYS: ProfileKey[] = [
  "name",
  "role",
  "business",
  "industry",
  "budget",
  "next_step",
];

/** Source-fenced server reads; no local storage, name matching or write-on-read. */
export async function readCallProspect(
  callId: string,
  signal: AbortSignal,
): Promise<ProspectSummary | null> {
  const response = await fetch(`${PROSPECTS_API}/calls/${callId}/suggestions`, {
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error("Key facts are unavailable. Try again.");
  const page = await response.json();
  if (
    page.schema !== "ac.sales-xray.prospect-link/1" ||
    page.submission_id !== callId
  )
    throw new Error("The prospect link could not be verified.");
  if (page.membership === null) return null;
  if (
    !UUID_RE.test(page.membership?.prospect_id) ||
    !UUID_RE.test(page.membership?.membership_id)
  )
    throw new Error("The prospect link could not be verified.");
  return (
    await fetchProspectDetail({
      prospectId: page.membership.prospect_id,
      signal,
    })
  ).prospect;
}

export function ProspectReportFacts({
  callId,
  readOnly = false,
}: {
  callId: string | null;
  readOnly?: boolean;
}) {
  const access = useWorkspaceAccess();
  const context = access?.context;
  const permitted =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!context &&
    !!callId &&
    UUID_RE.test(callId);
  const scope = `${context?.personId}:${context?.tenantId}:${context?.sessionId}:${callId}`;
  const [loaded, setLoaded] = useState<{
    scope: string;
    prospect: ProspectSummary | null;
    error?: string;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  useEffect(() => {
    const changed = () => setAttempt((n) => n + 1);
    window.addEventListener(PROSPECT_FACTS_CHANGED, changed);
    return () => window.removeEventListener(PROSPECT_FACTS_CHANGED, changed);
  }, []);
  useEffect(() => {
    if (!permitted) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(15000),
    ]);
    void readCallProspect(callId!, signal)
      .then((prospect) => {
        if (!controller.signal.aborted) {
          setLoaded({ scope, prospect });
          dismissNotice("report-key-facts");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLoaded({
            scope,
            prospect: null,
            error: "Key facts are unavailable.",
          });
          notify({
            id: "report-key-facts",
            tone: "error",
            title: "Key facts unavailable",
            message:
              "The prospect service did not answer. Your report is still available.",
            action: { label: "Try again", run: () => setAttempt((n) => n + 1) },
          });
        }
      });
    return () => controller.abort();
  }, [permitted, scope, callId, attempt]);
  const prospect =
    permitted && loaded?.scope === scope ? loaded.prospect : null;
  if (!permitted)
    return <p className={styles.note}>Sign in to save prospect facts.</p>;
  if (loaded?.scope !== scope)
    return (
      <div
        role="status"
        aria-label="Loading key facts"
        className={styles.factSkeleton}
      />
    );
  if (!prospect)
    return (
      <p className={styles.note}>
        {loaded.error || "Link this call to a prospect to save key facts."}
      </p>
    );
  async function save(key: ProfileKey, value: string) {
    if (pending.current || !prospect)
      throw new Error("Wait for the current save, then try again.");
    pending.current = true;
    setSaving(true);
    let saved = false;
    try {
      await editProspectField(
        prospect.prospect_id,
        prospect.revision,
        key,
        value,
      );
      saved = true;
      const fresh = await fetchProspectDetail({
        prospectId: prospect.prospect_id,
        signal: AbortSignal.timeout(15000),
      });
      setLoaded({ scope, prospect: fresh.prospect });
      dismissNotice("report-key-facts-save");
    } catch (error) {
      notify({
        id: "report-key-facts-save",
        tone: "error",
        title: saved ? "Fact saved · refresh unavailable" : "Fact wasn't saved",
        message: saved
          ? "Your edit was saved. Refresh facts to view the latest version."
          : error instanceof Error
            ? error.message
            : "Try again.",
        action: { label: "Refresh facts", run: () => setAttempt((n) => n + 1) },
      });
      if (saved) {
        // Do not offer stale revision edits after an acknowledged write.
        setLoaded({
          scope,
          prospect: null,
          error: "Your edit was saved. Latest facts are unavailable.",
        });
      } else throw error;
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  return (
    <div data-server-prospect-facts>
      <dl className={styles.facts}>
        {KEYS.map((key) => {
          const field = prospect.profile_fields?.[key];
          const known = field?.state === "known" ? field : null;
          const value = known ? profileValueText(known.value) : "";
          return (
            <div className={styles.fact} key={key}>
              <dt>
                {PROSPECT_FIELD_LABELS[key]}{" "}
                <small>
                  {known
                    ? known.heard_differently?.length
                      ? "Contradiction"
                      : known.changed_from
                        ? "Changed"
                        : "Observed"
                    : "Unknown"}
                </small>
              </dt>
              <dd>
                {!readOnly &&
                prospect.can_edit !== false &&
                prospect.profile_fields ? (
                  <InlineEdit
                    label={PROSPECT_FIELD_LABELS[key]}
                    value={value}
                    placeholder="Unknown · add"
                    disabled={saving}
                    onSave={(text) => save(key, text)}
                  />
                ) : (
                  value || "Unknown"
                )}
              </dd>
              {known?.locked && (
                <small className={styles.lock}>
                  <LockKeyhole size={12} aria-hidden="true" /> Person edit ·
                  locked
                </small>
              )}
              {known?.evidence && (
                <details className={styles.evidence}>
                  <summary>
                    Source · {formatClock(known.evidence.start_ms)}
                  </summary>
                  <blockquote>{known.evidence.quote}</blockquote>
                  <Link
                    href={`/analysis/calls/${known.evidence.submission_id}?section=transcript`}
                  >
                    Open source call
                  </Link>
                </details>
              )}
            </div>
          );
        })}
      </dl>
      <Link
        className={styles.profileLink}
        href={`/prospects/${prospect.prospect_id}`}
      >
        Open Prospect’s Information
      </Link>
    </div>
  );
}
