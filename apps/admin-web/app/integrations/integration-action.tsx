"use client";

/**
 * Stop one integration at once: revoke an API key, turn a webhook off or
 * disconnect an app (POST /v1/admin/integrations/keys/{id}/revoke,
 * /webhooks/{id}/disable, /connections/{id}/revoke).
 * Asks first, says what stops, and shows the API's answer as it is. The
 * change is audited in the organisation's own history.
 */
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { command, newKey } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import styles from "./integrations.module.css";

const ACTIONS = {
  key: {
    button: "Revoke",
    busy: "Revoking…",
    done: "Revoked",
    path: (id: string) => `/v1/admin/integrations/keys/${id}/revoke`,
    warn: "Apps using this key stop working at once. The organisation can make a new key.",
  },
  webhook: {
    button: "Turn off",
    busy: "Turning off…",
    done: "Turned off",
    path: (id: string) => `/v1/admin/integrations/webhooks/${id}/disable`,
    warn: "No more events go to this address, and its signing secret is retired.",
  },
  connection: {
    button: "Disconnect",
    busy: "Disconnecting…",
    done: "Disconnected",
    path: (id: string) => `/v1/admin/integrations/connections/${id}/revoke`,
    warn: "The app loses access at once and all its tokens stop working. The organisation can connect it again.",
  },
  staff: {
    button: "Revoke",
    busy: "Revoking…",
    done: "Revoked",
    path: (id: string) => `/v1/admin/staff-keys/${id}/revoke`,
    warn: "The key and its session stop at once. Make a new one when you need it.",
  },
} as const;

export function IntegrationAction({
  kind,
  id,
  name,
}: {
  kind: keyof typeof ACTIONS;
  id: string;
  name: string;
}) {
  const action = ACTIONS[kind];
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "sending" | "done">("idle");
  const [message, setMessage] = useState("");
  // One key per intent, so a repeated click never applies twice.
  const key = useRef(newKey());

  if (state === "done") return <span role="status">{action.done}</span>;
  if (!open)
    return (
      <button
        type="button"
        className={kitStyles.button}
        data-variant="ghost"
        onClick={() => setOpen(true)}
        aria-label={`${action.button} ${name}`}
      >
        {action.button}
      </button>
    );
  return (
    <div
      className={styles.confirm}
      role="group"
      aria-label={`${action.button} ${name}?`}
    >
      <small>{action.warn}</small>
      <span className={styles.confirmButtons}>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="primary"
          disabled={state === "sending"}
          onClick={async () => {
            setState("sending");
            setMessage("");
            const result = await command(action.path(id), {}, key.current);
            if (result.ok) {
              setState("done");
              router.refresh();
              return;
            }
            setState("idle");
            setMessage(result.message);
          }}
        >
          {state === "sending" ? action.busy : `${action.button} now`}
        </button>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="ghost"
          onClick={() => {
            setOpen(false);
            setMessage("");
          }}
        >
          Cancel
        </button>
      </span>
      {message ? (
        <small className={kitStyles.fieldError} role="alert">
          {message}
        </small>
      ) : null}
    </div>
  );
}
