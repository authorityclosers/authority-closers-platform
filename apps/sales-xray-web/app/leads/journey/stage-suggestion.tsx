"use client";

/**
 * A lead's next stage, suggested from what its last call said ("visit the site on
 * Saturday" → Site visit booked). Offered with one tap on the lead and in the
 * after-call picker; a person always confirms, nothing moves by itself.
 */

import { Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "../../ui/kit";
import {
  LeadsError,
  moveToStage,
  type LeadDetail,
  type StageSuggestion,
} from "../leads-client";
import styles from "./stage-suggestion.module.css";

const quote = (why: string) => (why.length > 90 ? `${why.slice(0, 89)}…` : why);

/** On the lead: "From the last call: “…”  [Move to Site visit booked]". */
export function SuggestedStage({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const suggestion = detail.stage_suggestion;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!suggestion || !detail.can_edit) return null;
  return (
    <div className={styles.suggested} data-kind={suggestion.kind}>
      <Sparkles size={15} aria-hidden="true" />
      <span className={styles.text}>
        <small>From the last call</small>
        <span>“{quote(suggestion.why)}”</span>
        {error ? (
          <small className={styles.error} role="alert">
            {error}
          </small>
        ) : null}
      </span>
      <Button
        variant="primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            onChanged(await moveToStage(detail.lead, suggestion.step));
          } catch (reason) {
            setError(
              reason instanceof LeadsError
                ? reason.message
                : "Not moved. Try again.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        Move to {suggestion.label}
      </Button>
    </div>
  );
}

/** In the after-call picker: the suggestion as one tap that picks the stage. */
export function SuggestionHint({
  suggestion,
  active,
  onUse,
}: {
  suggestion: StageSuggestion;
  active: boolean;
  onUse: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.hint}
      data-kind={suggestion.kind}
      aria-pressed={active}
      onClick={onUse}
    >
      <Sparkles size={14} aria-hidden="true" />
      <span>
        Suggested from the call: <strong>{suggestion.label}</strong>
        <small> “{quote(suggestion.why)}”</small>
      </span>
    </button>
  );
}
