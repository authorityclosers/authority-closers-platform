"use client";

import { LogOut, RefreshCw, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useState, type FormEvent } from "react";

import { useSalesXraySignOut } from "./account-navigation";
import { notify } from "./notice-center";
import styles from "./account-view.module.css";
import own from "./account-delete.module.css";

/**
 * Settings → Security → Delete account (Google Play, 23 Oct 2026: apps with
 * sign-up must let people start deletion inside the app).
 *
 * It opens under its row (no sheet on top of Settings), says what happens, and
 * asks for one thing at a time: a new owner for an organisation that has other
 * members, a fresh sign-in, then DELETE typed. The server closes the account
 * and signs it out everywhere (/v1/me/account-deletion); the data goes through
 * the owner-approved deletion process within 2 days, as /data-deletion says.
 */

const PATH = "/v1/me/account-deletion";
export const ACCOUNT_CLOSED_PATH = "/account-closed";

type Organisation = { id: string; name: string; otherMembers: number };
type Preview = {
  confirmWord: string;
  freshSignIn: boolean;
  freshMinutes: number;
  staff: boolean;
  transferFirst: Organisation[];
  closesWithAccount: Organisation[];
};
type Step =
  | { state: "loading" }
  | { state: "error" }
  | { state: "ready"; preview: Preview };

function organisations(value: unknown): Organisation[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const raw = item as Record<string, unknown>;
    if (typeof raw.id !== "string" || typeof raw.name !== "string") return [];
    return [
      {
        id: raw.id,
        name: raw.name,
        otherMembers:
          typeof raw.other_members === "number" ? raw.other_members : 0,
      },
    ];
  });
}

export function parsePreview(value: unknown): Preview | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  if (typeof body.confirm_word !== "string" || !body.confirm_word) return null;
  return {
    confirmWord: body.confirm_word,
    freshSignIn: body.fresh_sign_in === true,
    freshMinutes:
      typeof body.fresh_minutes === "number" && body.fresh_minutes > 0
        ? body.fresh_minutes
        : 10,
    staff: body.staff === true,
    transferFirst: organisations(body.transfer_first),
    closesWithAccount: organisations(body.closes_with_account),
  };
}

function people(count: number) {
  return count === 1 ? "1 other member" : `${count} other members`;
}

export function DeleteAccountRow() {
  const [open, setOpen] = useState(false);
  const regionId = useId();
  return (
    <>
      <div className={styles.row}>
        <div className={styles.rowText}>
          <span className={styles.rowLabel}>Delete account</span>
          <span className={styles.rowHint}>
            Close your account and delete its data.
          </span>
        </div>
        <div className={styles.rowControl}>
          <button
            type="button"
            className={styles.danger}
            aria-expanded={open}
            aria-controls={regionId}
            onClick={() => setOpen((value) => !value)}
          >
            <Trash2 size={15} aria-hidden="true" />
            Delete account
          </button>
        </div>
      </div>
      {open ? (
        <DeleteAccountFlow id={regionId} onCancel={() => setOpen(false)} />
      ) : null}
    </>
  );
}

