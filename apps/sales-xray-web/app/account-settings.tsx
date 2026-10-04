"use client";

import {
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  Clock3,
  CreditCard,
  LifeBuoy,
  LogOut,
  Mail,
  Pencil,
  RefreshCw,
  Settings2,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  acquisition,
  parseAllowance,
  record,
  type Allowance,
} from "./acquisition-client";
import { useSalesXraySignOut } from "./account-navigation";
import type { BillingViewProps } from "./billing/billing-view";
import { useBillingAccount } from "./billing/use-billing-account";
import { count, day, formatMoney, money } from "./billing/money";
import {
  TOP_UP_PACKS,
  PLANS_GST_RATE,
  type DisplayTopUpPack,
} from "./plans/plans-catalogue-fixture";
import { CheckoutDrawer } from "./plans/checkout-drawer";
import { usePurchaseCheckout } from "./plans/use-purchase-checkout";
import {
  AccountProfileRequestError,
  normalizeProfilePhoneInput,
  readAccountProfile,
  updateAccountProfile,
  validE164Phone,
  type AccountProfileRecord,
} from "./account-profile-client";
import { useTheme } from "./lightbox/theme-provider";
import { parseThemePreference } from "./lightbox/theme";
import { notify, dismissNotice } from "./notice-center";
import { PROFILE_UPDATED_EVENT } from "./profile-menu";
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

type SectionId =
  | "general"
  | "profile"
  | "usage"
  | "billing"
  | "security"
  | "help";
const SECTIONS: ReadonlyArray<{
  id: SectionId;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "general", label: "General", icon: Settings2 },
  { id: "profile", label: "Profile", icon: CircleUserRound },
  { id: "usage", label: "Analysis time", icon: Clock3 },
  { id: "billing", label: "Plan & billing", icon: CreditCard },
  { id: "security", label: "Security", icon: ShieldCheck },
  { id: "help", label: "Help & support", icon: LifeBuoy },
];

