"use client";

/**
 * Settings -> Security -> Sign-in methods (orchestrator, 19 Oct 2026: self-serve).
 * Lists every way into the account with when it was added and last used, and removes
 * Google, Apple or Facebook. The server allows a removal only within 10 minutes of a
 * sign-in and never the last way in; it emails the account and audits the change.
 */

import { useEffect, useRef, useState } from "react";

import { notify } from "./notice-center";
import styles from "./account-view.module.css";

export type MethodKind =
  | "email_code"
  | "password"
  | "google"
  | "apple"
  | "facebook";
export type SignInMethod = {
  kind: MethodKind;
  addedAt: string | null;
  lastUsedAt: string | null;
  removable: boolean;
};
type Loaded =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "ready"; methods: SignInMethod[]; freshMinutes: number };

const LABELS: Record<MethodKind, string> = {
  email_code: "Email code",
  password: "Password",
  google: "Google",
  apple: "Apple",
  facebook: "Facebook",
};
const KINDS = new Set<string>(Object.keys(LABELS));
const REMOVABLE_KINDS = new Set<MethodKind>(["google", "apple", "facebook"]);
const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function when(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : DATE.format(parsed);
}

export function parseSignInMethods(
  value: unknown,
): { methods: SignInMethod[]; freshMinutes: number } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  if (!Array.isArray(body.methods)) return null;
  const methods: SignInMethod[] = [];
  for (const raw of body.methods) {
    if (!raw || typeof raw !== "object") return null;
    const item = raw as Record<string, unknown>;
    if (typeof item.kind !== "string" || !KINDS.has(item.kind)) continue;
    methods.push({
      kind: item.kind as MethodKind,
      addedAt: typeof item.added_at === "string" ? item.added_at : null,
      lastUsedAt:
        typeof item.last_used_at === "string" ? item.last_used_at : null,
      removable:
        item.removable === true && REMOVABLE_KINDS.has(item.kind as MethodKind),
    });
  }
  const minutes =
    typeof body.fresh_minutes === "number" && body.fresh_minutes > 0
      ? body.fresh_minutes
      : 10;
  return { methods, freshMinutes: minutes };
}

function hint(method: SignInMethod): string {
  if (method.kind === "email_code")
    return "A one-time code to your email address.";
  const parts = [
    when(method.addedAt) ? `Added ${when(method.addedAt)}` : null,
    when(method.lastUsedAt) ? `last used ${when(method.lastUsedAt)}` : null,
  ].filter(Boolean);
  if (method.kind === "password" && parts.length === 0)
    return "Your Authority Closers password.";
  return parts.join(", ") || "On your account.";
}

export function SignInMethods({ active }: { active: boolean }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [confirming, setConfirming] = useState<MethodKind | null>(null);
  const [busy, setBusy] = useState<MethodKind | null>(null);
  const [needsFreshSignIn, setNeedsFreshSignIn] = useState<MethodKind | null>(
    null,
  );
  const started = useRef(false);

  useEffect(() => {
    if (!active && !started.current) return;
    started.current = true;
    const controller = new AbortController();
    fetch("/v1/me/sign-in-methods", {
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: { accept: "application/json" },
    })
      .then(async (response) => {
        const parsed = response.ok
          ? parseSignInMethods(await response.json())
          : null;
        if (controller.signal.aborted) return;
        setLoaded(parsed ? { state: "ready", ...parsed } : { state: "failed" });
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoaded({ state: "failed" });
      });
    return () => controller.abort();
  }, [active, attempt]);

  async function remove(kind: MethodKind) {
    if (confirming !== kind) {
      setConfirming(kind);
      setNeedsFreshSignIn(null);
      return;
    }
    setConfirming(null);
    setBusy(kind);
    try {
      const response = await fetch(`/v1/me/sign-in-methods/${kind}/remove`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { accept: "application/json" },
      });
      if (response.ok) {
        notify({
          id: "sign-in-method-removed",
          tone: "success",
          title: `${LABELS[kind]} sign-in removed`,
          message: "We emailed you about this change.",
          timeout: 6000,
        });
        setAttempt((value) => value + 1);
        return;
      }
      const body = (await response.json().catch(() => null)) as {
        detail?: { code?: unknown; message?: unknown };
      } | null;
      if (body?.detail?.code === "fresh_sign_in") {
        setNeedsFreshSignIn(kind);
        return;
      }
      notify({
        id: "sign-in-method-removed",
        tone: "error",
        title: `${LABELS[kind]} sign-in wasn’t removed`,
        message:
          typeof body?.detail?.message === "string"
            ? body.detail.message
            : "Try again in a moment.",
      });
      setAttempt((value) => value + 1);
    } catch {
      notify({
        id: "sign-in-method-removed",
        tone: "error",
        title: `${LABELS[kind]} sign-in wasn’t removed`,
        message: "Check your connection and try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  if (loaded.state === "loading")
    return (
      <div className={styles.row} aria-busy="true">
        <div className={styles.rowText}>
          <span className={styles.rowLabel}>Sign-in methods</span>
          <span className={styles.rowHint}>Loading…</span>
        </div>
      </div>
    );
  if (loaded.state === "failed")
    return (
      <div className={styles.row}>
        <div className={styles.rowText}>
          <span className={styles.rowLabel}>Sign-in methods</span>
          <span className={styles.rowHint}>
            Your sign-in methods couldn’t be loaded.
          </span>
        </div>
        <div className={styles.rowControl}>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => setAttempt((value) => value + 1)}
          >
            Try again
          </button>
        </div>
      </div>
    );
  return (
    <section aria-label="Sign-in methods">
      {loaded.methods.map((method) => (
        <div className={styles.row} key={method.kind}>
          <div className={styles.rowText}>
            <span className={styles.rowLabel}>{LABELS[method.kind]}</span>
            <span className={styles.rowHint}>
              {needsFreshSignIn === method.kind
                ? `For your safety, sign out below and sign in again, then remove it within ${loaded.freshMinutes} minutes.`
                : hint(method)}
            </span>
          </div>
          {method.removable ? (
            <div className={styles.rowControl}>
              <button
                type="button"
                className={styles.danger}
                disabled={busy !== null}
                onClick={() => void remove(method.kind)}
              >
                {busy === method.kind
                  ? "Removing…"
                  : confirming === method.kind
                    ? `Remove ${LABELS[method.kind]}?`
                    : "Remove"}
              </button>
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
}
