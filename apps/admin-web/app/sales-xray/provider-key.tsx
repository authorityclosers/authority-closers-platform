"use client";

/**
 * A provider's key in this environment (Providers hub slice 2, owner 20 Oct 2026: "add key
 * and boom it's there"). Paste a key and it is sealed here at once, never shown again: the
 * page keeps only its last four characters. "Test connection" makes the provider's free
 * read and says in plain words whether the key works and how many models it can use.
 * Adding needs a sign-in within the last few minutes; the key goes to the API only.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { Badge, Button, kitStyles } from "../ui/kit";
import {
  agoWords,
  keyTestWords,
  type HubProvider,
  type KeyTest,
  type ProviderKeys,
} from "./provider-hub-data";
import styles from "./provider-hub.module.css";

const path = (provider: string, action = "") =>
  `/v1/admin/providers/${provider}/key${action}`;

export function ProviderKey({
  provider,
  keys,
}: {
  provider: HubProvider;
  keys: ProviderKeys;
}) {
  const router = useRouter();
  const held = keys.keys[provider.id] ?? null;
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<KeyTest | null>(null);

  const save = async () => {
    setBusy("save");
    setError(null);
    const answer = await send("POST", path(provider.id), { key: value }, null);
    setBusy(null);
    // The field empties either way: the key is never kept in the page.
    setValue("");
    if (!answer.ok) {
      setError(answer.message);
      return;
    }
    setOpen(false);
    setResult(null);
    router.refresh();
  };

  const test = async () => {
    setBusy("test");
    setError(null);
    const answer = await send<Record<string, unknown>>(
      "POST",
      path(provider.id, "/test"),
      {},
      null,
    );
    setBusy(null);
    if (!answer.ok) {
      setError(answer.message);
      return;
    }
    setResult({
      at: typeof answer.data.at === "string" ? answer.data.at : "",
      ok: typeof answer.data.ok === "boolean" ? answer.data.ok : null,
      status:
        typeof answer.data.status === "number" ? answer.data.status : null,
      models:
        typeof answer.data.models === "number" ? answer.data.models : null,
      words: typeof answer.data.words === "string" ? answer.data.words : "",
      fix: typeof answer.data.fix === "string" ? answer.data.fix : null,
    });
    router.refresh();
  };

  const remove = async () => {
    setBusy("remove");
    setError(null);
    const answer = await send("POST", path(provider.id, "/remove"), {}, null);
    setBusy(null);
    if (!answer.ok) {
      setError(answer.message);
      return;
    }
    setResult(null);
    router.refresh();
  };

  const shown = result ?? held?.tested ?? null;

  return (
    <section
      className={styles.keyPanel}
      aria-label={`${provider.name} key in ${keys.environment}`}
    >
      <h3>Key in {keys.environment}</h3>
      {held ? (
        <p className={styles.keyLine}>
          <span>
            Key ending <code>{held.hint}</code>, added{" "}
            <span suppressHydrationWarning>{agoWords(held.addedAt)}</span>
          </span>
          {shown ? (
            <Badge
              tone={shown.ok === false ? "warn" : shown.ok ? "good" : "neutral"}
            >
              {shown.ok === false
                ? "Not working"
                : shown.ok
                  ? "Works"
                  : "Untested"}
            </Badge>
          ) : (
            <Badge>Not tested yet</Badge>
          )}
        </p>
      ) : (
        <p className={styles.muted}>
          {keys.sealing
            ? "No key here yet. Add one and it is sealed for this environment, never shown again."
            : `Keys can't be sealed in ${keys.environment} yet: Root gives this environment's API its platform key first.`}
        </p>
      )}
      {shown ? (
        <p className={styles.keyResult} role="status">
          {keyTestWords(shown)}
          {shown.fix === "console" && provider.console ? (
            <>
              {" "}
              <a href={provider.console} target="_blank" rel="noreferrer">
                {shown.status === 402 ? "Top up credit" : "Open the console"}
              </a>
            </>
          ) : null}
        </p>
      ) : null}
      {open ? (
        <form
          className={styles.keyForm}
          onSubmit={(event) => {
            event.preventDefault();
            if (value.trim()) void save();
          }}
        >
          <label>
            <span>{provider.name} API key</span>
            <input
              type="password"
              name="provider-key"
              autoComplete="off"
              spellCheck={false}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="Paste the key from the provider's console"
            />
          </label>
          <small className={styles.muted}>
            Sealed for {keys.environment} the moment you save; nobody can read
            it back, not even here. Needs a sign-in within the last{" "}
            {keys.freshMinutes} minutes.
          </small>
          <div className={styles.keyActions}>
            <Button
              type="submit"
              variant="primary"
              disabled={busy !== null || !value.trim()}
            >
              {busy === "save" ? "Sealing…" : "Seal key"}
            </Button>
            <Button
              onClick={() => {
                setOpen(false);
                setValue("");
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : keys.sealing ? (
        <div className={styles.keyActions}>
          {held ? (
            <Button
              variant="primary"
              disabled={busy !== null}
              onClick={() => void test()}
            >
              {busy === "test" ? "Testing…" : "Test connection"}
            </Button>
          ) : null}
          <Button
            variant={held ? "secondary" : "primary"}
            disabled={busy !== null}
            onClick={() => setOpen(true)}
          >
            {held ? "Replace key" : "Add key"}
          </Button>
          {held ? (
            <Button
              variant="ghost"
              disabled={busy !== null}
              onClick={() => void remove()}
            >
              {busy === "remove" ? "Removing…" : "Remove"}
            </Button>
          ) : null}
        </div>
      ) : null}
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
    </section>
  );
}
