"use client";

/**
 * Staff keys (orchestrator's go, 19 Oct): a verified control account makes a
 * key for the Admin command line or MCP right after signing in, at most two
 * at a time. The key shows once, here; Admin keeps only its fingerprint. A key
 * reaches only Admin settings, and can be revoked at once.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { when } from "../calls/call-data";
import { command, newKey } from "../lib/client-api";
import { Badge, kitStyles } from "../ui/kit";
import { IntegrationAction } from "./integration-action";
import styles from "./integrations.module.css";
import {
  activeKeys,
  normalizeStaffKey,
  type StaffKey,
  type StaffKeys as StaffKeysData,
} from "./staff-keys-data";

const STATE_TONE = {
  active: "good",
  expired: "neutral",
  revoked: "bad",
} as const;

export function StaffKeys({ data }: { data: StaffKeysData }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [write, setWrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<{ key: string; row: StaffKey } | null>(null);
  const [copied, setCopied] = useState(false);
  const full = activeKeys(data) >= data.limits.active;

  const make = async () => {
    setBusy(true);
    setError(null);
    const result = await command<Record<string, unknown>>(
      "/v1/admin/staff-keys",
      {
        name: name.trim(),
        scopes: write ? ["settings:read", "settings:write"] : ["settings:read"],
      },
      newKey(),
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    const key = typeof result.data.key === "string" ? result.data.key : "";
    setMade({ key, row: normalizeStaffKey(result.data) });
    setOpen(false);
    setName("");
    setWrite(false);
    router.refresh();
  };

  return (
    <div className={styles.staff}>
      <p className={styles.muted}>
        For the Admin command line and MCP:{" "}
        <a href="/tools/ac-admin.py" download>
          download ac-admin.py
        </a>
        , make a key here within {data.limits.freshMinutes} minutes of signing
        in, then <code className={styles.code}>export AC_ADMIN_KEY=…</code>. A
        key reaches only Admin settings, lasts {data.limits.days} days and never
        shows again.
      </p>

      {made ? (
        <div className={styles.made} role="status">
          <strong>
            Your new key, {made.row.name}: copy it now, it won&rsquo;t show
            again.
          </strong>
          <code className={styles.secret}>{made.key}</code>
          <span className={styles.badges}>
            <button
              type="button"
              className={kitStyles.button}
              data-variant="primary"
              onClick={async () => {
                await navigator.clipboard
                  ?.writeText(made.key)
                  .catch(() => undefined);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy key"}
            </button>
            <button
              type="button"
              className={kitStyles.button}
              data-variant="ghost"
              onClick={() => {
                setMade(null);
                setCopied(false);
              }}
            >
              Done, hide it
            </button>
          </span>
        </div>
      ) : null}

      {data.keys.length ? (
        <ul className={styles.apps} aria-label="Your staff keys">
          {data.keys.map((key) => (
            <li key={key.id}>
              <strong>{key.name}</strong>
              <code className={styles.code}>{key.prefix}…</code>
              <Badge tone={STATE_TONE[key.state]}>
                {key.state === "active"
                  ? "Active"
                  : key.state === "expired"
                    ? "Expired"
                    : "Revoked"}
              </Badge>
              <span className={styles.scopes}>
                {key.scopes.map((scope) => (
                  <code key={scope}>{scope}</code>
                ))}
              </span>
              <small className={styles.muted}>
                {key.lastUsedAt
                  ? `Last used ${when(key.lastUsedAt)}`
                  : "Never used"}
                {key.state === "active" && key.expiresAt
                  ? ` · ends ${when(key.expiresAt)}`
                  : ""}
              </small>
              {key.state === "active" ? (
                <IntegrationAction kind="staff" id={key.id} name={key.name} />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {open ? (
        <form
          className={styles.makeForm}
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim() && !busy) void make();
          }}
        >
          <input
            aria-label="Key name"
            placeholder="Name, e.g. Laptop CLI"
            maxLength={80}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={write}
              onChange={(event) => setWrite(event.target.checked)}
            />
            May change settings
          </label>
          <button
            type="submit"
            className={kitStyles.button}
            data-variant="primary"
            disabled={busy || !name.trim()}
          >
            {busy ? "Making…" : "Make key"}
          </button>
          <button
            type="button"
            className={kitStyles.button}
            data-variant="ghost"
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
        </form>
      ) : (
        <button
          type="button"
          className={kitStyles.button}
          disabled={full}
          title={
            full
              ? `You hold ${data.limits.active} active keys: revoke one first.`
              : undefined
          }
          onClick={() => setOpen(true)}
        >
          Make a staff key
        </button>
      )}
      {error ? (
        <p className={kitStyles.fieldError} role="alert">
          {error}
          {/sign in again/i.test(error) ? (
            <>
              {" "}
              <a href="/login">Sign in again</a>
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
