"use client";

/**
 * C2 transcription on Gemini 3.1 Flash-Lite (owner, 21 Oct 2026: "So at least
 * get this on prod now!!!"). Three steps, each audited:
 * 1. Prepare: the active configuration with only the transcription route on
 *    Gemini is saved as a provider revision (nothing changes yet).
 * 2. Root seals that revision's digest into the approval bundle
 *    (docs/ops/ONE-PASS-PRODUCTION.md).
 * 3. The owner switches: type the confirm word and give the reason (signed in
 *    within ten minutes). Back to Scribe is one click.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import type { Transcription } from "./one-pass-data";
import styles from "./one-pass.module.css";

const ACTIVATE = "/v1/admin/conversation/providers/activate";

function key(): string {
  return `one-pass-c2-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function TranscriptionSwitch({ view }: { view: Transcription }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const onGemini = view.active?.provider === "gemini";

  async function run(
    path: string,
    body: unknown,
    idempotent: boolean,
    done: string,
  ) {
    setBusy(true);
    setSaid(null);
    const result = await send("POST", path, body, idempotent ? key() : null);
    setBusy(false);
    if (!result.ok) {
      setSaid({ ok: false, text: result.message });
      return;
    }
    setSaid({ ok: true, text: done });
    setReason("");
    setConfirm("");
    router.refresh();
  }

  const prepare = () =>
    void run(
      "/v1/admin/analysis-pipeline/transcription/prepare",
      {},
      false,
      "Saved. Root seals its digest next; nothing changes until the owner switches.",
    );
  const switchOn = () =>
    void run(
      ACTIVATE,
      {
        expected_revision: view.latestRevision,
        target_revision: view.gemini.savedRevision,
        confirm: confirm.trim(),
        reason: reason.trim(),
      },
      true,
      "Switched. New calls are transcribed by Gemini 3.1 Flash-Lite.",
    );
  const back = () =>
    void run(
      ACTIVATE,
      {
        expected_revision: view.latestRevision,
        target_revision: view.classicRevision,
      },
      true,
      "Back on Scribe. New calls follow it at once.",
    );

  const inUse = view.active
    ? `${view.active.provider ?? "unknown"} · ${view.active.model ?? "unknown"} (revision ${view.active.revision})`
    : "No provider configuration is active here.";

  return (
    <div className={styles.switch}>
      <p className={styles.note}>Transcription in use: {inUse}</p>
      {onGemini ? (
        <span className={styles.actions}>
          <button
            type="button"
            className={kitStyles.button}
            disabled={busy || view.classicRevision === null}
            onClick={back}
          >
            Back to Scribe
          </button>
        </span>
      ) : view.gemini.savedRevision === null ? (
        <span className={styles.actions}>
          <button
            type="button"
            className={kitStyles.button}
            disabled={busy || view.active === null}
            onClick={prepare}
          >
            Prepare Gemini 3.1 Flash-Lite transcription
          </button>
        </span>
      ) : !view.gemini.approved ? (
        <p className={styles.note}>
          Saved as revision {view.gemini.savedRevision} (
          {view.gemini.configurationSha256?.slice(0, 12)}…). Waiting for Root to
          seal it into the approval bundle.
        </p>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            switchOn();
          }}
        >
          <label className={styles.reason}>
            Reason, in the owner&apos;s words
            <input
              value={reason}
              maxLength={200}
              required
              onChange={(event) => setReason(event.target.value)}
              placeholder="Owner, 21 Oct: So at least get this on prod now"
            />
          </label>
          <label className={styles.reason}>
            Type {view.confirm} to confirm
            <input
              value={confirm}
              maxLength={32}
              required
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </label>
          <span className={styles.actions}>
            <button
              type="submit"
              className={kitStyles.button}
              data-variant="primary"
              disabled={
                busy ||
                confirm.trim() !== view.confirm ||
                reason.trim().length < 10
              }
            >
              Switch transcription to Gemini 3.1 Flash-Lite
            </button>
          </span>
        </form>
      )}
      {said ? (
        <small
          className={said.ok ? styles.note : kitStyles.fieldError}
          role={said.ok ? "status" : "alert"}
        >
          {said.text}
        </small>
      ) : null}
    </div>
  );
}
