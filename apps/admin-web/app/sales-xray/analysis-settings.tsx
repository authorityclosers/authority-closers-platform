"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Save, SlidersHorizontal } from "lucide-react";
import { z } from "zod";

import { newIdempotencyKey } from "@ac/operations-web/api";

import { settingsSchema, responseSchema } from "./analysis-settings-contract";
import { AnalysisSettingsHistory } from "./analysis-settings-history";

import styles from "./analysis-settings.module.css";

type State = z.infer<typeof responseSchema>;
const endpoint = "/v1/admin/conversation/analysis-settings";

async function request(init: RequestInit = {}) {
  const response = await fetch(endpoint, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw new Error(
      response.status === 403
        ? "Use your verified AC Admin account to manage analysis limits."
        : response.status === 409
          ? "Another administrator changed these limits. Refresh before saving."
          : "Analysis limits could not be confirmed. Refresh to try again.",
    );
  }
  return response.json() as Promise<unknown>;
}

export function AnalysisSettingsPanel() {
  const [state, setState] = useState<State | null>(null);
  const [draft, setDraft] = useState<State["settings"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = responseSchema.parse(await request({ signal }));
      if (signal?.aborted) return;
      setState(next);
      setDraft(next.settings);
      setError(null);
    } catch (failure) {
      if (!signal?.aborted) {
        setError(
          failure instanceof Error && !(failure instanceof z.ZodError)
            ? failure.message
            : "Analysis limits could not be verified. Refresh to try again.",
        );
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void refresh(controller.signal);
    });
    return () => controller.abort();
  }, [refresh]);

  async function save() {
    if (!state || !draft || busy) return;
    if (!settingsSchema.safeParse(draft).success) {
      setError(
        "Use whole numbers within the displayed limits. Hindi and Marathi reports require the qualitative v0.2 engine.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const next = responseSchema.parse(
        await request({
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": newIdempotencyKey(),
          },
          body: JSON.stringify({
            expected_revision: state.revision,
            settings: draft,
          }),
        }),
      );
      setState(next);
      setDraft(next.settings);
      setMessage(`Saved analysis limits as revision ${next.revision}.`);
    } catch (failure) {
      setError(
        failure instanceof Error && !(failure instanceof z.ZodError)
          ? failure.message
          : "The saved limits could not be verified. Refresh before continuing.",
      );
    } finally {
      setBusy(false);
    }
  }

  const bounds = state?.bounds;
  return (
    <section
      className={styles.panel}
      aria-labelledby="analysis-settings-title"
      aria-busy={busy}
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>
            <SlidersHorizontal size={16} aria-hidden /> Future plan limits
          </p>
          <h2 id="analysis-settings-title">
            Analysis detail and test ceilings
          </h2>
        </div>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => void refresh()}
          disabled={busy}
          aria-label="Refresh analysis limits"
        >
          <RefreshCw size={17} aria-hidden />
        </button>
      </header>
      <p className={styles.copy}>
        These controls affect new plans only. Each value is intersected with the
        active release approval and provider route before a plan is quoted;
        accepted plans remain unchanged.
      </p>
      {state?.revision === 0 && (
        <p className={styles.hint}>
          Starting values are shown. Until you save an Admin revision, new plans
          remain governed by the pinned provider approval and route ceiling.
        </p>
      )}
      {!state && !error && <p role="status">Loading analysis limits…</p>}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {message && (
        <p role="status" className={styles.success}>
          {message}
        </p>
      )}
      {state && draft && bounds && (
        <>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>C4 fact requests per call</span>
              <input
                aria-label="C4 fact requests per call"
                type="number"
                min={bounds.c4_max_requests.min}
                max={bounds.c4_max_requests.max}
                step={1}
                value={draft.c4_max_requests}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    c4_max_requests: Number(event.target.value),
                  })
                }
              />
              <small>
                Server also applies the approved route’s request cap.
              </small>
            </label>
            <label className={styles.field}>
              <span>C4 output tokens</span>
              <input
                aria-label="C4 output tokens"
                type="number"
                min={bounds.c4_max_completion_tokens.min}
                max={bounds.c4_max_completion_tokens.max}
                step={256}
                value={draft.c4_max_completion_tokens}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    c4_max_completion_tokens: Number(event.target.value),
                  })
                }
              />
              <small>Lower values reduce the per-request test ceiling.</small>
            </label>
            <label className={styles.field}>
              <span>C5 output profile</span>
              <select
                aria-label="C5 output profile"
                value={draft.c5_output_profile}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    c5_output_profile: event.target.value as
                      | "standard"
                      | "detailed",
                  })
                }
              >
                {bounds.c5_output_profile.values.map((value) => (
                  <option key={value} value={value}>
                    {value === "detailed"
                      ? "Detailed overview"
                      : "Standard report"}
                  </option>
                ))}
              </select>
              <small>
                Detailed adds the structured overview section to new reports.
              </small>
            </label>
            <label className={styles.field}>
              <span>C5 output tokens</span>
              <input
                aria-label="C5 output tokens"
                type="number"
                min={bounds.c5_max_completion_tokens.min}
                max={bounds.c5_max_completion_tokens.max}
                step={256}
                value={draft.c5_max_completion_tokens}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    c5_max_completion_tokens: Number(event.target.value),
                  })
                }
              />
              <small>
                Release approval can lower this value for a specific route.
              </small>
            </label>
            <label className={styles.field}>
              <span>Report engine</span>
              <select
                aria-label="Report engine"
                value={draft.c5_coaching_prompt_revision}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    c5_coaching_prompt_revision: event.target.value as
                      | "coaching-v3"
                      | "coaching-v4",
                  })
                }
              >
                {bounds.c5_coaching_prompt_revision.values.map((value) => (
                  <option key={value} value={value}>
                    {value === "coaching-v4"
                      ? "Qualitative v0.2 · source-bound rule pack"
                      : "Current report · v3"}
                  </option>
                ))}
              </select>
              <small>
                Saving selects the engine for new plans. Existing reports and
                accepted plans keep their original version.
              </small>
            </label>
            <label className={styles.field}>
              <span>Default report language</span>
              <select
                aria-label="Default report language"
                value={draft.report_language_default}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    report_language_default: event.target.value as
                      | "en"
                      | "hi-Deva+en"
                      | "mr-Deva+en",
                  })
                }
              >
                {bounds.report_language_default.values.map((value) => (
                  <option key={value} value={value}>
                    {value === "hi-Deva+en"
                      ? "Hindi + English"
                      : value === "mr-Deva+en"
                        ? "Marathi + English"
                        : "English"}
                  </option>
                ))}
              </select>
              <small>
                The app stays English. Original evidence quotations keep their
                original wording and script.
              </small>
            </label>
          </div>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => void save()}
              disabled={busy}
            >
              <Save size={16} aria-hidden />{" "}
              {busy ? "Saving…" : "Save future plan limits"}
            </button>
            <span>Revision {state.revision}</span>
          </div>
          <AnalysisSettingsHistory revision={state.revision} />
          <p className={styles.hint}>
            Provider budget, trial allowances, timeouts and retries remain
            release-managed until their server consumers are configured.
          </p>
        </>
      )}
    </section>
  );
}
