"use client";

/**
 * One click on a cap: raise it to the next preset (the API checks the
 * revision and audits who, when, old and new), and the waiting background
 * jobs go again on their next pass. The background switch turns this
 * environment's background AI on or off, keeping every cap as it is.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import { rupees } from "./spend-data";
import styles from "./spend.module.css";

function useCommand() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  async function run(
    method: "POST" | "PUT",
    path: string,
    body: unknown,
    done: string,
  ) {
    setBusy(true);
    setMessage(null);
    const result = await send(method, path, body, null);
    setBusy(false);
    if (!result.ok) {
      setMessage({ ok: false, text: result.message });
      return;
    }
    setMessage({ ok: true, text: done });
    router.refresh();
  }
  return { busy, message, run };
}

function Said({ message }: { message: { ok: boolean; text: string } | null }) {
  return message ? (
    <small
      className={message.ok ? styles.changed : kitStyles.fieldError}
      role={message.ok ? "status" : "alert"}
    >
      {message.text}
    </small>
  ) : null;
}

export function RaiseCap({
  revision,
  target,
  raiseTo,
}: {
  revision: number | null;
  target: string;
  raiseTo: number;
}) {
  const { busy, message, run } = useCommand();
  return (
    <span className={styles.control}>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="secondary"
        disabled={busy}
        onClick={() =>
          run(
            "POST",
            "/v1/admin/ai-spend/raise",
            { expected_revision: revision, target },
            `Raised to ${rupees(raiseTo)}`,
          )
        }
      >
        {busy ? "Raising…" : `Raise to ${rupees(raiseTo)}`}
      </button>
      <Said message={message} />
    </span>
  );
}

export function BackgroundSwitch({
  revision,
  config,
  enabled,
}: {
  revision: number | null;
  config: Record<string, unknown>;
  enabled: boolean;
}) {
  const { busy, message, run } = useCommand();
  return (
    <span className={styles.control}>
      <button
        type="button"
        className={kitStyles.button}
        data-variant={enabled ? "secondary" : "primary"}
        disabled={busy}
        onClick={() =>
          run(
            "PUT",
            "/v1/admin/ai-spend/settings",
            {
              expected_revision: revision,
              config: { ...config, background_enabled: !enabled },
              reason: enabled
                ? "Background AI switched off in Admin"
                : "Background AI switched on in Admin",
            },
            enabled ? "Background AI is off" : "Background AI is on",
          )
        }
      >
        {busy ? "Saving…" : enabled ? "Turn off" : "Turn on"}
      </button>
      <Said message={message} />
    </span>
  );
}
