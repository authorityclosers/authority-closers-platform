"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { newIdempotencyKey } from "@ac/operations-web/api";
import { z } from "zod";

import { useAdminSession } from "../lib/admin-session";
import styles from "./minute-account-admin.module.css";

const SAFE_INTEGER = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const MAX_GRANT_MINUTES = Math.floor((Number.MAX_SAFE_INTEGER - 3_600) / 60);

const targetSchema = z
  .object({
    tenant_id: z.string().uuid(),
    person_id: z.string().uuid(),
    display_name: z.string().min(1),
    username: z.string().max(100).nullable(),
    masked_email: z.string().min(1),
  })
  .strict();

const resolveSchema = z.object({ target: targetSchema.nullable() }).strict();

const grantHistorySchema = z
  .object({
    grant_id: z.string().min(1),
    seconds: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
    authorization_ref: z.string().min(1),
    granted_by: z.string().min(1),
    reason: z.string().max(500),
    created_at: z.string().min(1).nullable(),
    audit_sequence: z
      .number()
      .int()
      .positive()
      .max(Number.MAX_SAFE_INTEGER)
      .nullable(),
  })
  .strict();

const accountSchema = z
  .object({
    tenant_id: z.string().uuid(),
    person_id: z.string().uuid(),
    revision: SAFE_INTEGER,
    stored_unlimited: z.boolean(),
    effective_unlimited: z.boolean(),
    granted_seconds: SAFE_INTEGER,
    committed_seconds: SAFE_INTEGER,
    available_seconds: SAFE_INTEGER,
    available_minutes: SAFE_INTEGER,
    shared_upload_allowance_seconds: SAFE_INTEGER,
    shared_upload_committed_seconds: SAFE_INTEGER,
    shared_upload_available_seconds: SAFE_INTEGER,
    grants: z.array(grantHistorySchema),
  })
  .strict();

const grantResponseSchema = z
  .object({
    grant_id: z.string().uuid(),
    minutes: z.number().int().positive().max(MAX_GRANT_MINUTES),
    replayed: z.boolean(),
    account: accountSchema,
  })
  .strict();

type Target = z.infer<typeof targetSchema>;
type MinuteAccount = z.infer<typeof accountSchema>;
const persistedGrantSchema = z
  .object({
    version: z.literal(1),
    key: z.string().min(1).max(200),
    actorTenantId: z.string().uuid(),
    actorPersonId: z.string().uuid(),
    tenantId: z.string().uuid(),
    personId: z.string().uuid(),
    minutes: z.number().int().positive().max(MAX_GRANT_MINUTES),
    reason: z.string().min(1).max(500),
  })
  .strict();
type PersistedGrant = z.infer<typeof persistedGrantSchema>;
type GrantIntent = {
  key: string;
  actorTenantId: string;
  actorPersonId: string;
  tenantId: string;
  personId: string;
  minutes: number;
  reason: string;
  restored: boolean;
};
type PendingGrantRead =
  | { status: "none" }
  | { status: "matching"; intent: GrantIntent }
  | { status: "other-actor" }
  | { status: "invalid" }
  | { status: "unavailable" };

const PENDING_GRANT_PREFIX = "ac.admin.sales-xray.minute-grant.v1";

function pendingGrantStorageKey(
  target: Pick<Target, "tenant_id" | "person_id">,
) {
  return `${PENDING_GRANT_PREFIX}:${target.tenant_id}:${target.person_id}`;
}

function readPendingGrant(
  target: Pick<Target, "tenant_id" | "person_id">,
  actor: { tenantId: string; personId: string },
): PendingGrantRead {
  try {
    const raw = window.sessionStorage.getItem(pendingGrantStorageKey(target));
    if (raw === null) return { status: "none" };
    const parsed = persistedGrantSchema.safeParse(JSON.parse(raw));
    if (
      !parsed.success ||
      parsed.data.tenantId !== target.tenant_id ||
      parsed.data.personId !== target.person_id
    ) {
      return { status: "invalid" };
    }
    const intent = parsed.data;
    if (
      intent.actorTenantId !== actor.tenantId ||
      intent.actorPersonId !== actor.personId
    ) {
      return { status: "other-actor" };
    }
    return { status: "matching", intent: { ...intent, restored: true } };
  } catch {
    return { status: "unavailable" };
  }
}