function sectionFromHash(hash: string, prefix: string): SectionId | null {
  const raw = hash.replace(/^#/, "");
  if (prefix && !raw.startsWith(prefix)) return null;
  const id = raw.slice(prefix.length).toLowerCase();
  return SECTIONS.some((section) => section.id === id)
    ? (id as SectionId)
    : null;
}

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

/**
 * Settings for the signed-in account: a section list and one pane of rows.
 * The /account page shows it in place; the settings dialog floats it over any
 * screen. On phones the list and the pane are separate steps.
 */
export function AccountSettings({
  hashPrefix = "",
  variant = "page",
  onClose,
  billing,
}: {
  billing?: SettingsBillingProps;
  hashPrefix?: string;
  variant?: "page" | "dialog";
  onClose?: () => void;
}) {
  const [profile, setProfile] = useState<LoadedProfile>({
    state: "loading",
  });
  const [allowance, setAllowance] = useState<Loaded<Allowance>>({
    state: "loading",
  });
  const [editing, setEditing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [section, setSection] = useState<SectionId>("general");
  const liveBilling = useBillingAccount(!billing && section === "billing");
  const [stage, setStage] = useState<"list" | "pane">("list");
  const [selectedTopUp, setSelectedTopUp] = useState<DisplayTopUpPack | null>(
    null,
  );
  const topUp = usePurchaseCheckout(undefined, "/account#billing");
  useEffect(() => {
    if (!topUp.error) return;
    const id = "topup-checkout-error";
    notify({
      id,
      tone: "error",
      title: "Checkout unavailable",
      message: topUp.error,
    });
    return () => dismissNotice(id);
  }, [topUp.error]);
  const tabs = useRef<Partial<Record<SectionId, HTMLButtonElement | null>>>({});
  const { signOut, signingOut, error: signOutError } = useSalesXraySignOut();

  // The URL hash keeps the open section across reloads and shared links.
  useEffect(() => {
    const sync = () => {
      const hashId = sectionFromHash(window.location.hash, hashPrefix);
      const searchParams = new URLSearchParams(window.location.search);
      const queryId = searchParams.get("section") as SectionId | null;
      const validQuery =
        queryId && SECTIONS.some((s) => s.id === queryId) ? queryId : null;
      const id = hashId || validQuery;
      if (!id) return;
      setSection(id);
      setStage("pane");
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [hashPrefix]);

  const open = useCallback(
    (id: SectionId, focus = false) => {
      setSection(id);
      if (!focus) setStage("pane");
      if (typeof window !== "undefined" && window.history?.replaceState) {
        window.history.replaceState(
          window.history.state,
          "",
          `${window.location.pathname}${window.location.search}#${hashPrefix}${id}`,
        );
      }
      if (focus) tabs.current[id]?.focus();
    },
    [hashPrefix],
  );
  const back = () => setStage("list");

  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = SECTIONS.findIndex((item) => item.id === section);
    const last = SECTIONS.length - 1;
    const next =
      event.key === "ArrowDown" || event.key === "ArrowRight"
        ? index === last
          ? 0
          : index + 1
        : event.key === "ArrowUp" || event.key === "ArrowLeft"
          ? index === 0
            ? last
            : index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (next === null) return;
    event.preventDefault();
    open(SECTIONS[next].id, true);
  };

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

  const who = profile.state === "ready" ? profile.value : null;

  return (
    <div className={styles.settings} data-variant={variant} data-stage={stage}>
      <aside className={styles.nav}>
        <header className={styles.navHead}>
          <span className={styles.navMark} aria-hidden="true">
            {who ? initials(who.name) || <CircleUserRound size={18} /> : null}
          </span>
          <div className={styles.navWho}>
            {variant === "dialog" ? <h2>Settings</h2> : <h1>Account</h1>}
            <p>{who?.email ?? "Sales Xray settings"}</p>
          </div>
          {onClose ? (
            <button
              type="button"
              className={styles.close}
              aria-label="Close settings"
              onClick={onClose}
            >
              <X size={18} aria-hidden="true" />
            </button>
          ) : null}
        </header>
        <div
          className={styles.tabs}
          role="tablist"
          aria-label="Account settings"
          aria-orientation="vertical"
          onKeyDown={onTabKey}
        >
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              ref={(node) => {
                tabs.current[id] = node;
              }}
              type="button"
              role="tab"
              id={`account-tab-${id}`}
              aria-selected={section === id}
              aria-controls={`account-pane-${id}`}
              tabIndex={section === id ? 0 : -1}
              className={styles.tab}
              onClick={() => open(id)}
            >
              <Icon size={17} aria-hidden="true" />
              <span>{label}</span>
              <ChevronRight
                size={16}
                aria-hidden="true"
                className={styles.tabChevron}
              />
            </button>
          ))}
        </div>
      </aside>

      <div className={styles.content}>
        <Pane id="general" title="General" active={section} onBack={back}>
          <ThemeRow />
          <Row
            label="Calls library"
            hint="Calls and reports stay private to your account and selected workspace."
          >
            <Link
              className={styles.secondary}
              href="/analysis/calls"
              replace={variant === "dialog"}
            >
              Open Calls
            </Link>
          </Row>
          <Row label="New analysis" hint="Upload a call recording to analyse.">
            <Link
              className={styles.secondary}
              href="/analysis/new"
              replace={variant === "dialog"}
            >
              Start
            </Link>
          </Row>
        </Pane>

        <Pane
          id="profile"
          title="Profile"
          active={section}
          onBack={back}
          action={
            profile.state === "ready" && !editing ? (
              <button
                type="button"
                className={styles.secondary}
                onClick={() => setEditing(true)}
              >
                <Pencil size={14} aria-hidden="true" /> Edit details
              </button>
            ) : null
          }
        >
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
              <button
                type="button"
                className={styles.secondary}
                onClick={retry}
              >
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
        </Pane>

        <Pane id="usage" title="Analysis time" active={section} onBack={back}>
          <AllowanceSummary allowance={allowance} onRetry={retry} />
          <div className={styles.row}>
            <div className={styles.rowText}>
              <span className={styles.rowLabel}>Need more minutes?</span>
              <span className={styles.rowHint}>
                Add analysis minutes anytime without changing your monthly
                subscription.
              </span>
            </div>
            <div className={styles.rowControl}>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => {
                  setSection("billing");
                  if (typeof window !== "undefined")
                    window.location.hash = "billing";
                }}
              >
                Top up minutes
              </button>
            </div>
          </div>
        </Pane>

        <Pane
          id="billing"
          title="Plan & billing"
          active={section}
          onBack={back}
        >
          <PlanAndBillingPane
            {...(billing ?? liveBilling)}
            active={section === "billing"}
            allowance={
              billing || !liveBilling.usage
                ? allowance
                : {
                    state: "ready",
                    value: {
                      allowance_seconds:
                        liveBilling.usage.allowance.allowanceSeconds,
                      committed_seconds:
                        liveBilling.usage.allowance.committedSeconds,
                      available_seconds:
                        liveBilling.usage.allowance.availableSeconds,
                      ...(liveBilling.usage.allowance.unlimited
                        ? { unlimited: true as const }
                        : {}),
                    },
                  }
            }
            onBuyTopUp={(pack) => {
              topUp.select();
              setSelectedTopUp(pack);
            }}
            variant={variant}
            onRetry={retry}
          />
        </Pane>

        <Pane id="security" title="Security" active={section} onBack={back}>
          <Row
            label="Privacy"
            hint="Calls and reports stay private to your account and selected workspace."
          />
          <Row
            label="Log out of this device"
            hint="End your Sales Xray session in this browser."
          >
            <button
              type="button"
              className={styles.danger}
              disabled={signingOut}
              onClick={() => void signOut()}
            >
              <LogOut size={15} aria-hidden="true" />
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </Row>
          {signOutError ? (
            <p className={styles.errorText} role="alert">
              {signOutError}
            </p>
          ) : null}
        </Pane>

        <Pane id="help" title="Help & support" active={section} onBack={back}>
          <Row
            label="Contact support"
            hint="Questions about a call, a report or your account? Write to the Authority Closers team."
          >
            <a
              className={styles.secondary}
              href="mailto:support@authorityclosers.com"
            >
              <Mail size={15} aria-hidden="true" />
              Email support
            </a>
          </Row>
        </Pane>
      </div>
      <CheckoutDrawer
        open={Boolean(selectedTopUp)}
        onClose={() => {
          topUp.select();
          setSelectedTopUp(null);
        }}
        item={selectedTopUp ? { type: "top_up", pack: selectedTopUp } : null}
        gstRate={PLANS_GST_RATE}
        busy={topUp.busy}
        confirmedOrder={topUp.prepared?.order}
        onPay={() => {
          if (selectedTopUp)
            void topUp.buy({
              kind: "top_up",
              account:
                selectedTopUp.planKey === "personal"
                  ? "personal"
                  : "organisation",
              planKey: selectedTopUp.planKey,
              packKey: selectedTopUp.key,
            });
        }}
      />
    </div>
  );
}

