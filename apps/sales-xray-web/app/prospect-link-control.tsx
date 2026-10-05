"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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

function Control({ submissionId }: { submissionId: string }) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);
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
    <section aria-label="Prospect history" className="panel">
      <h2>Prospect history</h2>
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
            This looks like {item.name} from{" "}
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
            Confirm {item.name}
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
              value={name}
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
            Create prospect and link this call
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

export function ProspectLinkControl({
  submissionId,
}: {
  submissionId: string;
}) {
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
      key={`${submissionId}:${access.context.personId}:${access.context.tenantId}`}
      submissionId={submissionId}
    />
  );
}