function persistPendingGrant(intent: GrantIntent) {
  const persisted: PersistedGrant = {
    version: 1,
    key: intent.key,
    actorTenantId: intent.actorTenantId,
    actorPersonId: intent.actorPersonId,
    tenantId: intent.tenantId,
    personId: intent.personId,
    minutes: intent.minutes,
    reason: intent.reason,
  };
  window.sessionStorage.setItem(
    pendingGrantStorageKey({
      tenant_id: intent.tenantId,
      person_id: intent.personId,
    }),
    JSON.stringify(persisted),
  );
}

function clearPendingGrant(intent: GrantIntent) {
  try {
    const target = { tenant_id: intent.tenantId, person_id: intent.personId };
    const raw = window.sessionStorage.getItem(pendingGrantStorageKey(target));
    if (raw === null) return true;
    const parsed = persistedGrantSchema.safeParse(JSON.parse(raw));
    if (
      !parsed.success ||
      parsed.data.key !== intent.key ||
      parsed.data.actorTenantId !== intent.actorTenantId ||
      parsed.data.actorPersonId !== intent.actorPersonId ||
      parsed.data.tenantId !== intent.tenantId ||
      parsed.data.personId !== intent.personId
    ) {
      return false;
    }
    window.sessionStorage.removeItem(pendingGrantStorageKey(target));
    return true;
  } catch {
    return false;
  }
}

class ApiError extends Error {
  constructor(readonly status: number) {
    super("admin_api_error");
  }
}

class InvalidResponseError extends Error {
  constructor() {
    super("invalid_admin_response");
  }
}

async function requestJson(
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) throw new ApiError(response.status);
  try {
    return await response.json();
  } catch {
    throw new InvalidResponseError();
  }
}

function isExactLookup(value: string) {
  const query = value.trim();
  const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
  const phone = /^\+?[\d\s().-]{7,}$/;
  const username = /^[A-Za-z][A-Za-z0-9_]{2,29}$/;
  const email = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return (
    !uuid.test(query) &&
    !phone.test(query) &&
    (username.test(query) || email.test(query))
  );
}

function lookupError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return "Your admin session has expired. Sign in again, then retry.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "Your current account cannot manage platform access.";
  }
  if (error instanceof ApiError && error.status === 400) {
    return "Enter an exact email address or public username.";
  }
  return "Could not verify this learner account. Check the connection and try again.";
}

function grantError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return {
      definitive: true,
      text: "Your admin session has expired. Sign in again before granting minutes.",
    };
  }
  if (error instanceof ApiError && error.status === 403) {
    return {
      definitive: true,
      text: "Your current account cannot grant learner minutes.",
    };
  }
  if (
    error instanceof ApiError &&
    (error.status === 400 || error.status === 422)
  ) {
    return {
      definitive: true,
      text: "The grant was rejected. Review the amount and reason, then refresh the balance.",
    };
  }
  return {
    definitive: false,
    text: "The result is not confirmed. Keep this request unchanged and retry it to check the same grant safely.",
  };
}