function Pane({
  id,
  title,
  active,
  action,
  onBack,
  children,
}: {
  id: SectionId;
  title: string;
  active: SectionId;
  action?: ReactNode;
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <section
      id={`account-pane-${id}`}
      role="tabpanel"
      aria-labelledby={`account-tab-${id}`}
      hidden={active !== id}
      className={styles.pane}
    >
      <div className={styles.paneHead}>
        <button
          type="button"
          className={styles.back}
          aria-label="Back to settings"
          onClick={onBack}
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <h2>{title}</h2>
        <span className={styles.paneAction}>{action}</span>
      </div>
      <div className={styles.rows}>{children}</div>
    </section>
  );
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <div className={styles.rowText}>
        <span className={styles.rowLabel}>{label}</span>
        {hint ? <span className={styles.rowHint}>{hint}</span> : null}
      </div>
      {children ? <div className={styles.rowControl}>{children}</div> : null}
    </div>
  );
}

function ThemeRow() {
  const theme = useTheme();
  // The theme control is only released where the provider is enabled.
  if (!theme) return null;
  return (
    <Row label="Theme" hint="System follows your device setting.">
      <label className={styles.selectWrap}>
        <span className={styles.srOnly}>Theme</span>
        <select
          className={styles.select}
          value={theme.preference}
          onChange={(event) =>
            theme.setPreference(parseThemePreference(event.target.value))
          }
        >
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>
    </Row>
  );
}

