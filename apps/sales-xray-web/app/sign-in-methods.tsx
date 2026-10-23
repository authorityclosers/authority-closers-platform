"use client";

/**
 * Settings -> Sign-in & security -> Sign-in methods (orchestrator, 19 Oct 2026:
 * self-serve; owner, 20 Oct: "connect google account, connect facebook account
 * inside the settings"). Lists every way into the account with when it was
 * added and last used, connects Google, Apple or Facebook where this
 * environment offers them, and removes them again. The server allows a change
 * only within 10 minutes of a sign-in and never removes the last way in; it
 * emails the account and audits the change. API: docs/product/identity/
 * sign-in-methods-api.md.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { KeyRound, Mail, type LucideIcon } from "lucide-react";

import { inPhoneApp } from "./leads/native-phone";
import { notify } from "./notice-center";
import { goToProvider } from "./sign-in-connect";
import { BrandTile } from "./ui/brand-tile";
import styles from "./account-view.module.css";
import local from "./sign-in-methods.module.css";

export type MethodKind =
  | "email_code"
  | "password"
  | "google"
  | "apple"
  | "facebook";
type ProviderKind = "google" | "apple" | "facebook";
export type SignInMethod = {
  kind: MethodKind;
  addedAt: string | null;
  lastUsedAt: string | null;
  removable: boolean;
};
/** A provider this environment offers, and whether the account has it. */
export type ConnectOption = {
  kind: ProviderKind;
  label: string;
  connected: boolean;
};
type Loaded =
  | { state: "loading" }
  | { state: "failed" }
  | {
      state: "ready";
      methods: SignInMethod[];
      available: ConnectOption[];
      freshMinutes: number;
    };

const LABELS: Record<MethodKind, string> = {
  email_code: "Email code",
  password: "Password",
  google: "Google",
  apple: "Apple",
  facebook: "Facebook",
};
const KINDS = new Set<string>(Object.keys(LABELS));
// Only a provider can be connected or removed; email code and password stay.
const PROVIDERS = new Set<string>(["google", "apple", "facebook"]);
const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});
// Where the provider sends the person back: this section.
const RETURN_TO = "/settings/security";
// Which provider a Connect went to, for the card on the way back.
const PENDING_KEY = "sx.signInConnect";

const isProvider = (value: unknown): value is ProviderKind =>
  typeof value === "string" && PROVIDERS.has(value);

function when(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : DATE.format(parsed);
}

export function parseSignInMethods(value: unknown): {
  methods: SignInMethod[];
  available: ConnectOption[];
  freshMinutes: number;
} | null {
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
      removable: item.removable === true && PROVIDERS.has(item.kind),
    });
  }
  const available: ConnectOption[] = [];
  for (const raw of Array.isArray(body.available) ? body.available : []) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    if (!isProvider(item.kind)) continue;
    available.push({
      kind: item.kind,
      label: typeof item.label === "string" ? item.label : LABELS[item.kind],
      // The account's own list wins if the two ever disagree.
      connected:
        item.connected === true ||
        methods.some((method) => method.kind === item.kind),
    });
  }
  const minutes =
    typeof body.fresh_minutes === "number" && body.fresh_minutes > 0
      ? body.fresh_minutes
      : 10;
  return { methods, available, freshMinutes: minutes };
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

// Each way in by its logo; email code and password by an icon.
const TILES: Record<MethodKind, { brands?: string[]; icon?: LucideIcon }> = {
  email_code: { icon: Mail },
  password: { icon: KeyRound },
  google: { brands: ["google"] },
  apple: { brands: ["apple"] },
  facebook: { brands: ["facebook"] },
};

/** The corner card for the way back from a provider, or null. */
export function connectReturnNotice(
  search: string,
  pending: string | null,
): Parameters<typeof notify>[0] | null {
  const params = new URLSearchParams(search);
  const connected = params.get("connected");
  const error = params.get("connect_error");
  if (!connected && !error) return null;
  const provider = isProvider(connected)
    ? connected
    : isProvider(pending)
      ? pending
      : null;
  const name = provider ? LABELS[provider] : "That account";
  if (connected)
    return {
      id: "sign-in-connect",
      tone: "success",
      title: `${name} is connected`,
      message: provider
        ? `You can now sign in with ${name}.`
        : "You can now sign in with it.",
      timeout: 6000,
    };
  return {
    id: "sign-in-connect",
    tone: error === "cancelled" ? "info" : "error",
    title:
      error === "in_use"
        ? `${provider ? `That ${name} account` : name} is already used by another Sales X-Ray account`
        : error === "cancelled"
          ? `${name} wasn’t connected`
          : `Couldn’t connect ${provider ? name : "that account"}`,
    message:
      error === "in_use"
        ? "Sign in with it to use that account, or connect a different one."
        : error === "cancelled"
          ? "You stopped before it finished. Connect again when you’re ready."
          : "Try again in a moment.",
    timeout: error === "cancelled" ? 6000 : undefined,
  };
}

const noSubscription = () => () => {};

