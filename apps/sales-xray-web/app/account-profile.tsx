"use client";

import {
  ArrowRight,
  Check,
  FileAudio2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  AccountProfileRequestError,
  readAccountProfile,
  readAccountProfileEligibility,
  updateAccountProfile,
  validE164Phone,
  type AccountProfileRecord,
} from "./account-profile-client";
import styles from "./account-profile.module.css";

export type SelectedFileMetadata = Readonly<{
  name: string;
  size: number;
  type?: string;
}>;

export type AccountProfileProps = Readonly<{
  selectedFile: SelectedFileMetadata | null;
  onEligible: () => void;
  onSignIn?: () => void;
  previewState?: "profile.required" | "profile.unverified" | "profile.ready";
}>;

type Phase =
  | "loading"
  | "form"
  | "saving"
  | "checking"
  | "blocked"
  | "ready"
  | "signed_out"
  | "error";
type CountryChoice = "" | "IN" | "US" | "CA" | "GB" | "AU" | "AE" | "OTHER";

const COUNTRY_CHOICES: ReadonlyArray<{
  value: Exclude<CountryChoice, "">;
  label: string;
  callingCode: string | null;
}> = [
  { value: "IN", label: "India (+91)", callingCode: "+91" },
  { value: "US", label: "United States (+1)", callingCode: "+1" },
  { value: "CA", label: "Canada (+1)", callingCode: "+1" },
  { value: "GB", label: "United Kingdom (+44)", callingCode: "+44" },
  { value: "AU", label: "Australia (+61)", callingCode: "+61" },
  { value: "AE", label: "United Arab Emirates (+971)", callingCode: "+971" },
  { value: "OTHER", label: "Another country or region", callingCode: null },
];

const PREVIEW_PROFILE: AccountProfileRecord = {
  name: "Preview account",
  email: "preview@example.invalid",
  phone_number_e164: "+12025550123",
  phone_verified: false,
  profile_complete: true,
  revision: 0,
};

function previewProfile(
  state: NonNullable<AccountProfileProps["previewState"]>,
): AccountProfileRecord {
  if (state === "profile.required")
    return {
      ...PREVIEW_PROFILE,
      name: null,
      phone_number_e164: null,
      profile_complete: false,
    };
  if (state === "profile.ready")
    return { ...PREVIEW_PROFILE, phone_verified: true };
  return PREVIEW_PROFILE;
}

function previewPhase(
  state: NonNullable<AccountProfileProps["previewState"]>,
): Phase {
  if (state === "profile.required") return "form";
  if (state === "profile.ready") return "ready";
  return "blocked";
}

function phoneError(phone: string, country: CountryChoice): string {
  if (!country) return "Choose your country or region.";
  if (!validE164Phone(phone))
    return "Enter the full international number: + followed by 7–15 digits, without spaces.";
  const callingCode = COUNTRY_CHOICES.find(
    (choice) => choice.value === country,
  )?.callingCode;
  if (callingCode && !phone.startsWith(callingCode))
    return `The selected country or region uses ${callingCode}. Check the number or change your selection.`;
  return "";
}