function ProfileSummary({ profile }: { profile: AccountProfileRecord }) {
  return (
    <>
      <dl className={styles.facts}>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>Name</dt>
          <dd>{profile.name ?? "Not provided yet"}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>Email</dt>
          <dd>{profile.email}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>Phone</dt>
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
        <div className={styles.row}>
          <dt className={styles.rowLabel}>Profile</dt>
          <dd>
            {profile.profile_complete
              ? "Complete"
              : "Incomplete: add your name and phone number"}
          </dd>
        </div>
      </dl>
    </>
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

export type SettingsBillingProps = BillingViewProps & {
  onBuyTopUp?: (pack: DisplayTopUpPack) => void;
  topUpPacks?: DisplayTopUpPack[];
};

/** Verified billing data and actions arrive as props; AUT-880 supplies the client. */
export function PlanAndBillingPane({
  active = true,
  allowance,
  variant,
  onRetry,
  mePlan = null,
  subs = null,
  documents,
  status = "error",
  invoicesStatus = status,
  busy = false,
  error,
  onCancel,
  onBuyTopUp,
  topUpPacks = TOP_UP_PACKS,
}: SettingsBillingProps & {
  active?: boolean;
  allowance: Loaded<Allowance>;
  variant?: "page" | "dialog";
  onRetry: () => void;
}) {
  const [cancelAsk, setCancelAsk] = useState(false);
  const current = subs?.current;
  const isCancelled = current?.cancelAtPeriodEnd === true;
  const canCancel =
    current && ["active", "past_due", "halted"].includes(current.status);
  const loading = status === "loading";
  useEffect(() => {
    if (!active || !error) return;
    const id = "settings-billing-error";
    notify({ id, tone: "error", title: "Billing unavailable", message: error });
    return () => dismissNotice(id);
  }, [active, error]);

  return (
    <div className={styles.billingBlock}>
      <div className={styles.billingCard}>
        <div className={styles.billingCardHead}>
          <div>
            <h3>Current subscription</h3>
            <p className={styles.muted}>Your plan and billing schedule.</p>
          </div>
          <span
            className={styles.badge}
            data-tone={
              current?.status === "active" && !isCancelled ? "ok" : "pending"
            }
          >
            {loading
              ? "Loading…"
              : status !== "ready"
                ? "Unavailable"
                : isCancelled
                  ? "Cancels at period end"
                  : current?.status === "active"
                    ? "Active"
                    : current?.status === "pending_authorisation"
                      ? "Awaiting payment"
                      : current?.status === "past_due"
                        ? "Payment due"
                        : current?.status === "halted"
                          ? "Paused"
                          : current
                            ? "Ended"
                            : "No subscription"}
          </span>
        </div>

        {loading ? (
          <div
            className={styles.billingSkeleton}
            role="status"
            aria-busy="true"
          >
            <span>Loading billing details…</span>
            <i />
            <i />
            <i />
          </div>
        ) : (
          <dl className={styles.facts}>
            <div className={styles.row}>
              <dt className={styles.rowLabel}>Plan</dt>
              <dd>{mePlan?.plan.name ?? current?.planName ?? "Unavailable"}</dd>
            </div>
            <div className={styles.row}>
              <dt className={styles.rowLabel}>Price</dt>
              <dd>
                {current
                  ? `${formatMoney(current.amount)} / ${current.interval === "month" ? "month" : "year"}${current.amount.gstInclusive ? " · GST included" : ""}`
                  : "Unavailable"}
              </dd>
            </div>
            {current?.seats ? (
              <div className={styles.row}>
                <dt className={styles.rowLabel}>Seats</dt>
                <dd>
                  {current.seats} {current.seats === 1 ? "seat" : "seats"}
                </dd>
              </div>
            ) : null}
            {mePlan ? (
              <div className={styles.row}>
                <dt className={styles.rowLabel}>Call length</dt>
                <dd>
                  Calls up to {count(mePlan.longestCallSeconds / 60)} minutes
                  long
                </dd>
              </div>
            ) : null}
            <div className={styles.row}>
              <dt className={styles.rowLabel}>
                {isCancelled ? "Access through" : "Next renewal"}
              </dt>
              <dd>
                {isCancelled
                  ? day(current?.currentPeriod?.end ?? null) || "Unavailable"
                  : current?.renewsAt
                    ? `${day(current.renewsAt)} · ${formatMoney(current.amount)}`
                    : status === "ready" && !current
                      ? "No renewal scheduled"
                      : "Unavailable"}
              </dd>
            </div>
          </dl>
        )}

        <div className={styles.actions}>
          <Link
            className={styles.primary}
            href="/plans"
            replace={variant === "dialog"}
          >
            Change or upgrade plan
          </Link>
          {!isCancelled &&
            (cancelAsk && current ? (
              <div className={styles.confirmCancelBox}>
                <p className={styles.muted}>
                  Renewal stops; access continues to the end of the period.
                </p>
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.danger}
                    disabled={busy || !onCancel}
                    onClick={() => onCancel?.(current.subscriptionId)}
                  >
                    Yes, stop renewal
                  </button>
                  <button
                    type="button"
                    className={styles.secondary}
                    disabled={busy}
                    onClick={() => setCancelAsk(false)}
                  >
                    Keep renewal
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className={styles.secondary}
                disabled={busy || status !== "ready" || !canCancel || !onCancel}
                onClick={() => setCancelAsk(true)}
              >
                Cancel renewal
              </button>
            ))}
        </div>
        {current?.renewalNeedsCustomerApproval ? (
          <p className={styles.muted}>
            Your bank will ask you to approve each renewal above ₹15,000.
          </p>
        ) : null}
      </div>

      <div className={styles.billingCard}>
        <div className={styles.billingCardHead}>
          <h3>Analysis time</h3>
          <Link
            className={styles.secondary}
            href="/analysis/new"
            replace={variant === "dialog"}
          >
            Analyse a call
          </Link>
        </div>
        <AllowanceSummary allowance={allowance} onRetry={onRetry} />
      </div>

      <div className={styles.billingCard}>
        <div className={styles.billingCardHead}>
          <div>
            <h3>Need more minutes?</h3>
            <p className={styles.muted}>
              Add analysis minutes without changing your subscription.
            </p>
          </div>
        </div>
        <div className={styles.topUpsMiniGrid}>
          {topUpPacks.map((pack) => {
            const total =
              pack.pricePaise +
              (pack.gstInclusive
                ? 0
                : Math.round(pack.pricePaise * PLANS_GST_RATE));
            return (
              <div className={styles.topUpMiniCard} key={pack.key}>
                <div className={styles.topUpMiniHead}>
                  <span>
                    {pack.title} · {pack.minutes} min
                  </span>
                  <span className={styles.topUpMiniPrice}>
                    {money(pack.pricePaise)}
                    {pack.gstInclusive ? "" : " + GST"}
                  </span>
                </div>
                <p className={styles.muted}>
                  {pack.gstInclusive
                    ? "GST included"
                    : `${money(total)} total incl. GST`}{" "}
                  · {pack.audience}
                </p>
                <button
                  type="button"
                  className={styles.secondary}
                  disabled={busy || !onBuyTopUp}
                  onClick={() => onBuyTopUp?.(pack)}
                >
                  Top up {pack.minutes} min
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {documents ? (
        <div className={styles.billingCard}>
          <div className={styles.billingCardHead}>
            <h3>Invoices &amp; Receipts</h3>
          </div>
          {invoicesStatus === "loading" ? (
            <p className={styles.muted} role="status">
              Loading invoices…
            </p>
          ) : invoicesStatus !== "ready" ? (
            <p className={styles.muted}>
              Invoices and receipts are currently unavailable.
            </p>
          ) : documents.length === 0 ? (
            <p className={styles.muted}>No invoices or receipts yet.</p>
          ) : (
            <div className={styles.invoiceTableWrap}>
              <table className={styles.invoiceTable}>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Description</th>
                    <th scope="col">Amount</th>
                    <th scope="col">Status</th>
                    <th scope="col">Documents</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((document) => (
                    <tr key={document.id}>
                      <td>{day(document.createdAt)}</td>
                      <td>{document.description}</td>
                      <td>{formatMoney(document.amount)}</td>
                      <td>{document.status}</td>
                      <td>
                        {document.invoiceHref ? (
                          <a
                            href={document.invoiceHref}
                            className={styles.muted}
                          >
                            Invoice
                          </a>
                        ) : null}
                        {document.invoiceHref && document.receiptHref
                          ? " · "
                          : null}
                        {document.receiptHref ? (
                          <a
                            href={document.receiptHref}
                            className={styles.muted}
                          >
                            Receipt
                          </a>
                        ) : null}
                        {!document.invoiceHref && !document.receiptHref
                          ? "Unavailable"
                          : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      <p className={styles.muted}>
        <b>Satisfaction guarantee:</b> Full refund within 7 days if none of this
        payment&apos;s minutes were used.
      </p>
    </div>
  );
}
