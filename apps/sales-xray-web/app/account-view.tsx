"use client";

import {
  CircleUserRound,
  Clock3,
  LogOut,
  Pencil,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  acquisition,
  parseAllowance,
  record,
  type Allowance,
} from "./acquisition-client";
import { AcquisitionShell } from "./acquisition-shell";
import { useSalesXraySignOut } from "./account-navigation";
import {
  AccountProfileRequestError,
  normalizeProfilePhoneInput,
  readAccountProfile,
  updateAccountProfile,
  validE164Phone,
  type AccountProfileRecord,
} from "./account-profile-client";
import { PROFILE_UPDATED_EVENT } from "./profile-menu";
import { useWorkspaceAccess } from "./workspace-access";
import styles from "./account-view.module.css";

type Loaded<T> =
  | { state: "loading" }
  | { state: "ready"; value: T }
  | { state: "error" };
type LoadedProfile =
  | Loaded<AccountProfileRecord>
  | {
      state: "needs_refresh";
      reason: "conflict" | "uncertain";
    };

type Country = "IN" | "US" | "CA" | "GB" | "AU" | "AE" | "OTHER";
const COUNTRIES: ReadonlyArray<{ value: Country; label: string }> = [
  { value: "IN", label: "India (+91)" },
  { value: "US", label: "United States (+1)" },
  { value: "CA", label: "Canada (+1)" },
  { value: "GB", label: "United Kingdom (+44)" },
  { value: "AU", label: "Australia (+61)" },
  { value: "AE", label: "United Arab Emirates (+971)" },
  { value: "OTHER", label: "Another country or region" },
];

function minutes(seconds: number) {
  // Round down so an allowance is never overstated.
  return Math.floor(seconds / 60);
}

function initials(name: string | null) {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/** The signed-in Sales Xray account: verified identity, details, allowance. */
export function AccountView() {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const identityKey = access?.context
    ? JSON.stringify([
        access.context.personId,
        access.context.sessionId,
        access.context.tenantId,
      ])
    : String(access?.authenticated ?? "unknown");
  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page} data-account-view>
        <header className={styles.header}>
          <h1>Account</h1>
          <p>Your Authority Closers identity for Sales Xray.</p>
        </header>
        {access?.authenticated === false ? (
          <section className={styles.panel} aria-labelledby="account-signin">
            <h2 id="account-signin">Sign in to see your account</h2>
            <p>Your profile and analysis allowance appear after you sign in.</p>
            <Link
              className={styles.primary}
              href="/login"
              onClick={(event) => {
                if (access.requestAccountSignIn) {
                  event.preventDefault();
                  access.requestAccountSignIn();
                }
              }}
            >
              Sign in
            </Link>
          </section>
        ) : authenticated ? (
          <AccountDetails key={identityKey} />
        ) : (
          <p className={styles.muted} role="status" aria-busy="true">
            Checking your account…
          </p>
        )}
      </div>
    </AcquisitionShell>
  );
}

