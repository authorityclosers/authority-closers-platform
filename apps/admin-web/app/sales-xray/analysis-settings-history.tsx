"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { responseSchema } from "./analysis-settings-contract";
import styles from "./analysis-settings.module.css";

const historySchema = z
  .object({
    items: z.array(responseSchema).max(50),
    next_before_revision: z.number().int().positive().nullable(),
  })
  .strict();
type Revision = z.infer<typeof responseSchema>;

/** Immutable history is loaded only when requested, with bounded cursor pages. */
export function AnalysisSettingsHistory({ revision }: { revision: number }) {
  return <RevisionHistory key={revision} />;
}

function RevisionHistory() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Revision[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    return () => controller.current?.abort();
  }, []);

  async function load(before?: number) {
    if (inFlight.current) return;
    const active = new AbortController();
    controller.current = active;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const suffix = before === undefined ? "" : `?before_revision=${before}`;
      const response = await fetch(
        `/v1/admin/conversation/analysis-settings/history${suffix}`,
        {
          signal: active.signal,
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          headers: { accept: "application/json" },
        },
      );
      if (!response.ok)
        throw new Error("History could not be loaded. Try again.");
      const page = historySchema.parse(await response.json());
      if (active.signal.aborted) return;
      if (
        page.items.some(
          (item, index) =>
            (before !== undefined && item.revision >= before) ||
            (index > 0 && item.revision >= page.items[index - 1].revision),
        ) ||
        (page.next_before_revision !== null &&
          page.next_before_revision !== page.items.at(-1)?.revision)
      ) {
        throw new Error("History could not be verified. Try again.");
      }
      setItems((previous) =>
        before === undefined ? page.items : [...previous, ...page.items],
      );
      setCursor(page.next_before_revision);
      setLoaded(true);
    } catch {
      if (!active.signal.aborted)
        setError("History could not be verified. Try again.");
    } finally {
      if (!active.signal.aborted) {
        inFlight.current = false;
        setBusy(false);
      }
    }
  }

  return (
    <section className={styles.history} aria-label="Analysis settings history">
      <button
        type="button"
        className={styles.iconButton}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          if (!open && !loaded) void load();
        }}
      >
        {open ? "Hide" : "View"} revision history
      </button>
      {open && (
        <div aria-busy={busy}>
          <p className={styles.hint}>
            Saved revisions are preserved. Changes apply to new plans only.
          </p>
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          {busy && <p role="status">Loading revisions…</p>}
          {loaded && !items.length && (
            <p>No analysis-settings revisions have been saved.</p>
          )}
          <ol className={styles.revisions}>
            {items.map((item) => (
              <li key={item.revision}>
                <strong>Revision {item.revision}</strong>
                {item.created_at && (
                  <time dateTime={item.created_at}>
                    {new Date(item.created_at).toLocaleString("en")}
                  </time>
                )}
                <dl>
                  <div>
                    <dt>Fact requests</dt>
                    <dd>{item.settings.c4_max_requests}</dd>
                  </div>
                  <div>
                    <dt>Fact output tokens</dt>
                    <dd>{item.settings.c4_max_completion_tokens}</dd>
                  </div>
                  <div>
                    <dt>Report output tokens</dt>
                    <dd>{item.settings.c5_max_completion_tokens}</dd>
                  </div>
                  <div>
                    <dt>Report detail</dt>
                    <dd>{item.settings.c5_output_profile}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ol>
          {(!loaded || cursor !== null) && !busy && (
            <button
              type="button"
              className={styles.iconButton}
              onClick={() =>
                void load(loaded && cursor !== null ? cursor : undefined)
              }
            >
              {error ? "Retry loading revisions" : "Load older revisions"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