function formatSeconds(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes} min ${remainder} sec` : `${minutes} min`;
}

export function MinuteAccountAdminPanel() {
  const adminSession = useAdminSession();
  const actor =
    adminSession.status === "ready"
      ? {
          tenantId: adminSession.session.tenantId,
          personId: adminSession.session.personId,
        }
      : null;
  const actorKey = actor
    ? JSON.stringify([actor.tenantId, actor.personId])
    : null;
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [account, setAccount] = useState<MinuteAccount | null>(null);
  const [lookupState, setLookupState] = useState<
    "idle" | "loading" | "ready" | "empty" | "error"
  >("idle");
  const [lookupMessage, setLookupMessage] = useState("");
  const [minutesText, setMinutesText] = useState("");
  const [reason, setReason] = useState("");
  const [grantMessage, setGrantMessage] = useState("");
  const [grantState, setGrantState] = useState<
    "idle" | "submitting" | "uncertain" | "success" | "error"
  >("idle");
  const [pendingGrant, setPendingGrant] = useState<GrantIntent | null>(null);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const lookupSequence = useRef(0);
  const lookupController = useRef<AbortController | null>(null);
  const grantIntent = useRef<GrantIntent | null>(null);
  const grantBusy = useRef(false);
  const mounted = useRef(false);
  const currentActorKey = useRef(actorKey);
  const previousActorKey = useRef(actorKey);

  useLayoutEffect(() => {
    currentActorKey.current = actorKey;
  }, [actorKey]);

  useEffect(() => {
    if (previousActorKey.current === actorKey) return;
    previousActorKey.current = actorKey;
    lookupSequence.current += 1;
    lookupController.current?.abort();
    lookupController.current = null;
    grantIntent.current = null;
    setTarget(null);
    setAccount(null);
    setLookupState("idle");
    setLookupMessage("");
    setMinutesText("");
    setReason("");
    setPendingGrant(null);
    setRecoveryBlocked(false);
    setGrantState("idle");
    setGrantMessage("");
  }, [actorKey]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      lookupSequence.current += 1;
      lookupController.current?.abort();
    };
  }, []);

  function invalidateLookup() {
    lookupSequence.current += 1;
    lookupController.current?.abort();
    lookupController.current = null;
    setTarget(null);
    setAccount(null);
    setLookupState("idle");
    setLookupMessage("");
    setRecoveryBlocked(false);
    setGrantMessage("");
    setGrantState("idle");
  }

  async function lookup() {
    if (grantIntent.current || grantBusy.current) return;
    const lookupActor = actor;
    const lookupActorKey = actorKey;
    if (!lookupActor || !lookupActorKey) {
      invalidateLookup();
      setLookupState("error");
      setLookupMessage(
        "Your admin session is not ready. Sign in and try again.",
      );
      return;
    }
    const normalized = query.trim();
    if (!isExactLookup(normalized)) {
      invalidateLookup();
      setLookupState("error");
      setLookupMessage(
        "Enter an exact email address or public username. Partial names, phone numbers, and IDs are not searched.",
      );
      return;
    }

    lookupController.current?.abort();
    const controller = new AbortController();
    lookupController.current = controller;
    const sequence = ++lookupSequence.current;
    setTarget(null);
    setAccount(null);
    setLookupState("loading");
    setLookupMessage("Verifying exact account and current balance…");
    setGrantMessage("");
    setGrantState("idle");

    const current = () =>
      !controller.signal.aborted &&
      sequence === lookupSequence.current &&
      currentActorKey.current === lookupActorKey;
    try {
      const resolved = resolveSchema.parse(
        await requestJson(
          "/v1/admin/conversation-minute-accounts/resolve-target",
          {
            method: "POST",
            signal: controller.signal,
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ query: normalized }),
          },
        ),
      );
      if (!current()) return;
      if (!resolved.target) {
        setLookupState("empty");
        setLookupMessage(
          "No eligible learner matched that exact email or public username.",
        );
        return;
      }
      setTarget(resolved.target);
      setLookupMessage("Account verified. Loading the canonical balance…");
      const accountValue = accountSchema.parse(
        await requestJson(
          `/v1/admin/conversation-minute-accounts/${encodeURIComponent(resolved.target.tenant_id)}/${encodeURIComponent(resolved.target.person_id)}`,
          { signal: controller.signal },
        ),
      );
      if (!current()) return;
      if (
        accountValue.tenant_id !== resolved.target.tenant_id ||
        accountValue.person_id !== resolved.target.person_id
      ) {
        throw new InvalidResponseError();
      }
      const recovery = readPendingGrant(resolved.target, lookupActor);
      if (!current()) return;
      setAccount(accountValue);
      setLookupState("ready");
      setRecoveryBlocked(false);
      if (recovery.status === "matching") {
        grantIntent.current = recovery.intent;
        setPendingGrant(recovery.intent);
        setMinutesText(String(recovery.intent.minutes));
        setReason(recovery.intent.reason);
        setGrantState("uncertain");
        setGrantMessage(
          "A previous grant result is unresolved. The original request was recovered for this administrator; retry it with the same key to confirm.",
        );
        setLookupMessage(
          "Verified learner account and current balance. A previous grant for this account still needs confirmation.",
        );
      } else if (recovery.status === "other-actor") {
        setRecoveryBlocked(true);
        setLookupMessage(
          "Verified learner account and current balance. A prior grant for this account is unresolved under another administrator; no new grant can be started here.",
        );
      } else if (
        recovery.status === "invalid" ||
        recovery.status === "unavailable"
      ) {
        setRecoveryBlocked(true);
        setLookupMessage(
          "Verified learner account and current balance. A pending grant could not be safely recovered; no new grant can be started.",
        );
      } else {
        setLookupMessage(
          "Verified learner account and current canonical balance.",
        );
      }
    } catch (error) {
      if (!current()) return;
      setTarget(null);
      setAccount(null);
      setLookupState("error");
      setLookupMessage(lookupError(error));
    }
  }

  async function submitGrant() {
    if (grantBusy.current) return;
    let intent = grantIntent.current;
    const submitActor = actor;
    const submitActorKey = actorKey;
    if (!submitActor || !submitActorKey || recoveryBlocked) {
      setGrantState("error");
      setGrantMessage(
        "A verified admin identity and recoverable grant state are required before granting minutes.",
      );
      return;
    }
    if (!intent) {
      if (!target || !account) return;
      const prior = readPendingGrant(target, submitActor);
      if (prior.status === "matching") {
        grantIntent.current = prior.intent;
        setPendingGrant(prior.intent);
        setMinutesText(String(prior.intent.minutes));
        setReason(prior.intent.reason);
        setGrantState("uncertain");
        setGrantMessage(
          "A previous grant result is unresolved. The original request was recovered; retry it with the same key to confirm.",
        );
        return;
      }
      if (prior.status !== "none") {
        setRecoveryBlocked(true);
        setGrantState("error");
        setGrantMessage(
          "A prior grant for this account could not be safely recovered. No new grant was sent.",
        );
        return;
      }
      const minutes = Number(minutesText);
      const trimmedReason = reason.trim();
      if (
        !Number.isSafeInteger(minutes) ||
        minutes <= 0 ||
        minutes > MAX_GRANT_MINUTES
      ) {
        setGrantState("error");
        setGrantMessage(
          `Enter a whole number of minutes from 1 to ${MAX_GRANT_MINUTES}.`,
        );
        return;
      }
      if (trimmedReason.length < 1 || trimmedReason.length > 500) {
        setGrantState("error");
        setGrantMessage("Enter a reason between 1 and 500 characters.");
        return;
      }
      let key: string;
      try {
        key = newIdempotencyKey();
      } catch {
        setGrantState("error");
        setGrantMessage(
          "A secure request key could not be created in this browser. Update the browser before granting minutes.",
        );
        return;
      }
      intent = {
        key,
        actorTenantId: submitActor.tenantId,
        actorPersonId: submitActor.personId,
        tenantId: target.tenant_id,
        personId: target.person_id,
        minutes,
        reason: trimmedReason,
        restored: false,
      };
      try {
        persistPendingGrant(intent);
      } catch {
        setGrantState("error");
        setGrantMessage(
          "This browser could not safely retain the grant request. No grant was sent.",
        );
        return;
      }
      grantIntent.current = intent;
      setPendingGrant(intent);
    }
    if (
      !target ||
      !account ||
      intent.actorTenantId !== submitActor.tenantId ||
      intent.actorPersonId !== submitActor.personId ||
      intent.tenantId !== target.tenant_id ||
      intent.personId !== target.person_id
    ) {
      return;
    }

    grantBusy.current = true;
    setGrantState("submitting");
    setGrantMessage("Submitting this audited minute grant…");
    try {
      const value = grantResponseSchema.parse(
        await requestJson(
          `/v1/admin/conversation-minute-accounts/${encodeURIComponent(intent.tenantId)}/${encodeURIComponent(intent.personId)}/grants`,
          {
            method: "POST",
            headers: {
              "content-type": "application/json",
              "Idempotency-Key": intent.key,
            },
            body: JSON.stringify({
              minutes: intent.minutes,
              reason: intent.reason,
            }),
          },
        ),
      );
      if (
        value.minutes !== intent.minutes ||
        value.account.tenant_id !== intent.tenantId ||
        value.account.person_id !== intent.personId
      ) {
        throw new InvalidResponseError();
      }
      if (currentActorKey.current !== submitActorKey) return;
      const markerCleared = clearPendingGrant(intent);
      if (!mounted.current) return;
      setAccount(value.account);
      if (markerCleared) {
        grantIntent.current = null;
        setPendingGrant(null);
        setMinutesText("");
        setReason("");
      } else {
        setRecoveryBlocked(true);
        setGrantState("uncertain");
        setGrantMessage(
          "The grant is confirmed, but this browser could not clear its recovery record. Keep the same request and retry later to reconcile it.",
        );
        return;
      }
      setGrantState("success");
      setGrantMessage(
        value.replayed
          ? "The original grant was confirmed; no duplicate grant was added."
          : "Minute grant confirmed in the canonical account ledger.",
      );
    } catch (error) {
      if (!mounted.current || currentActorKey.current !== submitActorKey)
        return;
      const outcome = grantError(error);
      if (outcome.definitive && !intent.restored) {
        const markerCleared = clearPendingGrant(intent);
        if (!markerCleared) {
          setRecoveryBlocked(true);
          setGrantState("uncertain");
          setGrantMessage(
            "The request was rejected, but this browser could not clear its recovery record. No new grant can be started until it is reconciled.",
          );
          return;
        }
        grantIntent.current = null;
        setPendingGrant(null);
        setGrantState("error");
      } else {
        grantIntent.current = { ...intent, restored: true };
        setPendingGrant({ ...intent, restored: true });
        setGrantState("uncertain");
      }
      setGrantMessage(outcome.text);
    } finally {
      grantBusy.current = false;
    }
  }

  useEffect(() => {
    if (!pendingGrant) return;
    const warnBeforeClose = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeClose);
    return () => window.removeEventListener("beforeunload", warnBeforeClose);
  }, [pendingGrant]);

  const unresolved = Boolean(pendingGrant && grantState === "uncertain");
  const locked = Boolean(pendingGrant);

  return (
    <section className={styles.panel} aria-labelledby="minute-account-title">
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Learner account access</span>
          <h2 id="minute-account-title">Minute allowance and grants</h2>
          <p>
            Find one learner by exact email or public username, review the
            canonical balance, then add a finite audited minute grant.
          </p>
        </div>
      </header>

      <form
        className={styles.lookup}
        onSubmit={(event) => {
          event.preventDefault();
          void lookup();
        }}
      >
        <label className={styles.field} htmlFor="minute-account-query">
          <span>Exact learner email or public username</span>
          <input
            id="minute-account-query"
            autoComplete="off"
            maxLength={320}
            value={query}
            disabled={locked || !actor}
            onChange={(event) => {
              setQuery(event.currentTarget.value);
              invalidateLookup();
            }}
          />
        </label>
        <button
          className="button button-secondary"
          type="submit"
          disabled={lookupState === "loading" || locked || !actor}
        >
          {lookupState === "loading" ? "Checking…" : "Find learner"}
        </button>
        <p className={styles.helper}>
          Partial names, phone numbers, and account IDs are not searched. A
          match must be an active verified learner in the configured learner
          tenant.
        </p>
      </form>

      {lookupMessage ? (
        <div
          className={
            lookupState === "error"
              ? styles.error
              : lookupState === "ready"
                ? styles.success
                : styles.notice
          }
          role={lookupState === "error" ? "alert" : "status"}
        >
          <p>{lookupMessage}</p>
          {lookupState === "error" && !locked ? (
            <button
              className="button button-secondary"
              type="button"
              onClick={() => void lookup()}
            >
              Try lookup again
            </button>
          ) : null}
        </div>
      ) : null}

      {target && account ? (
        <div className={styles.account}>
          <section
            className={styles.subsection}
            aria-labelledby="minute-account-current-title"
          >
            <div className={styles.subheading}>
              <div>
                <span className={styles.eyebrow}>Verified learner</span>
                <h3 id="minute-account-current-title">{target.display_name}</h3>
                <p>
                  {target.username
                    ? `@${target.username}`
                    : "Public username unavailable"}
                  {target.masked_email ? ` · ${target.masked_email}` : ""}
                </p>
              </div>
              <span className={styles.revision}>
                Balance revision {account.revision}
              </span>
            </div>
            <div className={styles.balanceGrid}>
              <article className={styles.balanceCard}>
                <span>Available account minutes</span>
                <strong>{account.available_minutes}</strong>
                <small>
                  {formatSeconds(account.available_seconds)} exact balance
                </small>
              </article>
              <article className={styles.balanceCard}>
                <span>Granted / committed</span>
                <strong>{formatSeconds(account.granted_seconds)}</strong>
                <small>
                  {formatSeconds(account.committed_seconds)} committed
                </small>
              </article>
              <article className={styles.balanceCard}>
                <span>Effective unlimited access</span>
                <strong>{account.effective_unlimited ? "Yes" : "No"}</strong>
                <small>
                  Stored flag: {account.stored_unlimited ? "on" : "off"};
                  informational only
                </small>
              </article>
            </div>
            <div className={styles.uploadBalance}>
              <strong>Shared upload allowance</strong>
              <span>
                {formatSeconds(account.shared_upload_available_seconds)}{" "}
                available
              </span>
              <small>
                {formatSeconds(account.shared_upload_committed_seconds)}{" "}
                committed of{" "}
                {formatSeconds(account.shared_upload_allowance_seconds)} total
              </small>
            </div>
          </section>

          <section
            className={styles.subsection}
            aria-labelledby="minute-grant-title"
          >
            <div className={styles.subheading}>
              <div>
                <span className={styles.eyebrow}>Audited access change</span>
                <h3 id="minute-grant-title">Grant learner minutes</h3>
                <p>
                  This adds finite account minutes only. It does not change
                  provider-spend limits or start analysis.
                </p>
                <p>
                  If a result is unclear, this tab retains the exact amount and
                  audit reason with its original request key until the grant is
                  confirmed.
                </p>
              </div>
            </div>
            <div className={styles.grantFields}>
              <label className={styles.field} htmlFor="minute-grant-amount">
                <span>Whole minutes</span>
                <input
                  id="minute-grant-amount"
                  type="number"
                  inputMode="numeric"
                  min="1"
                  max={MAX_GRANT_MINUTES}
                  step="1"
                  value={minutesText}
                  disabled={
                    locked ||
                    grantState === "submitting" ||
                    !actor ||
                    recoveryBlocked
                  }
                  onChange={(event) => {
                    setMinutesText(event.currentTarget.value);
                    setGrantState("idle");
                    setGrantMessage("");
                  }}
                />
              </label>
              <label className={styles.field} htmlFor="minute-grant-reason">
                <span>Audit reason</span>
                <textarea
                  id="minute-grant-reason"
                  maxLength={500}
                  rows={3}
                  value={reason}
                  disabled={
                    locked ||
                    grantState === "submitting" ||
                    !actor ||
                    recoveryBlocked
                  }
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                    setGrantState("idle");
                    setGrantMessage("");
                  }}
                />
              </label>
            </div>
            <div className={styles.actions}>
              <button
                className="button button-primary"
                type="button"
                onClick={() => void submitGrant()}
                disabled={
                  grantState === "submitting" ||
                  !account ||
                  !actor ||
                  recoveryBlocked
                }
              >
                {grantState === "submitting"
                  ? "Saving grant…"
                  : unresolved
                    ? "Retry same grant"
                    : "Grant minutes"}
              </button>
              {unresolved ? (
                <span className={styles.warning}>
                  The exact amount and reason are locked so the same idempotency
                  key can be retried safely.
                </span>
              ) : null}
            </div>
            {grantMessage ? (
              <div
                className={
                  grantState === "success"
                    ? styles.success
                    : grantState === "error"
                      ? styles.error
                      : grantState === "uncertain"
                        ? styles.warningBox
                        : styles.notice
                }
                role={grantState === "error" ? "alert" : "status"}
              >
                <p>{grantMessage}</p>
              </div>
            ) : null}
          </section>

          <section
            className={styles.subsection}
            aria-labelledby="minute-grant-history-title"
          >
            <div className={styles.subheading}>
              <div>
                <span className={styles.eyebrow}>Canonical audit history</span>
                <h3 id="minute-grant-history-title">Minute grants</h3>
              </div>
            </div>
            {account.grants.length ? (
              <ol className={styles.history}>
                {[...account.grants].reverse().map((grant) => (
                  <li key={grant.grant_id}>
                    <div>
                      <strong>{formatSeconds(grant.seconds)}</strong>
                      <span>{grant.created_at ?? "Timestamp unavailable"}</span>
                    </div>
                    <p>{grant.reason || "No reason supplied"}</p>
                    {grant.audit_sequence != null ? (
                      <small>Audit sequence {grant.audit_sequence}</small>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <p className={styles.empty}>
                No minute grants are recorded for this account.
              </p>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