export function SignInMethods({ active }: { active: boolean }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [confirming, setConfirming] = useState<MethodKind | null>(null);
  const [busy, setBusy] = useState<MethodKind | null>(null);
  // "remove:google" or "connect:facebook": the change that needs a fresh sign-in.
  const [needsFreshSignIn, setNeedsFreshSignIn] = useState<string | null>(null);
  const started = useRef(false);
  const returned = useRef(false);
  // Provider pages open in the phone's browser, which has no Sales Xray session.
  const phoneApp = useSyncExternalStore(
    noSubscription,
    inPhoneApp,
    () => false,
  );

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

  // Back from Google, Apple or Facebook: say how it went once, then drop the
  // query so a reload does not say it again.
  useEffect(() => {
    if (!active || returned.current) return;
    returned.current = true;
    let pending: string | null = null;
    try {
      pending = window.sessionStorage.getItem(PENDING_KEY);
      window.sessionStorage.removeItem(PENDING_KEY);
    } catch {
      pending = null;
    }
    const notice = connectReturnNotice(window.location.search, pending);
    if (!notice) return;
    notify(notice);
    const params = new URLSearchParams(window.location.search);
    params.delete("connected");
    params.delete("connect_error");
    const query = params.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
    );
  }, [active]);

  async function connect(kind: ProviderKind) {
    setConfirming(null);
    setNeedsFreshSignIn(null);
    setBusy(kind);
    try {
      const response = await fetch(`/v1/me/sign-in-methods/${kind}/connect`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({ return_to: RETURN_TO }),
      });
      const body = (await response.json().catch(() => null)) as {
        redirect_url?: unknown;
        detail?: unknown;
        code?: unknown;
      } | null;
      if (response.ok && typeof body?.redirect_url === "string") {
        const target = new URL(body.redirect_url, window.location.origin);
        if (
          target.protocol === "https:" ||
          target.origin === window.location.origin
        ) {
          try {
            window.sessionStorage.setItem(PENDING_KEY, kind);
          } catch {
            // Without storage the card on the way back names no provider.
          }
          goToProvider(target.href);
          return;
        }
      }
      if (body?.code === "fresh_sign_in") {
        setNeedsFreshSignIn(`connect:${kind}`);
        notify({
          id: "sign-in-connect",
          tone: "info",
          title: "Sign in again to connect",
          message: `For your safety, sign out and back in, then connect ${LABELS[kind]} within 10 minutes.`,
          timeout: 8000,
        });
        setBusy(null);
        return;
      }
      if (body?.code === "already_connected") setAttempt((value) => value + 1);
      notify({
        id: "sign-in-connect",
        tone: body?.code === "already_connected" ? "info" : "error",
        title:
          body?.code === "already_connected"
            ? `${LABELS[kind]} is already connected`
            : `${LABELS[kind]} wasn’t connected`,
        message:
          typeof body?.detail === "string"
            ? body.detail
            : "Try again in a moment.",
      });
    } catch {
      notify({
        id: "sign-in-connect",
        tone: "error",
        title: `${LABELS[kind]} wasn’t connected`,
        message: "Check your connection and try again.",
      });
    }
    setBusy(null);
  }

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
        setNeedsFreshSignIn(`remove:${kind}`);
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
    // The rows' own outline, so nothing moves when the list arrives.
    return (
      <section aria-label="Sign-in methods" aria-busy="true">
        {[0, 1, 2].map((index) => (
          <div className={styles.row} key={index}>
            <div className={local.lead}>
              <span className={local.placeholderTile} />
              <span className={local.placeholderText}>
                <i />
                <i />
              </span>
            </div>
          </div>
        ))}
      </section>
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
  const toConnect = loaded.available.filter((option) => !option.connected);
  return (
    <section aria-label="Sign-in methods">
      {loaded.methods.map((method) => (
        <div className={styles.row} key={method.kind}>
          <div className={local.lead}>
            <BrandTile {...TILES[method.kind]} size={36} />
            <div className={styles.rowText}>
              <span className={styles.rowLabel}>{LABELS[method.kind]}</span>
              <span className={styles.rowHint}>
                {needsFreshSignIn === `remove:${method.kind}`
                  ? `For your safety, sign out below and sign in again, then remove it within ${loaded.freshMinutes} minutes.`
                  : hint(method)}
              </span>
            </div>
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
      {toConnect.map((option) => (
        <div
          className={styles.row}
          key={option.kind}
          data-connect={option.kind}
        >
          <div className={local.lead}>
            <BrandTile brands={[option.kind]} size={36} />
            <div className={styles.rowText}>
              <span className={styles.rowLabel}>{option.label}</span>
              <span className={styles.rowHint}>
                {needsFreshSignIn === `connect:${option.kind}`
                  ? `For your safety, sign out below and sign in again, then connect it within ${loaded.freshMinutes} minutes.`
                  : phoneApp
                    ? `Connect ${option.label} from a computer or your phone’s browser.`
                    : `Not connected. Sign in with your ${option.label} account too.`}
              </span>
            </div>
          </div>
          {phoneApp ? null : (
            <div className={styles.rowControl}>
              <button
                type="button"
                className={`${styles.secondary} ${local.connect}`}
                disabled={busy !== null}
                onClick={() => void connect(option.kind)}
              >
                {busy === option.kind ? "Opening…" : "Connect"}
              </button>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
