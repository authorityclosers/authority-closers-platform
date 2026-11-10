"use client";

/**
 * The permissions checklist right after sign-in, in the phone app (owner, 30
 * Oct 2026, fix 5: "the app cannot be used until all are granted"). One screen:
 * call log, phone, contacts, notifications and the recordings folder, each with
 * Allow, or Open settings once Android won't ask again. It covers every page
 * until all that this app build can grant are granted; items the build can't
 * ask for say so and never lock anyone out (permissions-rules.ts).
 *
 * In an organisation's workspace (owner, 3 Nov 2026) it is read at every open
 * and every return to the app, so a permission taken away in Android's
 * settings brings it back. Two more rows join it there: the battery, and
 * "Analyse my calls automatically", the one-time standing consent with its
 * sealed words, never pre-ticked and never filled from storage. Call history,
 * the battery and the consent offer Not now; a put-off one stays as a slim
 * reminder until it is done. A personal workspace keeps the checklist it had.
 *
 * It waits for the Terms card and Home's first run, and call capture setup and
 * "Set up this phone" wait for it. Nothing shows in a browser or an app too
 * old to say what it has.
 */

import {
  BatteryCharging,
  Bell,
  CheckCircle2,
  Contact,
  FolderOpen,
  History,
  Phone,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import {
  acquisition,
  parsePolicy,
  type UploadPolicy,
} from "../acquisition-client";
import { PLAY_LISTING } from "../app-compatibility-provider";
import styles from "../leads/phone-onboarding.module.css";
import {
  askCallAccess,
  askContacts,
  askNotifications,
  autoCaptureSetup,
  callLogSetup,
  callLogStatus,
  inPhoneApp,
  onPhoneSignal,
  pickRecordingsFolder,
  setupMark,
  setupOpen,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import { dismissNotice, notify, useNoticeShown } from "../notice-center";
import {
  chooseAutoAnalysis,
  readAutoAnalysis,
  type AutoAnalysis,
} from "../settings/auto-analysis-client";
import { useBackClose } from "../ui/back-close";
import { Button } from "../ui/kit";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import { recordCaptureSetup } from "./capture-setup-client";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import own from "./capture-setup.module.css";
import {
  PERMISSIONS_ATTRIBUTE,
  checklistOpen,
  permissionItems,
  putOffKey,
  reminders,
  sayBatteryDone,
  toAnswer,
  waitsFor,
  type ConsentFact,
  type PermissionItem,
  type PermissionKey,
} from "./permissions-rules";
import { named } from "./product-name";

const ICONS: Record<PermissionKey, LucideIcon> = {
  callLog: History,
  phone: Phone,
  contacts: Contact,
  notifications: Bell,
  recordings: FolderOpen,
  battery: BatteryCharging,
  autoAnalysis: ShieldCheck,
};

const CONSENT_ATTRIBUTE = "data-sx-consent";
const REMINDER_ID = "permissions-later";
const OPEN_EVENT = "sx-permissions-open";

/**
 * The first-run screens that fill the page (Terms, Home's first run, "Set up
 * this phone"): the reminder waits for them, so it never sits over their
 * buttons (Redmi, v1.35 staging: it covered "Report a problem").
 */
const FULL_PAGE = [
  CONSENT_ATTRIBUTE,
  FIRST_RUN_ATTRIBUTE,
  CAPTURE_SETUP_ATTRIBUTE,
];
function watchFullPage(changed: () => void) {
  const watch = new MutationObserver(changed);
  watch.observe(document.documentElement, {
    attributes: true,
    attributeFilter: FULL_PAGE,
  });
  return () => watch.disconnect();
}
const fullPageOpen = () =>
  FULL_PAGE.some((name) => document.documentElement.hasAttribute(name));
const noFullPage = () => false;

/**
 * A sheet is up: the reminder waits until it closes, so it never covers the
 * sheet's own buttons (Redmi QA on production, 10 Nov 2026: Appearance in the
 * account menu, Add lead's footer, Notes, Remind me's times, Move).
 */
function watchSheets(changed: () => void) {
  const watch = new MutationObserver(changed);
  watch.observe(document.body, {
    attributes: true,
    attributeFilter: ["open"],
    childList: true,
    subtree: true,
  });
  return () => watch.disconnect();
}
const sheetOpen = () => document.querySelector("dialog[open]") !== null;

/**
 * Turn on from the Calls line (owner, 3 Nov 2026): the checklist again, at the
 * consent row with its sealed words. Only the phone app has the checklist.
 */
export function askConsent(): void {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

/** The checklist itself, for the gate and the review fixture. */
export function PermissionsChecklist({
  items,
  busy,
  tried,
  putOff = new Set(),
  onAllow,
  onSettings,
  onLater,
}: {
  items: readonly PermissionItem[];
  busy: PermissionKey | null;
  /** Asked once and still not granted: Android may not ask again. */
  tried: ReadonlySet<PermissionKey>;
  /** Put off with Not now (putOffKey). */
  putOff?: ReadonlySet<string>;
  onAllow: (key: PermissionKey) => void;
  onSettings: (key: PermissionKey) => void;
  onLater?: (item: PermissionItem) => void;
}) {
  const titleId = useId();
  const left = items.filter(waitsFor).length;
  const offering = toAnswer(items, putOff).filter((item) => !waitsFor(item));
  const offered = offering.length;
  // Name only the buttons on screen: the battery's is Done, the others' Not now
  // (phone QA on v1.36, 3 Nov 2026: "choose Not now" over the battery alone).
  const onlyBattery = offering.every((item) => item.key === "battery");
  return (
    <div className={own.permissions} aria-labelledby={titleId} role="group">
      <h1 id={titleId} className={styles.title}>
        {named("Allow what Sales X-Ray needs")}
      </h1>
      <p className={styles.line}>
        {left
          ? `Sales X-Ray works once these are allowed. ${left === 1 ? "1 left." : `${left} left.`}`
          : offered
            ? onlyBattery
              ? "This helps too. Check it, or tap Done once it's set."
              : "These help too. Allow them, or choose Not now."
            : "All set. Sales X-Ray is ready."}
      </p>
      <ul className={own.grants}>
        {items.map((item) => {
          const Icon = ICONS[item.key];
          const settings =
            item.state === "blocked" ||
            (item.state === "needed" && tried.has(item.key));
          const later =
            onLater &&
            item.canWait &&
            (item.state === "needed" || item.state === "blocked");
          // The battery: Check opens its page, and Done is the seller's word
          // when Android can't see it (HyperOS). The consent: one tap, Turn on
          // (owner, 3 Nov 2026).
          const allowWord =
            item.key === "battery"
              ? "Check"
              : item.key === "autoAnalysis"
                ? "Turn on"
                : "Allow";
          const laterWord = item.key === "battery" ? "Done" : "Not now";
          const saidDone =
            item.key === "battery" && putOff.has(putOffKey(item));
          const done = item.state === "granted" || saidDone;
          return (
            <li key={item.key} data-state={done ? "granted" : item.state}>
              <span className={own.grantIcon}>
                {done ? (
                  <CheckCircle2 size={20} aria-hidden="true" />
                ) : (
                  <Icon size={20} aria-hidden="true" />
                )}
              </span>
              <span className={own.grantText}>
                <strong>{item.label}</strong>
                <small>
                  {item.state === "update"
                    ? named("Update Sales X-Ray to allow this.")
                    : item.state === "later"
                      ? named(
                          "Comes in a later Google Play version of Sales X-Ray.",
                        )
                      : item.state === "elsewhere"
                        ? "Turns on in your organisation's workspace."
                        : item.key === "autoAnalysis"
                          ? // The sealed consent words, exactly as the server has them.
                            item.why
                          : named(item.why)}
                </small>
              </span>
              {done ? (
                <span className={own.granted}>
                  {item.state !== "granted"
                    ? "Done"
                    : item.key === "autoAnalysis" || item.key === "battery"
                      ? "On"
                      : "Allowed"}
                </span>
              ) : item.state === "update" ? (
                <a
                  className={own.link}
                  href={PLAY_LISTING}
                  target="_blank"
                  rel="noreferrer"
                >
                  Update
                </a>
              ) : item.state === "later" ||
                item.state === "elsewhere" ? null : (
                <span className={own.grantActions}>
                  <Button
                    variant={settings ? "ghost" : "primary"}
                    disabled={busy !== null}
                    aria-busy={busy === item.key || undefined}
                    aria-label={`${settings ? "Open settings for" : allowWord} ${item.label}`}
                    onClick={() =>
                      settings ? onSettings(item.key) : onAllow(item.key)
                    }
                  >
                    {settings ? "Open settings" : allowWord}
                  </Button>
                  {later ? (
                    <Button
                      variant="ghost"
                      disabled={busy !== null}
                      aria-label={`${laterWord}: ${item.label}`}
                      onClick={() => onLater(item)}
                    >
                      {laterWord}
                    </Button>
                  ) : null}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

async function ask(key: PermissionKey): Promise<void> {
  switch (key) {
    case "callLog": {
      // Work calls are logged from the SIM the seller works on; the first one by default.
      const log = await callLogStatus();
      await callLogSetup(true, log?.sim || log?.sims[0]?.id || "");
      return;
    }
    case "phone":
      await askCallAccess();
      return;
    case "contacts":
      await askContacts();
      return;
    case "notifications":
      await askNotifications();
      return;
    case "recordings":
      await pickRecordingsFolder();
      return;
    case "battery":
    case "autoAnalysis":
      // Their own screens: the gate reads again when the seller comes back.
      return;
  }
}

/** Not now, per person and workspace: a reminder, never a choice made for them. */
function laterKey(person: string, tenant: string): string {
  return `sales-xray:permissions-later:${person}:${tenant}`;
}

function readLater(key: string): Set<string> {
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) ?? "[]") as unknown;
    return new Set(
      Array.isArray(raw) ? raw.filter((v) => typeof v === "string") : [],
    );
  } catch {
    return new Set();
  }
}

function writeLater(key: string, value: ReadonlySet<string>) {
  try {
    window.localStorage.setItem(key, JSON.stringify([...value]));
  } catch {
    // Private mode or storage off: Not now lasts for this visit.
  }
}

type Consent = Readonly<{ view: AutoAnalysis; policy: UploadPolicy }>;

/** The standing consent and the upload terms in force; null when either fails. */
async function readConsent(): Promise<Consent | null> {
  try {
    const [view, policy] = await Promise.all([
      readAutoAnalysis(),
      acquisition("/upload-policy").then(parsePolicy),
    ]);
    return { view, policy };
  } catch {
    return null;
  }
}

function consentFact(consent: Consent | null): ConsentFact {
  const notice = consent?.view.notice;
  if (!consent) return null;
  if (consent.view.state === "unavailable")
    return { state: "unavailable", words: "", version: "" };
  if (!notice) return null;
  return {
    state: consent.view.state,
    words: notice.text,
    version: notice.version,
  };
}

export function PermissionsGate() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true && access.status === "ready";
  const tenant = access?.context?.tenantId ?? "";
  const person = access?.context?.personId ?? "";
  // Call logging works only in an organisation's workspace; elsewhere it never blocks.
  const organisation =
    access?.workspaces?.find((item) => item.tenant_id === tenant)?.kind ===
    "organisation";
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [decided, setDecided] = useState(false);
  const [busy, setBusy] = useState<PermissionKey | null>(null);
  const [tried, setTried] = useState<ReadonlySet<PermissionKey>>(new Set());
  // Not now, kept on this device per person and workspace, and for this visit
  // when the device can't keep it.
  const [visitLater, setVisitLater] = useState<ReadonlySet<string>>(new Set());
  // The reminder's Finish: the checklist again, with the put-off rows.
  const [reopened, setReopened] = useState(false);
  // The reminder was tapped or closed: not again until the app opens again.
  const reminded = useRef(false);
  const fullPage = useSyncExternalStore(
    watchFullPage,
    fullPageOpen,
    noFullPage,
  );
  const sheet = useSyncExternalStore(watchSheets, sheetOpen, noFullPage);
  // Capture setup's own "Recording isn't set up" card says the same thing for
  // now: the reminder waits until it has gone.
  const recordingCard = useNoticeShown("capture-setup");
  const away = useRef(false);

  useEffect(() => {
    const open = () => setReopened(true);
    window.addEventListener(OPEN_EVENT, open);
    return () => window.removeEventListener(OPEN_EVENT, open);
  }, []);

  const storageKey =
    organisation && person && tenant ? laterKey(person, tenant) : "";
  const putOff = useMemo<ReadonlySet<string>>(
    () =>
      new Set([...(storageKey ? readLater(storageKey) : []), ...visitLater]),
    [storageKey, visitLater],
  );

  const read = useCallback(async () => {
    const [next, nextConsent] = await Promise.all([
      setupStatus(),
      organisation ? readConsent() : Promise.resolve(null),
    ]);
    setStatus(next);
    setConsent(nextConsent);
    setDecided(true);
    return next;
  }, [organisation]);

  // After the Terms card and Home's first run: one screen at a time.
  useEffect(() => {
    if (!signedIn || !inPhoneApp()) return;
    let stopped = false;
    let started = false;
    const html = document.documentElement;
    const waiting = () =>
      html.hasAttribute(CONSENT_ATTRIBUTE) ||
      html.hasAttribute(FIRST_RUN_ATTRIBUTE);
    const start = () => {
      if (stopped || started || waiting()) return;
      started = true;
      void (async () => {
        const [next, nextConsent] = await Promise.all([
          setupStatus(),
          organisation ? readConsent() : Promise.resolve(null),
        ]);
        if (stopped) return;
        setStatus(next);
        setConsent(nextConsent);
        setDecided(true);
      })();
    };
    start();
    const watch = new MutationObserver(start);
    watch.observe(html, {
      attributes: true,
      attributeFilter: [CONSENT_ATTRIBUTE, FIRST_RUN_ATTRIBUTE],
    });
    return () => {
      stopped = true;
      watch.disconnect();
    };
  }, [signedIn, organisation]);

  // Back in the app: from Android's settings or the folder picker, and, in an
  // organisation's workspace, every return, so a permission taken away shows.
  useEffect(
    () =>
      onPhoneSignal((event) => {
        if (event !== "resume" || !decided) return;
        if (!away.current && !organisation) return;
        away.current = false;
        void read();
      }),
    [read, decided, organisation],
  );

  const items = status
    ? permissionItems(status, {
        organisation,
        consent: organisation ? consentFact(consent) : null,
      })
    : [];
  const later = reminders(items, putOff);
  const open =
    Boolean(status) &&
    (checklistOpen(items, putOff) || (reopened && later.length > 0));
  const deciding = signedIn && inPhoneApp() && !decided;

  useEffect(() => {
    const html = document.documentElement;
    if (deciding || open) html.setAttribute(PERMISSIONS_ATTRIBUTE, "");
    else html.removeAttribute(PERMISSIONS_ATTRIBUTE);
    return () => html.removeAttribute(PERMISSIONS_ATTRIBUTE);
  }, [deciding, open]);

  // A put-off row stays as one slim line until it is done, or until Finish or
  // the X is tapped, once per app open (orchestrator, 3 Nov 2026: it left by
  // itself after 5 s). On Leads it is the line above the rows; elsewhere the
  // corner, which the page keeps room for.
  const remind =
    open || fullPage || sheet || recordingCard
      ? ""
      : later.map((item) => item.label).join(" · ");
  useEffect(() => {
    if (!remind || reminded.current) {
      dismissNotice(REMINDER_ID);
      return;
    }
    notify({
      id: REMINDER_ID,
      tone: "info",
      title: "Finish setting up",
      message: remind,
      action: {
        label: "Finish",
        icon: "none",
        run: () => {
          reminded.current = true;
          setReopened(true);
        },
      },
      slim: true,
      pillAction: true,
      noReport: true,
      dock: true,
      timeout: 0,
      onDismiss: async () => {
        reminded.current = true;
      },
    });
  }, [remind]);

  // Back is Not now for the rows that can wait (never the battery's Done or the
  // consent, which are the seller's own words), and closes the checklist the
  // reminder reopened (Redmi QA on production, 10 Nov 2026: Back did nothing).
  // What the app needs to work still holds it; Escape still doesn't close it.
  useBackClose(open, () => {
    if (reopened) {
      setReopened(false);
      return;
    }
    const keys = toAnswer(items, putOff)
      .filter(
        (item) =>
          item.canWait &&
          !waitsFor(item) &&
          item.key !== "battery" &&
          item.key !== "autoAnalysis",
      )
      .map(putOffKey);
    if (!keys.length) return;
    setVisitLater(new Set([...visitLater, ...keys]));
    if (storageKey) writeLater(storageKey, new Set([...putOff, ...keys]));
  });

  // A modal dialog over every page; Escape doesn't close it.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = frame.current;
    if (open && node && !node.open) node.showModal?.();
  }, [open]);

  if (!open) return null;
  const allow = async (key: PermissionKey) => {
    setBusy(key);
    try {
      if (key === "battery") {
        away.current = true;
        await setupOpen("battery");
      } else if (key === "autoAnalysis") {
        const notice = consent?.view.notice;
        if (!notice || !consent) return;
        // The seller's own choice, once, with the words as shown and the terms in force.
        await chooseAutoAnalysis({
          decision: "granted",
          notice,
          uploadPolicySha256: consent.policy.policy_sha256,
        });
        // Automatic upload follows from it; the app's own confirmation shows the words again.
        away.current = true;
        await autoCaptureSetup(true, false).catch(() => null);
      } else await ask(key);
    } catch {
      // Android said no, or the phone didn't answer: Open settings next.
    } finally {
      setBusy(null);
    }
    const next = await read();
    const still = next
      ? permissionItems(next, { organisation }).find((item) => item.key === key)
      : undefined;
    if (still && still.state !== "granted" && key !== "battery")
      setTried((value) => new Set(value).add(key));
  };
  const settings = (key: PermissionKey) => {
    if (key === "recordings" || key === "battery") {
      void allow(key);
      return;
    }
    away.current = true;
    void setupOpen(key === "notifications" ? "notifications" : "appSettings");
  };
  const putAside = (item: PermissionItem) => {
    const next = new Set(putOff).add(putOffKey(item));
    setVisitLater(new Set(visitLater).add(putOffKey(item)));
    setReopened(false);
    if (storageKey) writeLater(storageKey, next);
    // Done is the seller's word for battery and Autostart: Set up this phone asks for neither again.
    if (item.key === "battery") {
      sayBatteryDone();
      void setupMark("autostart", true);
    }
    // The capture setup's own record of not now: it asks again on its own days.
    if (item.key === "autoAnalysis")
      void recordCaptureSetup({ outcome: "declined" }).catch(() => null);
  };
  return (
    <dialog
      ref={frame}
      className={styles.page}
      data-permissions=""
      onCancel={(event) => event.preventDefault()}
    >
      <div className={styles.body}>
        <PermissionsChecklist
          items={items}
          busy={busy}
          tried={tried}
          putOff={reopened ? new Set() : putOff}
          onAllow={(key) => void allow(key)}
          onSettings={settings}
          onLater={putAside}
        />
      </div>
    </dialog>
  );
}
