"use client";

/**
 * This environment's analysis pipeline (owner, 21 Oct 2026): today's, or both
 * side by side with the Google-only one-pass pipeline, and the one pass's
 * Flex/standard tiers. One save is one audited revision; the API refuses a
 * stale revision and any choice this environment may not make (one pass for
 * people waits for the comparison; staging and production stay on today's).
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
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const changed =
    mode !== settings.mode ||
    transcriptionTier !== settings.transcriptionTier ||
    analysisTier !== settings.analysisTier;
  const needsReason = mode !== settings.mode;

  async function save() {
    setBusy(true);
    setSaid(null);
    const result = await send(
      "PUT",
      "/v1/admin/analysis-pipeline/settings",
      {
        expected_revision: settings.revision,
        config: {
          ...settings.config,
          mode,
          transcription_tier: transcriptionTier,
          analysis_tier: analysisTier,
        },
        reason: reason.trim() || null,
      },
      null,
    );
    setBusy(false);
    if (!result.ok) {
      setSaid({ ok: false, text: result.message });
      return;
    }
    setSaid({ ok: true, text: "Saved. New calls follow it on the next pass." });
    setReason("");
    router.refresh();
  }

  return (
    <form
      className={styles.switch}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
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
      {needsReason ? (
        <label className={styles.reason}>
          Reason (kept with the change)
          <input
            value={reason}
            maxLength={200}
            required
            onChange={(event) => setReason(event.target.value)}
            placeholder="Owner asked for the side-by-side comparison"
          />
        </label>
      ) : null}
      <span className={styles.actions}>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={!changed || busy || (needsReason && !reason.trim())}
        >
          {busy ? "Saving…" : "Save"}
        </button>
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
