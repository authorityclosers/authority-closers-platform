"use client";

/**
 * This environment's analysis pipeline (owner, 21 Oct 2026): today's, both
 * side by side (development), or one pass for people. One save is one audited
 * revision; the API refuses a stale revision and any choice this environment
 * may not make. One pass for people is the owner's action: type the confirm
 * word and give the reason in the owner's words (a control account signed in
 * within ten minutes; the one-pass spend cap must be above zero). Going back
 * to today's pipeline is one click.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import type { PipelineSettings } from "./one-pass-data";
import styles from "./one-pass.module.css";

export function PipelineSwitch({ settings }: { settings: PipelineSettings }) {
  const router = useRouter();
  const [mode, setMode] = useState(settings.mode);
  const [transcriptionTier, setTranscriptionTier] = useState(
    settings.transcriptionTier,
  );
  const [analysisTier, setAnalysisTier] = useState(settings.analysisTier);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const changed =
    mode !== settings.mode ||
    transcriptionTier !== settings.transcriptionTier ||
    analysisTier !== settings.analysisTier;
  const needsReason = mode !== settings.mode;
  const ownerAction = Boolean(
    settings.modes.find((choice) => choice.value === mode)?.needsOwner,
  );
  const ownerReady =
    !ownerAction ||
    (confirm.trim() === settings.confirm && reason.trim().length >= 10);

  async function put(body: Record<string, unknown>, done: string) {
    setBusy(true);
    setSaid(null);
    const result = await send(
      "PUT",
      "/v1/admin/analysis-pipeline/settings",
      { expected_revision: settings.revision, ...body },
      null,
    );
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

  function save() {
    void put(
      {
        config: {
          ...settings.config,
          mode,
          transcription_tier: transcriptionTier,
          analysis_tier: analysisTier,
        },
        reason: reason.trim() || null,
        ...(ownerAction ? { confirm: confirm.trim() } : {}),
      },
      "Saved. New calls follow it on the next pass.",
    );
  }

  function backToClassic() {
    void put(
      {
        config: { ...settings.config, mode: "classic" },
        reason: "Back to today's pipeline",
      },
      "Back on today's pipeline. New calls follow it at once.",
    );
  }

  return (
    <form
      className={styles.switch}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <fieldset className={styles.modes}>
        <legend>Pipeline</legend>
        {settings.modes.map((choice) => (
          <label key={choice.value} className={styles.mode}>
            <input
              type="radio"
              name="mode"
              value={choice.value}
              checked={mode === choice.value}
              disabled={Boolean(choice.whyNot) || busy}
              onChange={() => setMode(choice.value)}
            />
            <span>
              {choice.label}
              {choice.whyNot ? (
                <small className={styles.note}>{choice.whyNot}</small>
              ) : choice.needsOwner ? (
                <small className={styles.note}>
                  The owner&apos;s decision: type {settings.confirm} and give
                  the reason.
                </small>
              ) : null}
            </span>
          </label>
        ))}
      </fieldset>
      <div className={styles.tiers}>
        <label>
          Transcription ({settings.models.transcription})
          <select
            value={transcriptionTier}
            disabled={busy}
            onChange={(event) => setTranscriptionTier(event.target.value)}
          >
            {settings.tiers.map((tier) => (
              <option key={tier.value} value={tier.value}>
                {tier.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          One pass ({settings.models.analysis})
          <select
            value={analysisTier}
            disabled={busy}
            onChange={(event) => setAnalysisTier(event.target.value)}
          >
            {settings.tiers.map((tier) => (
              <option key={tier.value} value={tier.value}>
                {tier.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {needsReason || ownerAction ? (
        <label className={styles.reason}>
          {ownerAction
            ? "Reason, in the owner's words (kept with the change)"
            : "Reason (kept with the change)"}
          <input
            value={reason}
            maxLength={200}
            required
            onChange={(event) => setReason(event.target.value)}
            placeholder={
              ownerAction
                ? "Owner, 21 Oct: So at least get this on prod now"
                : "Owner asked for the side-by-side comparison"
            }
          />
        </label>
      ) : null}
      {ownerAction ? (
        <label className={styles.reason}>
          Type {settings.confirm} to confirm
          <input
            value={confirm}
            maxLength={32}
            required
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </label>
      ) : null}
      <span className={styles.actions}>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={
            !changed || busy || (needsReason && !reason.trim()) || !ownerReady
          }
        >
          {busy ? "Saving…" : "Save"}
        </button>
        {settings.mode !== "classic" ? (
          <button
            type="button"
            className={kitStyles.button}
            disabled={busy}
            onClick={backToClassic}
          >
            Back to today&apos;s pipeline
          </button>
        ) : null}
        {said ? (
          <small
            className={said.ok ? styles.note : kitStyles.fieldError}
            role={said.ok ? "status" : "alert"}
          >
            {said.text}
          </small>
        ) : null}
      </span>
    </form>
  );
}