function AccountDetails() {
  const [profile, setProfile] = useState<LoadedProfile>({
    state: "loading",
  });
  const [allowance, setAllowance] = useState<Loaded<Allowance>>({
    state: "loading",
  });
  const [editing, setEditing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { signOut, signingOut, error: signOutError } = useSalesXraySignOut();

  // Independent reads: a failed allowance never hides the profile, or vice versa.
  useEffect(() => {
    const controller = new AbortController();
    void readAccountProfile(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setProfile({ state: "ready", value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setProfile({ state: "error" });
      });
    void acquisition("/session", { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return;
        setAllowance({
          state: "ready",
          value: parseAllowance(record(value).allowance),
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setAllowance({ state: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  const retry = () => {
    setProfile({ state: "loading" });
    setAllowance({ state: "loading" });
    setAttempt((value) => value + 1);
  };

  return (
    <div className={styles.grid}>
      <section className={styles.panel} aria-labelledby="account-profile">
        <div className={styles.panelHead}>
          <h2 id="account-profile">Profile</h2>
          {profile.state === "ready" && !editing ? (
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setEditing(true)}
            >
              <Pencil size={15} aria-hidden="true" /> Edit details
            </button>
          ) : null}
        </div>
        {profile.state === "loading" ? (
          <p className={styles.muted} role="status" aria-busy="true">
            Loading your profile…
          </p>
        ) : profile.state === "error" || profile.state === "needs_refresh" ? (
          <div className={styles.error} role="alert">
            <p>
              {profile.state === "error"
                ? "Your profile could not be loaded. Refresh before editing or confirming changes."
                : profile.reason === "conflict"
                  ? "Your profile changed elsewhere. Refresh it before editing again."
                  : "A profile update may have been saved, but its status could not be confirmed. Refresh before editing again."}
            </p>
            <button type="button" className={styles.secondary} onClick={retry}>
              <RefreshCw size={15} aria-hidden="true" /> Refresh profile
            </button>
          </div>
        ) : editing ? (
          <ProfileForm
            profile={profile.value}
            onCancel={() => setEditing(false)}
            onNeedsRefresh={(reason) => {
              setProfile({ state: "needs_refresh", reason });
              setEditing(false);
            }}
            onSaved={(value) => {
              setProfile({ state: "ready", value });
              setEditing(false);
            }}
          />
        ) : (
          <ProfileSummary profile={profile.value} />
        )}
      </section>

      <section className={styles.panel} aria-labelledby="account-allowance">
        <div className={styles.panelHead}>
          <h2 id="account-allowance">Analysis time</h2>
          <Clock3 size={18} aria-hidden="true" className={styles.headIcon} />
        </div>
        <AllowanceSummary allowance={allowance} onRetry={retry} />
      </section>

      <section className={styles.panel} aria-labelledby="account-session">
        <div className={styles.panelHead}>
          <h2 id="account-session">Session</h2>
          <ShieldCheck
            size={18}
            aria-hidden="true"
            className={styles.headIcon}
          />
        </div>
        <p className={styles.muted}>
          Calls and reports stay private to your account and selected workspace.
        </p>
        <div className={styles.actions}>
          <Link className={styles.secondary} href="/calls">
            Open Calls
          </Link>
          <button
            type="button"
            className={styles.danger}
            disabled={signingOut}
            onClick={() => void signOut()}
          >
            <LogOut size={15} aria-hidden="true" />
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
        {signOutError ? (
          <p className={styles.errorText} role="alert">
            {signOutError}
          </p>
        ) : null}
      </section>
    </div>
  );
}

function ProfileSummary({ profile }: { profile: AccountProfileRecord }) {
  const mark = initials(profile.name);
  return (
    <div className={styles.identity}>
      {/* No profile-photo contract exists; this mark is decorative only. */}
      <span className={styles.mark} aria-hidden="true">
        {mark || <CircleUserRound size={26} />}
      </span>
      <dl className={styles.facts}>
        <div>
          <dt>Name</dt>
          <dd>{profile.name ?? "Not provided yet"}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd>{profile.email}</dd>
        </div>
        <div>
          <dt>Phone</dt>
          <dd>
            {profile.phone_number_e164 ?? "Not provided yet"}
            {profile.phone_number_e164 ? (
              <span
                className={styles.badge}
                data-tone={profile.phone_verified ? "ok" : "pending"}
              >
                {profile.phone_verified ? "Verified" : "Not verified"}
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Profile</dt>
          <dd>
            {profile.profile_complete
              ? "Complete"
              : "Incomplete: add your name and phone number"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function ProfileForm({
  profile,
  onCancel,
  onNeedsRefresh,
  onSaved,
}: {
  profile: AccountProfileRecord;
  onCancel: () => void;
  onNeedsRefresh: (reason: "conflict" | "uncertain") => void;
  onSaved: (profile: AccountProfileRecord) => void;
}) {
  const [name, setName] = useState(profile.name ?? "");
  const [country, setCountry] = useState<Country>(
    !profile.phone_number_e164 || profile.phone_number_e164.startsWith("+91")
      ? "IN"
      : "OTHER",
  );
  const [phone, setPhone] = useState(profile.phone_number_e164 ?? "");
  const [saving, setSaving] = useState(false);
  const [issue, setIssue] = useState("");
  const [refreshReason, setRefreshReason] = useState<
    "conflict" | "uncertain" | null
  >(null);
  const [checkingLatest, setCheckingLatest] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const checkLatest = useCallback(async () => {
    if (checkingLatest || saving) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setCheckingLatest(true);
    setIssue("");
    try {
      const latest = await readAccountProfile(current.signal);
      if (current.signal.aborted) return;
      setCheckingLatest(false);
      window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
      onSaved(latest);
    } catch {
      if (current.signal.aborted) return;
      setCheckingLatest(false);
      setIssue(
        refreshReason === "conflict"
          ? "The latest profile could not be loaded. Your draft is still here; load the latest profile before saving again."
          : "The save status is still unconfirmed. Your draft is still here; check the latest profile before saving again.",
      );
    }
  }, [checkingLatest, onSaved, refreshReason, saving]);

  const submit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (saving || refreshReason !== null) return;
      const fullName = name.trim();
      const normalized = normalizeProfilePhoneInput(phone, country);
      if (!fullName) return setIssue("Enter your full name.");
      if (!validE164Phone(normalized))
        return setIssue(
          "Enter the full phone number: + and country code, then 7–15 digits.",
        );
      controller.current?.abort();
      const current = new AbortController();
      controller.current = current;
      setSaving(true);
      setIssue("");
      let updateAccepted = false;
      try {
        await updateAccountProfile(
          {
            full_name: fullName,
            phone_number_e164: normalized,
            expected_revision: profile.revision,
          },
          current.signal,
        );
        updateAccepted = true;
        setRefreshReason("uncertain");
        // Do not call the form saved until the server reread confirms state.
        const saved = await readAccountProfile(current.signal);
        if (current.signal.aborted) return;
        window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
        onSaved(saved);
      } catch (error) {
        if (current.signal.aborted) return;
        const status =
          error instanceof AccountProfileRequestError ? error.status : 0;
        if (status === 409) {
          setRefreshReason("conflict");
          setIssue(
            "Your details changed elsewhere. Load the latest profile before saving again.",
          );
        } else if (status === 422) {
          setIssue("Check your name and phone number, then save again.");
        } else if (status === 401) {
          setIssue("Your session ended. Sign in again to save.");
        } else {
          // A transport/server failure can happen after the write committed.
          // Keep the draft, but require a fresh profile read before another PUT.
          setRefreshReason("uncertain");
          setIssue(
            updateAccepted
              ? "Your update was accepted, but the current profile could not be confirmed. Check the latest profile before saving again."
              : "Your update may have been saved, but its status could not be confirmed. Check the latest profile before saving again.",
          );
        }
        setSaving(false);
      }
    },
    [country, name, onSaved, phone, profile.revision, refreshReason, saving],
  );

  return (
    <form className={styles.form} onSubmit={(event) => void submit(event)}>
      <label>
        <span>Full name</span>
        <input
          value={name}
          autoComplete="name"
          maxLength={120}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        <span>Country or region</span>
        <select
          value={country}
          onChange={(event) => setCountry(event.target.value as Country)}
        >
          {COUNTRIES.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Phone number</span>
        <input
          value={phone}
          inputMode="tel"
          autoComplete="tel"
          onChange={(event) => setPhone(event.target.value)}
        />
        <small>
          {country === "IN"
            ? "10-digit Indian numbers get +91 automatically."
            : "Include + and the country code."}
        </small>
      </label>
      <p className={styles.muted}>
        Email is your sign-in identity and can’t be changed here.
      </p>
      {issue ? (
        <p className={styles.errorText} role="alert">
          {issue}
        </p>
      ) : null}
      <div className={styles.actions}>
        {refreshReason ? (
          <button
            type="button"
            className={styles.secondary}
            disabled={saving || checkingLatest}
            onClick={() => void checkLatest()}
          >
            {checkingLatest ? "Checking profile…" : "Load latest profile"}
          </button>
        ) : null}
        <button
          type="submit"
          className={styles.primary}
          disabled={saving || checkingLatest || refreshReason !== null}
        >
          {saving ? "Saving…" : "Save details"}
        </button>
        <button
          type="button"
          className={styles.secondary}
          disabled={saving || checkingLatest}
          onClick={() =>
            refreshReason ? onNeedsRefresh(refreshReason) : onCancel()
          }
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function AllowanceSummary({
  allowance,
  onRetry,
}: {
  allowance: Loaded<Allowance>;
  onRetry: () => void;
}) {
  if (allowance.state === "loading")
    return (
      <p className={styles.muted} role="status" aria-busy="true">
        Loading your analysis time…
      </p>
    );
  if (allowance.state === "error")
    return (
      <div className={styles.error} role="alert">
        <p>Your analysis time is unavailable right now.</p>
        <button type="button" className={styles.secondary} onClick={onRetry}>
          <RefreshCw size={15} aria-hidden="true" /> Try again
        </button>
      </div>
    );
  const { allowance_seconds, available_seconds, committed_seconds } =
    allowance.value;
  if (allowance.value.unlimited)
    return (
      <div className={styles.allowance} data-allowance="unlimited">
        <p className={styles.big}>Unlimited</p>
        <p className={styles.muted}>
          No minute limit applies to this account. {minutes(committed_seconds)}{" "}
          min used or reserved by analyses.
        </p>
      </div>
    );
  if (allowance_seconds <= 0)
    return (
      <div className={styles.allowance} data-allowance="none">
        <p className={styles.big}>No analysis time yet</p>
        <p className={styles.muted}>Ask the AC team to allot minutes.</p>
      </div>
    );
  const share = Math.min(1, available_seconds / allowance_seconds);
  return (
    <div className={styles.allowance} data-allowance="finite">
      <p className={styles.big}>
        {minutes(available_seconds)} of {minutes(allowance_seconds)} min
        available
      </p>
      <span
        className={styles.meter}
        role="meter"
        aria-label="Analysis time available"
        aria-valuemin={0}
        aria-valuemax={allowance_seconds}
        aria-valuenow={available_seconds}
      >
        <span style={{ width: `${share * 100}%` }} />
      </span>
      <p className={styles.muted}>
        {minutes(committed_seconds)} min used or reserved by analyses.
      </p>
    </div>
  );
}