export function AccountProfile({
  selectedFile,
  onEligible,
  onSignIn,
  previewState,
}: AccountProfileProps) {
  // The parent may pass a local fixture, but a production build always ignores it.
  const activePreviewState =
    process.env.NODE_ENV === "production" ? undefined : previewState;
  const [phase, setPhase] = useState<Phase>(() =>
    activePreviewState ? previewPhase(activePreviewState) : "loading",
  );
  const [profile, setProfile] = useState<AccountProfileRecord | null>(() =>
    activePreviewState ? previewProfile(activePreviewState) : null,
  );
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState<CountryChoice>("");
  const [notice, setNotice] = useState("");
  const [nameIssue, setNameIssue] = useState("");
  const [phoneIssue, setPhoneIssue] = useState("");
  const mounted = useRef(false);
  const requestId = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const saveInFlight = useRef(false);
  const eligibleNotified = useRef(false);
  const onEligibleRef = useRef(onEligible);
  const nameInput = useRef<HTMLInputElement>(null);
  const countrySelect = useRef<HTMLSelectElement>(null);
  const phoneInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    onEligibleRef.current = onEligible;
  }, [onEligible]);

  const notifyEligible = useCallback(() => {
    if (eligibleNotified.current) return;
    eligibleNotified.current = true;
    onEligibleRef.current();
  }, []);

  const load = useCallback(
    async (preserveDraft = false) => {
      if (activePreviewState) return;
      controller.current?.abort();
      const currentController = new AbortController();
      controller.current = currentController;
      const currentId = ++requestId.current;
      const active = () =>
        mounted.current &&
        requestId.current === currentId &&
        !currentController.signal.aborted;
      setPhase("loading");
      if (!preserveDraft) setNotice("");
      try {
        const currentProfile = await readAccountProfile(
          currentController.signal,
        );
        if (!active()) return;
        setProfile(currentProfile);
        if (!preserveDraft) {
          setName(currentProfile.name ?? "");
          setPhone(currentProfile.phone_number_e164 ?? "");
          // A stored phone prefix is not proof of the user's country choice.
          setCountry("");
          setNameIssue("");
          setPhoneIssue("");
        }
        const eligibility = await readAccountProfileEligibility(
          currentController.signal,
        );
        if (!active()) return;
        if (eligibility === "eligible") {
          notifyEligible();
        } else if (eligibility === "unauthenticated") {
          setPhase("signed_out");
        } else if (preserveDraft || !currentProfile.profile_complete) {
          if (preserveDraft)
            setNotice(
              "Your profile changed in another session. Review your details and save again.",
            );
          setPhase("form");
        } else {
          setPhase("blocked");
        }
      } catch (error) {
        if (!active()) return;
        if (error instanceof AccountProfileRequestError && error.status === 401)
          setPhase("signed_out");
        else {
          setNotice(
            "We couldn’t load or check your AC profile. Your selected file has not been uploaded.",
          );
          setPhase("error");
        }
      }
    },
    [activePreviewState, notifyEligible],
  );

  useEffect(() => {
    let cancelled = false;
    mounted.current = true;
    queueMicrotask(() => {
      if (cancelled) return;
      if (activePreviewState) {
        controller.current?.abort();
        requestId.current += 1;
        const fixture = previewProfile(activePreviewState);
        setProfile(fixture);
        setName(fixture.name ?? "");
        setPhone(fixture.phone_number_e164 ?? "");
        setCountry("");
        setNotice("");
        setNameIssue("");
        setPhoneIssue("");
        setPhase(previewPhase(activePreviewState));
      } else void load();
    });
    return () => {
      cancelled = true;
      mounted.current = false;
      controller.current?.abort();
      requestId.current += 1;
    };
  }, [activePreviewState, load]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saveInFlight.current || !profile) return;
    const normalizedName = name.trim().normalize("NFC");
    const normalizedPhone = phone.trim();
    const nextNameIssue = normalizedName ? "" : "Enter your name.";
    const nextPhoneIssue = phoneError(normalizedPhone, country);
    setNameIssue(nextNameIssue);
    setPhoneIssue(nextPhoneIssue);
    if (nextNameIssue || nextPhoneIssue) {
      if (nextNameIssue) nameInput.current?.focus();
      else if (!country) countrySelect.current?.focus();
      else phoneInput.current?.focus();
      return;
    }

    if (activePreviewState) {
      setNotice("This local preview does not save an account or check access.");
      return;
    }

    saveInFlight.current = true;
    controller.current?.abort();
    const currentController = new AbortController();
    controller.current = currentController;
    const currentId = ++requestId.current;
    const active = () =>
      mounted.current &&
      requestId.current === currentId &&
      !currentController.signal.aborted;
    setPhase("saving");
    setNotice("");
    let saved = false;
    try {
      await updateAccountProfile(
        {
          full_name: normalizedName,
          phone_number_e164: normalizedPhone,
          expected_revision: profile.revision,
        },
        currentController.signal,
      );
      if (!active()) return;
      saved = true;
      setPhase("checking");
      const currentProfile = await readAccountProfile(currentController.signal);
      if (!active()) return;
      setProfile(currentProfile);
      const eligibility = await readAccountProfileEligibility(
        currentController.signal,
      );
      if (!active()) return;
      if (eligibility === "eligible") notifyEligible();
      else if (eligibility === "unauthenticated") setPhase("signed_out");
      else {
        setNotice(
          "Your details were saved, but AC has not confirmed call review access yet. No audio was uploaded.",
        );
        setPhase("blocked");
      }
    } catch (error) {
      if (!active()) return;
      if (error instanceof AccountProfileRequestError && error.status === 401)
        setPhase("signed_out");
      else if (
        error instanceof AccountProfileRequestError &&
        error.status === 409
      )
        void load(true);
      else if (saved) {
        setNotice(
          "Your details were saved, but we couldn’t check access. Try again before continuing.",
        );
        setPhase("blocked");
      } else {
        setNotice(
          error instanceof AccountProfileRequestError && error.status === 422
            ? "Check your name and international mobile number, then try again."
            : "We couldn’t confirm whether your details were saved. Review them and try again.",
        );
        setPhase("form");
      }
    } finally {
      saveInFlight.current = false;
    }
  }

  const busy = phase === "saving" || phase === "checking";
  const retry = () => {
    if (activePreviewState) {
      setNotice(
        "This local preview is paused. Choose another state in Settings to continue reviewing.",
      );
      return;
    }
    void load();
  };

  return (
    <section className={styles.panel} aria-labelledby="account-profile-heading">
      <header className={styles.header}>
        <span className={styles.eyebrow}>YOUR AC ACCOUNT</span>
        <h2 id="account-profile-heading">
          A few details before we review your call.
        </h2>
        <p>
          Your name, account email and mobile number stay with your AC profile.
          We’ll continue only when your account is confirmed ready.
        </p>
      </header>

      {selectedFile ? (
        <div className={styles.file} aria-label="Selected audio file">
          <span className={styles.fileIcon}>
            <FileAudio2 size={20} aria-hidden="true" />
          </span>
          <span className={styles.fileText}>
            <strong>{selectedFile.name}</strong>
            <small>Selected for review · still in this browser</small>
          </span>
          <Check size={17} className={styles.fileCheck} aria-hidden="true" />
        </div>
      ) : null}

      {phase === "loading" || busy ? (
        <p className={styles.status} role="status">
          <span className={styles.spinner} aria-hidden="true" />
          {phase === "loading"
            ? "Checking your AC profile…"
            : phase === "saving"
              ? "Saving your details…"
              : "Confirming access…"}
        </p>
      ) : null}

      {phase === "form" && profile ? (
        <form
          className={styles.form}
          onSubmit={(event) => void submit(event)}
          noValidate
        >
          <div className={styles.fields}>
            <label className={styles.field}>
              <span>Full name</span>
              <input
                ref={nameInput}
                name="full_name"
                autoComplete="name"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameIssue("");
                }}
                aria-invalid={Boolean(nameIssue)}
                aria-describedby={
                  nameIssue ? "account-profile-name-error" : undefined
                }
              />
              {nameIssue ? (
                <small
                  className={styles.fieldError}
                  id="account-profile-name-error"
                >
                  {nameIssue}
                </small>
              ) : null}
            </label>
            <div className={styles.field}>
              <span>Account email</span>
              <div className={styles.readonly}>{profile.email}</div>
              <small>Confirmed when you signed in to AC.</small>
            </div>
            <label className={styles.field}>
              <span>Country or region</span>
              <select
                ref={countrySelect}
                name="phone_country"
                value={country}
                onChange={(event) => {
                  setCountry(event.target.value as CountryChoice);
                  setPhoneIssue("");
                }}
                aria-invalid={Boolean(phoneIssue) && !country}
                aria-describedby="account-profile-phone-help"
              >
                <option value="">Choose a country or region</option>
                {COUNTRY_CHOICES.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              <span>Mobile number</span>
              <input
                ref={phoneInput}
                name="phone_number_e164"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={phone}
                onChange={(event) => {
                  setPhone(event.target.value);
                  setPhoneIssue("");
                }}
                aria-invalid={Boolean(phoneIssue)}
                aria-describedby={
                  phoneIssue
                    ? "account-profile-phone-error account-profile-phone-help"
                    : "account-profile-phone-help"
                }
              />
              <small id="account-profile-phone-help">
                Include + and the country code, with no spaces. This number is
                not verified yet.
              </small>
              {phoneIssue ? (
                <small
                  className={styles.fieldError}
                  id="account-profile-phone-error"
                >
                  {phoneIssue}
                </small>
              ) : null}
            </label>
          </div>
          {notice ? (
            <p className={styles.notice} role="alert">
              {notice}
            </p>
          ) : null}
          <button className={styles.primary} type="submit">
            Save details and check access{" "}
            <ArrowRight size={18} aria-hidden="true" />
          </button>
          <p className={styles.assurance}>
            <ShieldCheck size={17} aria-hidden="true" /> Your audio stays in
            this browser until AC confirms access.
          </p>
        </form>
      ) : null}

      {phase === "blocked" ? (
        <div className={styles.recovery}>
          <p role="status">
            {notice ||
              "Your profile is saved, but AC has not confirmed call review access yet. No audio was uploaded."}
          </p>
          {profile?.phone_number_e164 && !profile.phone_verified ? (
            <small>Your mobile number is not verified yet.</small>
          ) : null}
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={retry}>
              <RefreshCw size={17} aria-hidden="true" /> Check access again
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setPhase("form")}
            >
              Edit details
            </button>
          </div>
        </div>
      ) : null}

      {phase === "ready" ? (
        <div className={styles.recovery} role="status">
          <p>AC has confirmed this profile is ready for call review.</p>
          <small>No audio was uploaded in this local preview.</small>
        </div>
      ) : null}

      {phase === "signed_out" ? (
        <div className={styles.recovery}>
          <p role="alert">
            Your AC session has ended. Sign in again to continue with this
            selected file.
          </p>
          {onSignIn ? (
            <button type="button" className={styles.primary} onClick={onSignIn}>
              Sign in again <ArrowRight size={17} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      ) : null}

      {phase === "error" ? (
        <div className={styles.recovery}>
          <p role="alert">{notice}</p>
          <button type="button" className={styles.primary} onClick={retry}>
            <RefreshCw size={17} aria-hidden="true" /> Try again
          </button>
        </div>
      ) : null}
    </section>
  );
}