function DeleteAccountFlow({
  id,
  onCancel,
}: {
  id: string;
  onCancel: () => void;
}) {
  const [step, setStep] = useState<Step>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [typed, setTyped] = useState("");
  const [sending, setSending] = useState(false);
  const { signOut, signingOut } = useSalesXraySignOut();
  const inputId = useId();
  const hintId = useId();

  useEffect(() => {
    const controller = new AbortController();
    setStep({ state: "loading" });
    void fetch(PATH, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        const preview = response.ok
          ? parsePreview(await response.json())
          : null;
        if (controller.signal.aborted) return;
        setStep(preview ? { state: "ready", preview } : { state: "error" });
      })
      .catch(() => {
        if (!controller.signal.aborted) setStep({ state: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  const recheck = useCallback(() => setAttempt((value) => value + 1), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step.state !== "ready" || sending) return;
    const word = step.preview.confirmWord;
    if (typed.trim().toUpperCase() !== word) return;
    setSending(true);
    try {
      const response = await fetch(PATH, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({ confirm: word }),
      });
      if (response.ok) {
        // The server signed this account out everywhere; drop this document too.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- the closed account must leave the signed-in document and route cache.
        window.location.assign(ACCOUNT_CLOSED_PATH);
        return;
      }
      const body = (await response.json().catch(() => null)) as {
        detail?: { code?: unknown; message?: unknown };
      } | null;
      const code = body?.detail?.code;
      if (
        code === "fresh_sign_in" ||
        code === "transfer_ownership_first" ||
        code === "staff"
      ) {
        // Something changed since the preview: show the step it now needs.
        recheck();
      } else {
        notify({
          id: "delete-account",
          tone: "error",
          title: "Your account wasn’t deleted",
          message:
            typeof body?.detail?.message === "string"
              ? body.detail.message
              : "Try again in a moment.",
        });
      }
    } catch {
      notify({
        id: "delete-account",
        tone: "error",
        title: "Your account wasn’t deleted",
        message: "Check your connection and try again.",
      });
    }
    setSending(false);
  }

  if (step.state === "loading") {
    return (
      <div
        id={id}
        className={styles.deleteAccount}
        role="region"
        aria-label="Delete account"
      >
        <p className={styles.muted} role="status">
          Checking your account…
        </p>
      </div>
    );
  }
  if (step.state === "error") {
    return (
      <div
        id={id}
        className={styles.deleteAccount}
        role="region"
        aria-label="Delete account"
      >
        <p className={styles.muted}>We couldn’t check your account just now.</p>
        <div className={styles.deleteAccountActions}>
          <button type="button" className={styles.secondary} onClick={recheck}>
            <RefreshCw size={15} aria-hidden="true" /> Try again
          </button>
        </div>
      </div>
    );
  }

  const { preview } = step;
  const matches = typed.trim().toUpperCase() === preview.confirmWord;
  return (
    <div
      id={id}
      className={styles.deleteAccount}
      role="region"
      aria-label="Delete account"
    >
      <div className={own.summary}>
        <p className={own.lead}>
          Your account closes at once and you’re signed out on every device.
          Within 2 days we delete:
        </p>
        <ul className={own.list}>
          <li>Your name, email address and mobile number</li>
          <li>Your recordings, transcripts and reports</li>
          <li>Your leads, with their notes and call history</li>
          <li>The connection to any Facebook Page you linked</li>
        </ul>
        {preview.closesWithAccount.map((organisation) => (
          <p key={organisation.id} className={styles.muted}>
            <strong>{organisation.name}</strong> closes too, because you’re its
            only member.
          </p>
        ))}
        <p className={styles.muted}>
          We keep invoices that tax law requires, a record of this request, and
          backups, which this doesn’t delete.{" "}
          <a href="/data-deletion" target="_blank" rel="noopener">
            How deletion works
          </a>
        </p>
      </div>

      {preview.staff ? (
        <div className={own.step}>
          <p className={own.stepTitle}>The owner closes staff accounts</p>
          <p className={styles.muted}>
            This account has staff access. Write to admin@authorityclosers.com
            to have it closed.
          </p>
        </div>
      ) : preview.transferFirst.length ? (
        <div className={own.step}>
          <p className={own.stepTitle}>First, choose a new owner</p>
          <p className={styles.muted}>
            Your team keeps its workspace when someone else owns it.
          </p>
          <ul className={own.organisations}>
            {preview.transferFirst.map((organisation) => (
              <li key={organisation.id}>
                <span className={own.organisationName}>
                  {organisation.name}
                </span>
                <span className={styles.muted}>
                  {people(organisation.otherMembers)}
                </span>
              </li>
            ))}
          </ul>
          <div className={styles.deleteAccountActions}>
            <Link className={styles.secondary} href="/organisation">
              <Users size={15} aria-hidden="true" /> Choose a new owner
            </Link>
            <button
              type="button"
              className={styles.secondary}
              onClick={recheck}
            >
              <RefreshCw size={15} aria-hidden="true" /> Check again
            </button>
          </div>
        </div>
      ) : !preview.freshSignIn ? (
        <div className={own.step}>
          <p className={own.stepTitle}>Sign in again first</p>
          <p className={styles.muted}>
            For your safety, sign out and back in, then delete your account
            within {preview.freshMinutes} minutes.
          </p>
          <div className={styles.deleteAccountActions}>
            <button
              type="button"
              className={styles.secondary}
              disabled={signingOut}
              onClick={() => void signOut()}
            >
              <LogOut size={15} aria-hidden="true" />
              {signingOut ? "Signing out…" : "Sign out to sign in again"}
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={onCancel}
            >
              Not now
            </button>
          </div>
        </div>
      ) : (
        <form className={own.step} onSubmit={(event) => void submit(event)}>
          <label className={own.stepTitle} htmlFor={inputId}>
            Type {preview.confirmWord} to confirm
          </label>
          <input
            id={inputId}
            className={own.confirm}
            value={typed}
            autoComplete="off"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            aria-describedby={hintId}
            onChange={(event) => setTyped(event.target.value)}
          />
          <p id={hintId} className={styles.muted}>
            Changed your mind later? Write to admin@authorityclosers.com before
            the 2 days are up.
          </p>
          <div className={styles.deleteAccountActions}>
            <button
              type="submit"
              className={own.destroy}
              disabled={!matches || sending}
            >
              <Trash2 size={15} aria-hidden="true" />
              {sending ? "Deleting…" : "Delete my account"}
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={onCancel}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
