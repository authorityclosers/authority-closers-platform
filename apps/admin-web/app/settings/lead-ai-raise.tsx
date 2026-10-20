"use client";

/**
 * "Raise and resume" for AI replies to leads (Lead Desk contract, 20 Oct): one
 * click lifts the cap to the next preset and the waiting replies go on the
 * runner's next pass. The Lead Desk checks the revision and audits the raise.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import styles from "./settings.module.css";

const rupees = (value: number) => `₹${value.toLocaleString("en-IN")}`;

export function LeadAiRaise({
  revision,
  raiseTo,
  atCap,
  waiting,
}: {
  revision: number | null;
  raiseTo: number;
  atCap: boolean;
  waiting: number;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  return (
    <span className={styles.control}>
      <small className={styles.note}>
        {atCap
          ? "Cap reached: automatic replies are waiting, suggestions are paused."
          : `${waiting} ${waiting === 1 ? "reply is" : "replies are"} waiting for budget.`}
      </small>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setMessage(null);
          const result = await send(
            "POST",
            "/v1/admin/lead-desk-ai/raise",
            { expected_revision: revision },
            null,
          );
          setBusy(false);
          if (!result.ok) {
            setMessage({ ok: false, text: result.message });
            return;
          }
          setMessage({
            ok: true,
            text: `Raised to ${rupees(raiseTo)}; replies resume`,
          });
          router.refresh();
        }}
      >
        {busy ? "Raising…" : `Raise to ${rupees(raiseTo)} and resume`}
      </button>
      {message ? (
        <small
          className={message.ok ? styles.changed : kitStyles.fieldError}
          role={message.ok ? "status" : "alert"}
        >
          {message.text}
        </small>
      ) : null}
    </span>
  );
}
