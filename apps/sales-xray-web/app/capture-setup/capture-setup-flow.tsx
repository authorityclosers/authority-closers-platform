"use client";

/**
 * Call capture setup, one screen at a time (owner, 30 Oct 2026: "simple clicks
 * and disclosure one by one"). Each screen has one sentence on why, one primary
 * button, and Android's own screen when one is needed; it goes on by itself.
 *
 * 1. Your name and phone (the profile the upload's write-eligibility check reads).
 * 2. What Sales X-Ray captures and why, then the owner's approved consent words
 *    (auto-analysis), never pre-ticked. "Not now" is recorded and asked again.
 * 3. The call recordings folder (Android's folder picker), with the recorder's
 *    switch when it is off.
 * 4. Running in the background: battery, and Autostart on phones that need it.
 * 5. Uploads on (the app's own confirmation shows the words again), then
 *    "You're set" with the last recording found, recorded for Team.
 *
 * The web shows 1 and 2, then "finish on your phone". The look is "Set up this
 * phone"'s (phone-onboarding.module.css): a full screen, buttons in thumb reach.
 */

import {
  BatteryCharging,
  CheckCircle2,
  Circle,
  FolderOpen,
  Mic,
  Power,
  ShieldCheck,
  Smartphone,
  UploadCloud,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  normalizeProfilePhoneInput,
  readAccountProfile,
  updateAccountProfile,
  validE164Phone,
  type AccountProfileRecord,
} from "../account-profile-client";
import {
  acquisition,
  parsePolicy,
  type UploadPolicy,
} from "../acquisition-client";
import { PLAY_LISTING } from "../app-compatibility-provider";
import styles from "../leads/phone-onboarding.module.css";
import { recorderGuide } from "../leads/phone-setup-words";
import {
  askNotifications,
  autoCaptureSetup,
  autoCaptureStatus,
  buzz,
  onPhoneSignal,
  pickRecordingsFolder,
  recorderOpen,
  setupMark,
  setupOpen,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import { notify } from "../notice-center";
import {
  chooseAutoAnalysis,
  readAutoAnalysis,
  type AutoAnalysis,
} from "../settings/auto-analysis-client";
import { useBackClose } from "../ui/back-close";
import { Button, Skeleton } from "../ui/kit";
import { recordCaptureSetup, type CaptureSetup } from "./capture-setup-client";
import {
  phoneFacts,
  savedWhen,
  stepsFor,
  type CaptureStep,
  type PhoneFacts,
} from "./capture-setup-rules";
import own from "./capture-setup.module.css";
import { named } from "./product-name";

type Phone = { status: SetupStatus | null; facts: PhoneFacts | null };

/** One step's screen: icon, title, the why, then its buttons. */
function Screen({
  icon: Icon,
  title,
  titleId,
  line,
  children,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  titleId: string;
  line?: ReactNode;
  children?: ReactNode;
  actions: ReactNode;
}) {
  return (
    <>
      <div className={styles.body}>
        <span className={styles.icon}>
          <Icon size={28} aria-hidden="true" />
        </span>
        <h1 id={titleId} className={styles.title}>
          {named(title)}
        </h1>
        {line ? (
          <p className={styles.line}>
            {typeof line === "string" ? named(line) : line}
          </p>
        ) : null}
        {children}
      </div>
      <div className={styles.actions}>{actions}</div>
    </>
  );
}

const message = (reason: unknown) =>
  reason instanceof Error && reason.message ? reason.message : "Try again.";

/** Step 1: the name and phone the upload's check needs. */
function ProfileStep({
  titleId,
  onDone,
}: {
  titleId: string;
  onDone: () => void;
}) {
  const [profile, setProfile] = useState<AccountProfileRecord | null>(null);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [issue, setIssue] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readAccountProfile(controller.signal).then(
      (found) => {
        setProfile(found);
        setName(found.name ?? "");
        setPhone(found.phone_number_e164 ?? "");
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, []);

  const save = async () => {
    if (!profile) return;
    const fullName = name.trim().replace(/\s+/g, " ");
    const number = normalizeProfilePhoneInput(phone, "IN");
    if (!fullName) return setIssue("Add your name.");
    if (!validE164Phone(number))
      return setIssue(
        "Add your mobile number: 10 digits, or + and the country code.",
      );
    setIssue(null);
    setSaving(true);
    try {
      await updateAccountProfile({
        full_name: fullName,
        phone_number_e164: number,
        expected_revision: profile.revision,
      });
      onDone();
    } catch {
      setIssue("Not saved. Check the number and try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen
      icon={UserRound}
      title="Your name and phone"
      titleId={titleId}
      line="Your team sees who made each call, and Sales X-Ray uploads calls only for a seller with a name and phone number."
      actions={
        <Button
          variant="primary"
          disabled={!profile || saving}
          aria-busy={saving || undefined}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save and continue"}
        </Button>
      }
    >
      {failed ? (
        <p className={own.note} role="status">
          Your profile couldn&apos;t load. Check your connection, then open this
          page again.
        </p>
      ) : !profile ? (
        <Skeleton height={120} />
      ) : (
        <form
          className={own.form}
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            <span>Your name</span>
            <input
              value={name}
              autoComplete="name"
              maxLength={200}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>Your mobile number</span>
            <input
              value={phone}
              inputMode="tel"
              autoComplete="tel"
              maxLength={20}
              placeholder="98765 43210"
              onChange={(event) => setPhone(event.target.value)}
            />
            <small>10 digits, or + and the country code.</small>
          </label>
          {issue ? (
            <p className={own.issue} role="alert">
              {issue}
            </p>
          ) : null}
        </form>
      )}
    </Screen>
  );
}

/** What is captured and why, in plain words, around the owner's sealed sentence. */
const CAPTURES = [
  "Sales X-Ray checks the recordings folder you choose, also when the app is closed.",
  "It uploads only calls with your leads: the lead's number and the call's time must match. Other calls and files stay on your phone.",
  "You get 60 seconds to Undo each upload.",
  "Each call is analysed for its report, at your organisation's AI setting. Audio is encrypted and can be deleted from Calls.",
];

/** Step 2: the disclosure, then agreeing (the standing consent) or not now. */
function ConsentStep({
  titleId,
  setup,
  personal,
  onAgreed,
  onDeclined,
}: {
  titleId: string;
  setup: CaptureSetup;
  personal: boolean;
  onAgreed: () => void;
  onDeclined: (next: CaptureSetup) => void;
}) {
  const [view, setView] = useState<AutoAnalysis | null>(null);
  const [terms, setTerms] = useState<UploadPolicy | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (personal) return;
    const controller = new AbortController();
    Promise.all([
      readAutoAnalysis(controller.signal),
      acquisition("/upload-policy", { signal: controller.signal }).then(
        parsePolicy,
      ),
    ]).then(
      ([next, policy]) => {
        setView(next);
        setTerms(policy);
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [personal]);

  if (personal)
    return (
      <Screen
        icon={ShieldCheck}
        title="Your calls in your own workspace"
        titleId={titleId}
        line="Calls upload by themselves in an organisation's workspace. Here, Sales X-Ray finds each lead call's recording on this phone, and you choose to upload it."
        actions={
          <Button variant="primary" onClick={onAgreed}>
            Continue
          </Button>
        }
      />
    );

  const agreed = view?.state === "on" || setup.consent === "on";
  const notice = view?.notice;
  const agree = async () => {
    if (!notice || !terms) return;
    setSaving(true);
    try {
      await chooseAutoAnalysis({
        decision: "granted",
        notice,
        uploadPolicySha256: terms.policy_sha256,
      });
      buzz("done");
      onAgreed();
    } catch (reason) {
      notify({
        id: "capture-setup",
        tone: "error",
        title: "Not saved",
        message: message(reason),
      });
    } finally {
      setSaving(false);
    }
  };
  const decline = async () => {
    setSaving(true);
    try {
      onDeclined(await recordCaptureSetup({ outcome: "declined" }));
    } catch (reason) {
      notify({
        id: "capture-setup",
        tone: "error",
        title: "Not saved",
        message: message(reason),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen
      icon={ShieldCheck}
      title="What Sales X-Ray captures"
      titleId={titleId}
      line="So every call with a lead gets its report, without you uploading it."
      actions={
        agreed ? (
          <Button variant="primary" onClick={onAgreed}>
            Continue
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              disabled={saving || !notice || !terms}
              aria-busy={saving || undefined}
              onClick={() => void agree()}
            >
              I agree
            </Button>
            <Button
              variant="ghost"
              disabled={saving}
              onClick={() => void decline()}
            >
              Not now
            </Button>
          </>
        )
      }
    >
      <ul className={own.captures}>
        {CAPTURES.map((line) => (
          <li key={line}>{named(line)}</li>
        ))}
      </ul>
      {failed ? (
        <p className={own.note} role="status">
          The consent words couldn&apos;t load. Check your connection, then open
          this page again.
        </p>
      ) : !notice ? (
        <Skeleton height={96} />
      ) : (
        <div className={own.words}>
          <strong>{notice.title}</strong>
          <p>{notice.text}</p>
          {terms?.privacy_details ? (
            <small>{terms.privacy_details}</small>
          ) : null}
        </div>
      )}
      {agreed ? (
        <p className={own.note}>
          You agreed
          {view?.since || setup.consent_since
            ? ` on ${new Date(
                String(view?.since ?? setup.consent_since),
              ).toLocaleDateString("en-IN", {
                day: "numeric",
                month: "short",
                timeZone: "Asia/Kolkata",
              })}`
            : ""}
          . Turn it off any time in Settings, Privacy.
        </p>
      ) : (
        <p className={own.note}>
          Not now keeps calls on your phone. We&apos;ll ask again tomorrow.
        </p>
      )}
    </Screen>
  );
}

const RECORDING_STATE: Record<string, string> = {
  on: "Call recording is on.",
  off: "Call recording is off.",
};

/** Step 3: the folder, then the recorder's switch if it is off. */
function RecordingsStep({
  titleId,
  phone,
  leave,
  refresh,
  onDone,
}: {
  titleId: string;
  phone: Phone;
  leave: (after: () => Promise<void>) => void;
  refresh: () => Promise<Phone>;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const facts = phone.facts;
  const status = phone.status;
  if (!facts || !status) return null;
  const guide = recorderGuide(status.recorder, status.family);
  const dialer = status.recorder?.dialerLabel ?? "Your Phone app";

  if (facts.privateDialler)
    return (
      <Screen
        icon={Mic}
        title="This Phone app keeps recordings private"
        titleId={titleId}
        line={guide.lead}
        actions={
          <>
            {status.recorder?.switchTo ? (
              <Button
                variant="primary"
                onClick={() => {
                  void recorderOpen("defaultDialer").then((opened) => {
                    if (opened)
                      leave(async () => {
                        const next = await refresh();
                        if (!next.facts?.privateDialler)
                          setNote("Now pick its recordings folder.");
                      });
                  });
                }}
              >
                Choose the Phone app
              </Button>
            ) : null}
            <Button
              variant={status.recorder?.switchTo ? "ghost" : "primary"}
              onClick={onDone}
            >
              Continue without recordings
            </Button>
          </>
        }
      >
        <ol className={styles.steps}>
          {guide.steps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
        {note ? <p className={own.note}>{note}</p> : null}
      </Screen>
    );

  if (!facts.folderPicked)
    return (
      <Screen
        icon={FolderOpen}
        title="Pick your call recordings folder"
        titleId={titleId}
        line="Your Phone app saves each call. Choose that folder once: Android opens it for you, then tap Use this folder and Allow."
        actions={
          <Button
            variant="primary"
            disabled={busy}
            aria-busy={busy || undefined}
            onClick={() => {
              setBusy(true);
              void pickRecordingsFolder().then(async (picked) => {
                const next = picked ? await refresh() : phone;
                setBusy(false);
                if (!next.facts?.folderPicked)
                  setNote("No folder chosen yet. Tap Choose the folder again.");
                else if (!next.facts.recorderOff) onDone();
              });
            }}
          >
            Choose the folder
          </Button>
        }
      >
        <p className={own.note}>
          {dialer} on this phone.{" "}
          {RECORDING_STATE[status.recorder?.recording ?? ""] ??
            "Check that it records calls."}
        </p>
        <p className={own.fine}>
          Most Xiaomi, Redmi, POCO, Samsung, Vivo, Oppo, Realme, OnePlus and
          Huawei phones save calls by themselves. Google&apos;s Phone app keeps
          its recordings private.
        </p>
        <dl className={styles.fine}>
          <div>
            <dt>Reads</dt>
            <dd>
              Only the folder you choose. Not your photos, documents or other
              files.
            </dd>
          </div>
          <div>
            <dt>Leaves your phone</dt>
            <dd>Recordings of calls with your leads, after their Undo time.</dd>
          </div>
        </dl>
        {note ? (
          <p className={own.issue} role="status">
            {note}
          </p>
        ) : null}
      </Screen>
    );

  return (
    <Screen
      icon={Mic}
      title="Turn on call recording"
      titleId={titleId}
      line={`${dialer} saves calls only while Call recording is on.`}
      actions={
        <>
          <Button
            variant="primary"
            onClick={() => {
              void setupOpen("recorder").then((opened) => {
                if (!opened) {
                  setNote(
                    "Open your Phone app's settings yourself, then come back.",
                  );
                  return;
                }
                leave(async () => {
                  await setupMark("recorder", true);
                  await refresh();
                  onDone();
                });
              });
            }}
          >
            Open call recording settings
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              void setupMark("recorder", true).then(() => onDone());
            }}
          >
            It&apos;s on
          </Button>
        </>
      }
    >
      <ol className={styles.steps}>
        {guide.steps.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
      {note ? <p className={own.note}>{note}</p> : null}
    </Screen>
  );
}

const BRAND: Record<string, string> = {
  xiaomi: "Xiaomi",
  vivo: "Vivo",
  oppo: "Oppo",
  realme: "Realme",
  oneplus: "OnePlus",
  huawei: "Huawei",
};

/** Step 4: battery, then Autostart on the brands that stop apps. */
function BackgroundStep({
  titleId,
  phone,
  leave,
  refresh,
  onDone,
}: {
  titleId: string;
  phone: Phone;
  leave: (after: () => Promise<void>) => void;
  refresh: () => Promise<Phone>;
  onDone: () => void;
}) {
  const [tried, setTried] = useState(false);
  // Some phones never report the change: after one try the seller may go on.
  const [pastBattery, setPastBattery] = useState(false);
  const facts = phone.facts;
  if (!facts) return null;
  const autostartLeft = facts.autostartNeeded && !facts.autostart;
  const afterBattery = async () => {
    const next = (await refresh()).facts;
    if (next?.battery && !(next.autostartNeeded && !next.autostart)) onDone();
  };

  if (!facts.battery && !pastBattery)
    return (
      <Screen
        icon={BatteryCharging}
        title="Let Sales X-Ray run in the background"
        titleId={titleId}
        line="So calls upload when the app is closed, not only when you open it. It uses very little battery."
        actions={
          <>
            <Button
              variant="primary"
              onClick={() => {
                setTried(true);
                void setupOpen("battery").then((opened) => {
                  if (opened) leave(afterBattery);
                  else
                    notify({
                      id: "capture-setup",
                      tone: "info",
                      title: "Open your phone's battery settings",
                      message:
                        "Find Sales X-Ray in Settings, Apps, Battery and choose No restrictions.",
                    });
                });
              }}
            >
              Allow
            </Button>
            {tried ? (
              <Button
                variant="ghost"
                onClick={() =>
                  autostartLeft ? setPastBattery(true) : onDone()
                }
              >
                Continue anyway
              </Button>
            ) : null}
          </>
        }
      >
        {tried ? (
          <p className={own.note} role="status">
            Still restricted. Tap Allow, then choose Allow in Android&apos;s
            question.
          </p>
        ) : null}
      </Screen>
    );

  return (
    <Screen
      icon={Power}
      title="Turn on Autostart"
      titleId={titleId}
      line={`${BRAND[facts.family] ?? "Your"} phones stop apps after a restart unless Autostart is on. Switch Sales X-Ray on, then come back.`}
      actions={
        <Button
          variant="primary"
          onClick={() => {
            void setupOpen("autostart").then((opened) => {
              // Android can't tell an app whether Autostart is on: coming back counts.
              const mark = async () => {
                await setupMark("autostart", true);
                await refresh();
                onDone();
              };
              if (opened) leave(mark);
              else void mark();
            });
          }}
        >
          Open Autostart
        </Button>
      }
    />
  );
}

/** Step 5: upload notices (Undo needs them), then uploads on. */
function UploadsStep({
  titleId,
  phone,
  leave,
  refresh,
  onDone,
  onProblem,
}: {
  titleId: string;
  phone: Phone;
  leave: (after: () => Promise<void>) => void;
  refresh: () => Promise<Phone>;
  onDone: () => void;
  onProblem: (step: "profile" | "consent") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const facts = phone.facts;
  const [wifiOnly, setWifiOnly] = useState(facts?.wifiOnly ?? true);
  if (!facts) return null;

  const turnOn = async () => {
    setBusy(true);
    setNote(null);
    try {
      const status = await autoCaptureSetup(true, wifiOnly);
      await refresh();
      if (status.on) onDone();
      else setNote("Uploads are still off. Tap Turn uploads on, then Turn on.");
    } catch (reason) {
      const code = reason instanceof Error ? reason.message : "";
      if (code === "profile_required") onProblem("profile");
      else if (code === "standing_consent_required") onProblem("consent");
      else
        setNote(
          "Uploads didn't turn on. Check that the folder is still chosen, then try again.",
        );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen
      icon={UploadCloud}
      title="Turn uploads on"
      titleId={titleId}
      line="Calls with your leads upload by themselves. A notice gives you 60 seconds to Undo each one."
      actions={
        !facts.notifications ? (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              if (facts.notificationsBlocked) {
                void setupOpen("notifications").then((opened) => {
                  if (opened) leave(async () => void (await refresh()));
                });
                return;
              }
              setBusy(true);
              void askNotifications()
                .then(() => refresh())
                .finally(() => setBusy(false));
            }}
          >
            Allow upload notices
          </Button>
        ) : (
          <Button
            variant="primary"
            disabled={busy}
            aria-busy={busy || undefined}
            onClick={() => void turnOn()}
          >
            Turn uploads on
          </Button>
        )
      }
    >
      <label className={own.choice}>
        <span>Upload using</span>
        <select
          value={wifiOnly ? "wifi" : "any"}
          disabled={busy}
          onChange={(event) => setWifiOnly(event.target.value === "wifi")}
        >
          <option value="any">Wi-Fi or mobile data</option>
          <option value="wifi">Wi-Fi only</option>
        </select>
      </label>
      {note ? (
        <p className={own.issue} role="status">
          {note}
        </p>
      ) : null}
    </Screen>
  );
}

/** The last screen: what is on, and the newest recording this phone found. */
function DoneStep({
  titleId,
  phone,
  setup,
  personal,
  onDone,
}: {
  titleId: string;
  phone: Phone;
  setup: CaptureSetup;
  personal: boolean;
  onDone: (next: CaptureSetup | null) => void;
}) {
  const facts = phone.facts;
  const [saved, setSaved] = useState<CaptureSetup | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [now] = useState(() => Date.now());
  const key = useRef<string | null>(null);

  // Recorded for Team as soon as the screen shows.
  useEffect(() => {
    if (personal || !facts) return;
    key.current ??= crypto.randomUUID();
    let alive = true;
    recordCaptureSetup(
      {
        outcome: "completed",
        phone: {
          device: facts.device,
          model: facts.model,
          family: facts.family,
          app_version: facts.version,
          recordings: facts.folderPicked && !facts.privateDialler,
          background:
            facts.battery && (!facts.autostartNeeded || facts.autostart),
          uploads: facts.uploadsOn,
        },
      },
      key.current,
    ).then(
      (next) => {
        if (!alive) return;
        setSaved(next);
        buzz("done");
      },
      () => {
        if (alive) setFailed(true);
      },
    );
    return () => {
      alive = false;
    };
  }, [personal, facts, attempt]);

  if (!facts) return null;
  const when = savedWhen(facts.newestMs, now);
  const lines: [string, boolean][] = [
    ["Your name and phone", setup.profile_complete !== false],
    ...(personal
      ? []
      : ([["Agreed to call capture", true]] as [string, boolean][])),
    ["Recordings folder chosen", facts.folderPicked && !facts.privateDialler],
    [
      "Runs in the background",
      facts.battery && (!facts.autostartNeeded || facts.autostart),
    ],
    ...(personal
      ? []
      : ([["Uploads on", facts.uploadsOn]] as [string, boolean][])),
  ];
  return (
    <Screen
      icon={CheckCircle2}
      title="You're set"
      titleId={titleId}
      line={
        when
          ? `Last call recording found ${when}.`
          : "No call recording found yet. Call a lead: its recording uploads by itself."
      }
      actions={
        failed && !saved ? (
          <Button
            variant="primary"
            onClick={() => {
              setFailed(false);
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </Button>
        ) : (
          <Button
            variant="primary"
            disabled={!personal && !saved}
            onClick={() => onDone(saved)}
          >
            Start working
          </Button>
        )
      }
    >
      <ul className={own.checks}>
        {lines.map(([label, on]) => (
          <li key={label} data-on={on ? "" : undefined}>
            {on ? (
              <CheckCircle2 size={18} aria-hidden="true" />
            ) : (
              <Circle size={18} aria-hidden="true" />
            )}
            <span>{label}</span>
            <span className={own.hidden}>{on ? "done" : "not done"}</span>
          </li>
        ))}
      </ul>
      {failed && !saved ? (
        <p className={own.issue} role="status">
          This couldn&apos;t be saved. Check your connection and try again.
        </p>
      ) : null}
    </Screen>
  );
}

/** The web's last screen, or an app too old to upload calls by itself. */
function PhoneStep({
  titleId,
  inApp,
  onDone,
}: {
  titleId: string;
  inApp: boolean;
  onDone: () => void;
}) {
  return (
    <Screen
      icon={Smartphone}
      title={inApp ? "Update Sales X-Ray" : "Now finish on your phone"}
      titleId={titleId}
      line={
        inApp
          ? "This version can't upload calls by itself. Update it from Google Play, then open it again."
          : "Calls are captured on the phone you call from. Open Sales X-Ray there to choose the recordings folder, let it run in the background and turn uploads on."
      }
      actions={
        <Button variant="primary" onClick={onDone}>
          Continue
        </Button>
      }
    >
      <a
        className={own.link}
        href={PLAY_LISTING}
        target="_blank"
        rel="noreferrer"
      >
        {inApp ? "Update on Google Play" : "Get Sales X-Ray on Google Play"}
      </a>
    </Screen>
  );
}

export function CaptureSetupFlow({
  setup: first,
  phone: start,
  inApp,
  required,
  organisation,
  onFinish,
  onDeclined,
  onClose,
  startAt,
}: {
  setup: CaptureSetup;
  /** The phone app's answer when the flow opened; null on the web. */
  phone: { status: SetupStatus | null } | null;
  inApp: boolean;
  /** An organisation's seller: no close, and Not now is recorded. */
  required: boolean;
  organisation: string | null;
  onFinish: (next: CaptureSetup | null) => void;
  onDeclined: (next: CaptureSetup) => void;
  onClose: () => void;
  /** Review fixtures: open at this step when it is one of the steps. */
  startAt?: CaptureStep;
}) {
  const personal = first.workspace === "personal";
  const [setup, setSetup] = useState(first);
  const [phone, setPhone] = useState<Phone>(() => ({
    status: start?.status ?? null,
    facts: null,
  }));
  const [steps, setSteps] = useState<CaptureStep[] | null>(null);
  const [index, setIndex] = useState(0);
  const [away, setAway] = useState(false);
  const afterAway = useRef<(() => Promise<void>) | null>(null);
  const titleId = useId();

  const refresh = useCallback(async (): Promise<Phone> => {
    if (!inApp) return { status: null, facts: null };
    const [status, capture] = await Promise.all([
      setupStatus(),
      autoCaptureStatus(),
    ]);
    const next = { status, facts: phoneFacts(status, capture) };
    setPhone(next);
    return next;
  }, [inApp]);

  // The steps, from what the server and this phone say when it opens.
  useEffect(() => {
    let alive = true;
    void (async () => {
      const [status, capture] = inApp
        ? await Promise.all([setupStatus(), autoCaptureStatus()])
        : [null, null];
      if (!alive) return;
      const facts = phoneFacts(status, capture);
      setPhone({ status, facts });
      const planned = stepsFor(first, facts);
      setSteps(planned);
      if (startAt) setIndex(Math.max(0, planned.indexOf(startAt)));
    })();
    return () => {
      alive = false;
    };
  }, [first, inApp, startAt]);

  // Back from one of Android's screens: read the phone again, then go on.
  useEffect(() => {
    if (!away) return;
    return onPhoneSignal((event) => {
      if (event !== "resume") return;
      setAway(false);
      const then = afterAway.current;
      afterAway.current = null;
      void then?.();
    });
  }, [away]);
  const leave = useCallback((after: () => Promise<void>) => {
    afterAway.current = after;
    setAway(true);
  }, []);

  const next = useCallback(() => {
    setIndex((at) => at + 1);
  }, []);
  // Back closes an optional run; a required one stays until it is done or declined.
  useBackClose(!required, onClose);

  // A modal dialog, above the page and its sheets.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = frame.current;
    if (node && !node.open) node.showModal?.();
  }, [steps]);

  const step = steps?.[index];
  // Past the last step (the web's steps end without "done").
  useEffect(() => {
    if (steps && index >= steps.length) onFinish(setup);
  }, [steps, index, setup, onFinish]);
  if (!steps || !step) return null;

  const problem = (fix: "profile" | "consent") => {
    // A refusal from the phone: that step again, then back here.
    setSteps([...steps.slice(0, index), fix, ...steps.slice(index)]);
  };

  let screen: ReactNode;
  switch (step) {
    case "profile":
      screen = (
        <ProfileStep
          titleId={titleId}
          onDone={() => {
            setSetup((value) => ({ ...value, profile_complete: true }));
            next();
          }}
        />
      );
      break;
    case "consent":
      screen = (
        <ConsentStep
          titleId={titleId}
          setup={setup}
          personal={personal}
          onAgreed={() => {
            setSetup((value) =>
              personal ? value : { ...value, consent: "on" },
            );
            next();
          }}
          onDeclined={(saved) => {
            notify({
              id: "capture-setup",
              tone: "info",
              title: "Calls stay on your phone",
              message:
                "We'll ask again tomorrow. Turn call capture on any time in Settings, Privacy.",
            });
            onDeclined(saved);
          }}
        />
      );
      break;
    case "recordings":
      screen = (
        <RecordingsStep
          titleId={titleId}
          phone={phone}
          leave={leave}
          refresh={refresh}
          onDone={next}
        />
      );
      break;
    case "background":
      screen = (
        <BackgroundStep
          titleId={titleId}
          phone={phone}
          leave={leave}
          refresh={refresh}
          onDone={next}
        />
      );
      break;
    case "uploads":
      screen = (
        <UploadsStep
          titleId={titleId}
          phone={phone}
          leave={leave}
          refresh={refresh}
          onDone={next}
          onProblem={problem}
        />
      );
      break;
    case "done":
      screen = (
        <DoneStep
          titleId={titleId}
          phone={phone}
          setup={setup}
          personal={personal}
          onDone={(saved) => onFinish(saved ?? setup)}
        />
      );
      break;
    case "phone":
      screen = <PhoneStep titleId={titleId} inApp={inApp} onDone={next} />;
      break;
  }

  return (
    <dialog
      ref={frame}
      className={styles.page}
      aria-labelledby={titleId}
      data-step={step}
      onCancel={(event) => {
        event.preventDefault();
        if (!required) onClose();
      }}
    >
      <div className={styles.top}>
        {steps.length > 1 ? (
          <ol
            className={styles.dots}
            aria-label={`Step ${index + 1} of ${steps.length}`}
          >
            {steps.map((item, at) => (
              <li
                key={`${item}-${at}`}
                data-on={at <= index ? "" : undefined}
              />
            ))}
          </ol>
        ) : (
          <span />
        )}
        {required ? (
          organisation ? (
            <span className={own.where}>{organisation}</span>
          ) : null
        ) : (
          <button
            type="button"
            className={styles.close}
            aria-label="Close call capture setup"
            onClick={onClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        )}
      </div>
      {away ? (
        <p className={own.away} role="status">
          Waiting for you to come back…
        </p>
      ) : null}
      {screen}
      {!required && step !== "done" ? (
        <div className={own.skip}>
          <Button variant="ghost" onClick={next}>
            Skip
          </Button>
        </div>
      ) : null}
    </dialog>
  );
}
