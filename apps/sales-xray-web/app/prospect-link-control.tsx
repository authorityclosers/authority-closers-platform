"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ACQUISITION, record } from "./acquisition-client";
import { Clip } from "./report-kit";
import type { ReportEvidence, Transcript } from "./report-contract";
import styles from "./report-kit.module.css";
import factStyles from "./key-facts.module.css";

import { PROSPECTS_API, UUID_RE } from "./prospects-client";
import { useWorkspaceAccess } from "./workspace-access";

type Membership = { membership_id: string; prospect_id: string };
type Reference = {
  submission_id: string;
  evidence: {
    quote: string;
    segment_id: string;
    start_ms: number;
    end_ms: number;
  }[];
};
type Suggestion = {
  prospect_id: string;
  name: string;
  previous_call_at: string;
  confirmed: false;
  details: {
    key: string;
    text: string;
    current: Reference;
    previous: Reference;
  }[];
};
type Page = {
  membership: Membership | null;
  suggestions: Suggestion[];
  next_offset: number | null;
};

async function request(
  submissionId: string,
  action: string,
  signal: AbortSignal,
  body?: object,
): Promise<Page> {
  const response = await fetch(
    `${PROSPECTS_API}/calls/${submissionId}/${action}`,
    {
      method: body ? "POST" : "GET",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal,
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    throw new Error(
      response.status === 409
        ? "The call link changed. Reload before confirming."
        : "Prospect links are unavailable. Reload to try again.",
    );
  }
  const page = await response.json();
  if (
    page.schema !== "ac.sales-xray.prospect-link/1" ||
    page.submission_id !== submissionId ||
    (page.membership !== null &&
      (!UUID_RE.test(page.membership?.prospect_id) ||
        !UUID_RE.test(page.membership?.membership_id)))
  ) {
    throw new Error("Prospect links could not be verified.");
  }
  if (
    (!body &&
      (!Array.isArray(page.suggestions) ||
        page.suggestions.some(
          (item: Suggestion) =>
            !UUID_RE.test(item.prospect_id) ||
            typeof item.name !== "string" ||
            item.confirmed !== false ||
            !Number.isFinite(Date.parse(item.previous_call_at)) ||
            !Array.isArray(item.details) ||
            item.details.some(
              (detail) =>
                typeof detail.text !== "string" ||
                [detail.current, detail.previous].some(
                  (ref) =>
                    !ref ||
                    !UUID_RE.test(ref.submission_id) ||
                    !Array.isArray(ref.evidence) ||
                    ref.evidence.some((ev) => typeof ev.quote !== "string"),
                ),
            ),
        ))) ||
    (!body &&
      page.next_offset !== null &&
      (!Number.isInteger(page.next_offset) || page.next_offset < 0))
  ) {
    throw new Error("Prospect suggestions could not be verified.");
  }
  return body
    ? { membership: page.membership, suggestions: [], next_offset: null }
    : page;
}

type Props = {
  submissionId: string;
  transcript?: Transcript;
  onSelectEvidence?: (evidence: ReportEvidence, title: string) => void;
  /** Reserved for Card D2's server-backed detected state. */
  statusSlot?: ReactNode;
};
type HeardName = { name: string; evidence: ReportEvidence[] };

async function statedName(
  submissionId: string,
  transcript: Transcript,
  signal: AbortSignal,
): Promise<HeardName | null> {
  const response = await fetch(
    `${ACQUISITION}/submissions/${submissionId}/speaker-map`,
    {
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal,
    },
  );
  if (!response.ok) return null;
  const data = record(await response.json());
  if (
    data.schema !== "ac.sales-xray.speaker-map/1" ||
    data.submission_id !== submissionId ||
    data.transcript_revision !== transcript.revision ||
    !["predicted", "confirmed", "channel", "model_named"].includes(
      data.status as string,
    ) ||
    !Array.isArray(data.speakers)
  )
    return null;
  const prospects = data.speakers
    .map(record)
    .filter((row) => row.role === "prospect");
  if (prospects.length !== 1) return null;
  const row = prospects[0];
  if (
    row.name_source !== "stated_in_call" ||
    typeof row.display_name !== "string" ||
    !transcript.segments.some(
      (segment) => segment.speaker_id === row.speaker_id,
    ) ||
    !row.display_name.trim() ||
    row.display_name.trim().length > 160 ||
    !Array.isArray(row.name_evidence) ||
    !row.name_evidence.length
  )
    return null;
  const evidence: ReportEvidence[] = [];
  for (const value of row.name_evidence) {
    const ref = record(value);
    const segment = transcript.segments.find((s) => s.id === ref.segment_id);
    if (
      !segment ||
      !Number.isInteger(ref.start_ms) ||
      !Number.isInteger(ref.end_ms) ||
      (ref.start_ms as number) < segment.start_ms ||
      (ref.end_ms as number) > segment.end_ms ||
      (ref.end_ms as number) <= (ref.start_ms as number)
    )
      return null;
    evidence.push({
      segment_id: segment.id,
      quote: segment.text,
      start_ms: ref.start_ms as number,
      end_ms: ref.end_ms as number,
    });
  }
  return { name: row.display_name.trim(), evidence };
}

function Control({
  submissionId,
  transcript,
  onSelectEvidence,
  statusSlot,
}: Props) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editedName, setName] = useState<string | null>(null);
  const [heard, setHeard] = useState<HeardName | null>(null);
  const name = editedName ?? heard?.name ?? "";
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (!transcript) return;
    const load = new AbortController();
    void statedName(submissionId, transcript, load.signal)
      .then((value) => {
        if (!load.signal.aborted) setHeard(value);
      })
      .catch(() => {
        /* Manual entry stays available when the map is missing. */
      });
    return () => load.abort();
  }, [submissionId, transcript]);
  useEffect(() => {
    const load = new AbortController();
    void request(submissionId, `suggestions?offset=${offset}`, load.signal)
      .then((result) => {
        if (!load.signal.aborted) {
          setPage(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!load.signal.aborted)
          setError(
            err instanceof Error ? err.message : "Reload prospect links.",
          );
      });
    return () => load.abort();
  }, [submissionId, offset, attempt]);

  async function save(action: "create" | "confirm", body: object) {
    if (busy) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError(null);
    try {
      const result = await request(
        submissionId,
        action,
        controller.signal,
        body,
      );
      if (!controller.signal.aborted) setPage(result);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : "Reload prospect links.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section
      aria-label="Prospect"
      className={`${styles.card} ${styles.tone}`}
      data-tone="info"
      data-prospect-card
    >
      <h2>Prospect</h2>
      {statusSlot}
      {heard && (
        <div>
          <p>Name heard in this call: {heard.name}</p>
          {heard.evidence.map((evidence) =>
            onSelectEvidence ? (
              <Clip
                key={evidence.segment_id}
                evidence={evidence}
                title="Prospect name"
                onPlay={onSelectEvidence}
              />
            ) : (
              <blockquote key={evidence.segment_id}>
                {evidence.quote}
              </blockquote>
            ),
          )}
        </div>
      )}
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              setPage(null);
              setAttempt((a) => a + 1);
            }}
          >
            Reload
          </button>
        </p>
      )}
      {!page && !error && <p role="status">Loading prospect links…</p>}
      {page?.membership && (
        <p>
          Confirmed link.{" "}
          <Link href={`/prospects/${page.membership.prospect_id}`}>
            Open prospect history
          </Link>
        </p>
      )}
      {!!page?.suggestions.length && (
        <p>
          These stated details match an earlier call. Confirm only if this is
          the same prospect.
        </p>
      )}
      {page?.suggestions.map((item) => (
        <div key={item.prospect_id}>
          <p>
            Same as {item.name}? Earlier call:{" "}
            {new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
              new Date(item.previous_call_at),
            )}
            .
          </p>
          <details>
            <summary>Matching stated details</summary>
            {item.details.map((detail, i) => (
              <div key={i}>
                <p>
                  {detail.key}: {detail.text}
                </p>
                {[detail.current, detail.previous].map((ref, j) => (
                  <p key={j}>
                    <Link href={`/analysis/calls/${ref.submission_id}`}>
                      {j === 0 ? "This call" : "Earlier call"}
                    </Link>
                    : {ref.evidence.map((ev) => `“${ev.quote}”`).join(" ")}
                  </p>
                ))}
              </div>
            ))}
          </details>
          <button
            type="button"
            className="secondary-button"
            disabled={busy || error !== null}
            onClick={() =>
              void save("confirm", {
                prospect_id: item.prospect_id,
                expected_membership_id: page.membership?.membership_id ?? null,
              })
            }
          >
            Same as {item.name}?
          </button>
        </div>
      ))}
      {page && !page.membership && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) void save("create", { display_name: name.trim() });
          }}
        >
          <label>
            New prospect name{" "}
            <input
              className={factStyles.select}
              value={name}
              disabled={busy}
              maxLength={160}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="secondary-button"
            disabled={busy || error !== null || !name.trim()}
          >
            Save as new prospect
          </button>
        </form>
      )}
      {page?.next_offset !== null && page?.next_offset !== undefined && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setPage(null);
            setOffset(page.next_offset ?? 0);
          }}
        >
          Look for more matches
        </button>
      )}
    </section>
  );
}

export function ProspectLinkControl(props: Props) {
  const { submissionId } = props;
  const access = useWorkspaceAccess();
  if (
    access?.status !== "ready" ||
    access.authenticated !== true ||
    !access.context ||
    !UUID_RE.test(submissionId)
  )
    return null;
  return (
    <Control
      key={`${submissionId}:${props.transcript?.revision}:${access.context.personId}:${access.context.tenantId}`}
      {...props}
    />
  );
}
