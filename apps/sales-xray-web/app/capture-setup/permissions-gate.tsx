"use client";

/**
 * Phone setup right after sign-in, in the phone app (owner, 30 Oct 2026, fix
 * 5: call log, phone, contacts, notifications and the recordings folder). It
 * covers every page while something this build can grant is still to answer;
 * items the build can't ask for say so elsewhere and never lock anyone out
 * (permissions-rules.ts).
 *
 * One ask per screen (owner, 20 Nov 2026, style C "See what to tap"): the
 * walk in setup-walk.tsx shows each thing on its own screen with a picture of
 * the phone screen that comes next, and this gate does what each button asks
 * of Android and remembers each Not now. Not now on anything lets the person
 * in: a row the app needs is put off for this app open only and asked again
 * at the next one; a row that can wait is put off on this phone and stays as
 * a slim reminder until it is done.
 *
 * In an organisation's workspace (owner, 3 Nov 2026) it is read at every open
 * and every return to the app, so a permission taken away in Android's
 * settings brings it back, and two more screens join: the battery (with
 * Autostart where the maker needs it) and "Analyse my calls automatically",
 * the one-time standing consent with its sealed words, never pre-ticked and
 * never filled from storage.
 *
 * It waits for the Terms card and Home's first run, and call capture setup and
 * "Set up this phone" wait for it. Nothing shows in a browser or an app too
 * old to say what it has.
 */

import {
  useCallback,
  useEffect,
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
  openDialer,
  pickRecordingsFolder,
  setupMark,
  setupOpen,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import {
  markPrivateDiallerSeen,
  privateDiallerSeen,
} from "../leads/phone-setup-steps";
import {
  startAsk,
  trackPrompt,
  type Ask,
} from "../leads/phone-setup-telemetry";
import { dismissNotice, notify, useNoticeShown } from "../notice-center";
import {
  chooseAutoAnalysis,
  readAutoAnalysis,
  type AutoAnalysis,
} from "../settings/auto-analysis-client";
import {
  SETUP_SCREEN_ATTRIBUTE,
  screenChanged,
  track,
  type FlowVia,
} from "../telemetry";
import { useFlow } from "../telemetry-flows";
import { useBackClose } from "../ui/back-close";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import { recordCaptureSetup } from "./capture-setup-client";
import {
  CAPTURE_SETUP_ATTRIBUTE,
  PHONE_SETUP_PANEL_ATTRIBUTE,
  markTestCall,
  phoneFacts,
  recordingProven,
} from "./capture-setup-rules";
import {
  PERMISSIONS_ATTRIBUTE,
  permissionItems,
  putOffKey,
  reminders,
  sayBatteryDone,
  type ConsentFact,
  type PermissionItem,
  type PermissionKey,
} from "./permissions-rules";
import { SetupWalk } from "./setup-walk";
import walkStyles from "./setup-walk.module.css";
import {
  STEP_KEYS,
  WALK_PROMPT,
  WALK_TELEMETRY,
  WALK_WELCOMED_KEY,
  askSteps,
  captureReady,
  isAsk,
  noCallsKey,
  pendingKeys,
  readKey,
  stepOpen,
  testSkippedKey,
  walkSteps,
  writeKey,
  type AskStep,
  type WalkStep,
} from "./setup-walk-steps";
import { TEST_CALL_NUMBER } from "./setup-walk-words";

const CONSENT_ATTRIBUTE = "data-sx-consent";
const REMINDER_ID = "permissions-later";
const OPEN_EVENT = "sx-permissions-open";

/**
 * The first-run screens that fill the page (Terms, Home's first run, "Set up
 * this phone"): the reminder waits for them, so it never sits over their
 * buttons (Redmi, v1.35 staging: it covered "Report a problem"). Settings'
 * Phone setup offers the same steps itself, so it waits there too.
 */
const FULL_PAGE = [
  CONSENT_ATTRIBUTE,
  FIRST_RUN_ATTRIBUTE,
  CAPTURE_SETUP_ATTRIBUTE,
  PHONE_SETUP_PANEL_ATTRIBUTE,
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

/** Fields a keyboard types into; a box, a switch or a button isn't one. */
const NOT_TYPED = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "hidden",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);

/**
 * Someone is typing: the reminder waits until they leave the field, so it never
 * rides the keyboard over a form (Redmi QA on the owner's production build,
 * 1.55, 13 Nov 2026: on Edit details it sat above the keyboard over the
 * fields). Leaving one field for the next is one stretch of typing.
 */
function typingNow(): boolean {
  const at = document.activeElement;
  if (!(at instanceof HTMLElement)) return false;
  if (at.isContentEditable || at instanceof HTMLTextAreaElement) return true;
  return at instanceof HTMLInputElement && !NOT_TYPED.has(at.type);
}
const TYPING_PAUSE_MS = 200;
function watchTyping(changed: () => void) {
  let timer = 0;
  const now = () => {
    window.clearTimeout(timer);
    changed();
  };
  const soon = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(changed, TYPING_PAUSE_MS);
  };
  document.addEventListener("focusin", now);
  document.addEventListener("focusout", soon);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener("focusin", now);
    document.removeEventListener("focusout", soon);
  };
}
type OpenDetail = { step?: AskStep };

/**
 * Turn on from the Calls line (owner, 3 Nov 2026): the consent's own screen
 * with its sealed words. Only the phone app has phone setup.
 */
export function askConsent(): void {
  openSetupStep("analyse");
}

/**
 * Phone setup at the one screen that is missing, just in time (a call that
 * didn't upload: the recordings folder; a missed lead alert: alerts), or all
 * of what is left when no screen is named.
 */
export function openSetupStep(step?: AskStep): void {
  window.dispatchEvent(
    new CustomEvent<OpenDetail>(OPEN_EVENT, { detail: { step } }),
  );
}

/** The test call: to the organisation's number when there is one, else the empty dialer. */
function dial(number: string) {
  if (!number) {
    openDialer();
    return;
  }
  try {
    window.location.href = `tel:${number}`;
  } catch {
    openDialer();
  }
}

/** A test call's recording is looked for this long after the seller comes back. */
const TEST_WAIT_MS = 45_000;
type TestCall = { started: number; found: boolean; gaveUp: boolean };

/** Android's questions on the calls screen, in the order the phone asks them. */
function callQuestions(
  pending: ReadonlySet<PermissionKey>,
  status: SetupStatus,
): string[] {
  const questions: string[] = [];
  if (pending.has("phone"))
    questions.push("Allow Sales X-Ray to make and manage phone calls?");
  if (
    status.callLogSupported &&
    (pending.has("callLog") || pending.has("phone"))
  )
    questions.push("Allow Sales X-Ray to access your phone call logs?");
  if (pending.has("contacts"))
    questions.push("Allow Sales X-Ray to access your contacts?");
  return questions;
}

async function ask(key: PermissionKey): Promise<void> {
  switch (key) {
    case "callLog": {
      // Work calls are logged from the SIM the seller works on; the first one by default.
      const log = await callLogStatus();
      const after = await callLogSetup(
        true,
        log?.sim || log?.sims[0]?.id || "",
      );
      // Until call history is allowed the phone lists no SIMs, so a two-SIM
      // phone was sent none, kept logging off and said nothing (Wise Life,
      // 19 Nov 2026: an Oppo whose calls never reached Sales X-Ray). Now that
      // it lists them: the first one, as above.
      const first = after?.sims[0]?.id;
      if (after && !after.on && after.access && !log?.sims.length && first)
        await callLogSetup(true, first);
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

/**
 * The reminder's X: quiet until tomorrow, per person and workspace (Redmi QA on
 * production, 10 Nov 2026: X hid it only until the next cold start, and it sat
 * at the foot of every page again).
 */
const quietKey = (person: string, tenant: string) =>
  `sales-xray:permissions-reminder-quiet:${person}:${tenant}`;
const today = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(
    new Date(),
  );
function quietToday(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === today();
  } catch {
    return false;
  }
}
function keepQuiet(key: string) {
  try {
    window.localStorage.setItem(key, today());
  } catch {
    // Without storage the X lasts for this app open, as before.
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
  const [busy, setBusy] = useState(false);
  // Refusals per row: twice, and the screen opens Android's settings instead.
  const [tries, setTries] = useState<Readonly<Record<string, number>>>({});
  // Not now, kept on this device per person and workspace (rows that can
  // wait), and for this visit when the device can't keep it.
  const [visitLater, setVisitLater] = useState<ReadonlySet<string>>(new Set());
  // Not now for this app open only: every row, the needed ones included.
  const [skipped, setSkipped] = useState<ReadonlySet<string>>(new Set());
  // The reminder's Finish or the Calls line's Turn on: the walk again, with
  // the put-off rows, or at one screen.
  const [target, setTarget] = useState<OpenDetail | null>(null);
  const [walk, setWalk] = useState<{
    steps: WalkStep[];
    via: FlowVia;
  } | null>(null);
  const [noCallsNow, setNoCalls] = useState(false);
  const [batteryPhase, setBatteryPhase] = useState<"battery" | "autostart">(
    "battery",
  );
  const [test, setTest] = useState<TestCall | null>(null);
  const [testSkippedNow, setTestSkipped] = useState(false);
  const [note, setNote] = useState<string | null>(null);
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
  // New analysis's "Analysis minutes used up" is the card that matters there:
  // the reminder waits for it too (Redmi QA on production, 10 Nov 2026: the two
  // stacked at the foot of New analysis).
  const minutesCard = useNoticeShown("analysis-minutes-out");
  const typing = useSyncExternalStore(watchTyping, typingNow, noFullPage);
  // Away in one of Android's settings screens, and which screen sent them.
  const away = useRef(false);
  const awayStep = useRef<AskStep | null>(null);
  const asked = useRef<Ask | null>(null);

  useEffect(() => {
    const open = (event: Event) => {
      const detail = (event as CustomEvent<OpenDetail | null>).detail;
      setSkipped(new Set());
      setTarget({ step: detail?.step });
    };
    window.addEventListener(OPEN_EVENT, open);
    return () => window.removeEventListener(OPEN_EVENT, open);
  }, []);

  // Kept in Personal too, now that the folder has Not now there (Redmi QA on
  // production, 10 Nov 2026).
  const storageKey = person && tenant ? laterKey(person, tenant) : "";
  const quiet = person && tenant ? quietKey(person, tenant) : "";
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

  // "I don't make calls on this phone" and a skipped test call, per install.
  const device = status?.device ?? "";
  const noCalls =
    noCallsNow || (device !== "" && readKey(noCallsKey(device)) === "1");
  const testSkipped =
    testSkippedNow ||
    (device !== "" && readKey(testSkippedKey(device)) === "1");

  const items = useMemo(
    () =>
      status
        ? permissionItems(status, {
            organisation,
            consent: organisation ? consentFact(consent) : null,
          })
        : [],
    [status, organisation, consent],
  );
  const pending = useMemo(
    () =>
      pendingKeys(items, {
        // The reminder's Finish shows the put-off rows again.
        putOff: target ? new Set<string>() : putOff,
        skipped,
        makesCalls: !noCalls,
      }),
    [items, target, putOff, skipped, noCalls],
  );
  const tested =
    testSkipped ||
    test?.found === true ||
    (status ? recordingProven(phoneFacts(status, null)!) : false);
  const facts = useMemo(
    () =>
      status
        ? {
            pending,
            status,
            makesCalls: !noCalls,
            welcomed: readKey(WALK_WELCOMED_KEY) === "1" || target !== null,
            tested,
            privateSeen: privateDiallerSeen(),
          }
        : null,
    [pending, status, noCalls, target, tested],
  );
  const stillOpen = useCallback(
    (step: AskStep) =>
      facts !== null &&
      (step === "test_call"
        ? !facts.tested && captureReady(facts.status)
        : stepOpen(step, facts)),
    [facts],
  );
  const planned = useMemo(
    () => (facts ? walkSteps(facts, target?.step) : []),
    [facts, target],
  );
  const asksSomething = planned.some(
    (step) => isAsk(step) && step !== "test_call",
  );
  const showing =
    walk ??
    (asksSomething
      ? { steps: planned, via: (target ? "fix" : "first_run") as FlowVia }
      : null);
  // The walk's screens are fixed once it shows, so its dots don't jump; a
  // request with nothing left to ask is spent. (State kept from the render
  // before: React re-renders at once, with no effect in between.)
  if (!walk && showing) setWalk(showing);
  if (target && !walk && !asksSomething) setTarget(null);

  // Where people stop and what Android answered (the weekly friction report).
  const flow = useFlow("phone_setup", { via: showing?.via });
  const answered = useCallback(
    (after: SetupStatus | null) => {
      const ask = asked.current;
      if (!ask) return;
      asked.current = null;
      trackPrompt({
        ...ask,
        after,
        fix: showing?.via === "fix",
        ms: performance.now() - ask.at,
      });
    },
    [showing?.via],
  );

  // A row is put off: kept on this phone when it can wait, and for this app
  // open in every case, so the walk moves on.
  const putAway = useCallback(
    (keys: readonly PermissionItem[]) => {
      if (!keys.length) return;
      const lasting = keys.filter((item) => item.canWait).map(putOffKey);
      setSkipped((value) => new Set([...value, ...keys.map(putOffKey)]));
      if (lasting.length) {
        setVisitLater((value) => new Set([...value, ...lasting]));
        if (storageKey)
          writeLater(storageKey, new Set([...putOff, ...lasting]));
      }
    },
    [putOff, storageKey],
  );
  const stepItems = useCallback(
    (step: AskStep) =>
      items.filter(
        (item) => STEP_KEYS[step].includes(item.key) && pending.has(item.key),
      ),
    [items, pending],
  );

  // The battery screen is done once the seller has been to its pages: HyperOS
  // doesn't tell Android, so coming back is the seller's word, as the
  // checklist's Done was (Set up this phone asks for neither again).
  const batteryDone = useCallback(() => {
    sayBatteryDone();
    if (status?.autostartNeeded) void setupMark("autostart", true);
    setBatteryPhase("battery");
    putAway(stepItems("battery"));
  }, [status?.autostartNeeded, putAway, stepItems]);

  // Back in the app: from Android's settings or the folder picker, and, in an
  // organisation's workspace, every return, so a permission taken away shows.
  useEffect(
    () =>
      onPhoneSignal((event) => {
        if (event !== "resume" || !decided) return;
        if (!away.current && !organisation) return;
        const from = awayStep.current;
        away.current = false;
        awayStep.current = null;
        void read().then((next) => {
          if (from) answered(next);
          if (from === "battery") {
            if (batteryPhase === "battery" && next?.autostartNeeded)
              setBatteryPhase("autostart");
            else batteryDone();
          }
        });
      }),
    [read, decided, organisation, answered, batteryPhase, batteryDone],
  );

  // A test call is out: its recording is looked for every few seconds and when
  // the app comes back, until it is found or the seller has been back a while.
  const waitingFrom = test && !test.found && !test.gaveUp ? test.started : null;
  useEffect(() => {
    if (waitingFrom === null) return;
    let stopped = false;
    let giveUp: number | undefined;
    const check = async () => {
      const next = await setupStatus();
      const newest = next?.recorder?.newestMs ?? null;
      if (stopped || !next || newest === null || newest < waitingFrom) return;
      markTestCall(next.device);
      setStatus(next);
      setTest((value) => (value ? { ...value, found: true } : value));
    };
    const timer = window.setInterval(() => void check(), 4_000);
    const stop = onPhoneSignal((event) => {
      if (event !== "resume") return;
      void check();
      giveUp ??= window.setTimeout(
        () =>
          setTest((value) =>
            value && !value.found ? { ...value, gaveUp: true } : value,
          ),
        TEST_WAIT_MS,
      );
    });
    return () => {
      stopped = true;
      window.clearInterval(timer);
      window.clearTimeout(giveUp);
      stop();
    };
  }, [waitingFrom]);

  // Put off with Not now and still not done: the slim reminder names them,
  // the rows the app needs among them.
  const later = [
    ...reminders(items, putOff),
    ...items.filter(
      (item) =>
        item.required &&
        (item.state === "needed" || item.state === "blocked") &&
        skipped.has(putOffKey(item)) &&
        !putOff.has(putOffKey(item)),
    ),
  ];
  const open = Boolean(showing);
  const deciding = signedIn && inPhoneApp() && !decided;

  useEffect(() => {
    const html = document.documentElement;
    if (deciding || open) html.setAttribute(PERMISSIONS_ATTRIBUTE, "");
    else html.removeAttribute(PERMISSIONS_ATTRIBUTE);
    return () => html.removeAttribute(PERMISSIONS_ATTRIBUTE);
  }, [deciding, open]);

  // The walk is its own screen in the friction report ("setup").
  useEffect(() => {
    if (!open) return;
    const html = document.documentElement;
    html.setAttribute(SETUP_SCREEN_ATTRIBUTE, "");
    screenChanged();
    return () => {
      html.removeAttribute(SETUP_SCREEN_ATTRIBUTE);
      screenChanged();
    };
  }, [open]);

  // A put-off row stays as one slim line until it is done, or until Finish or
  // the X is tapped, once per app open (orchestrator, 3 Nov 2026: it left by
  // itself after 5 s). On Leads it is the line above the rows; elsewhere the
  // corner, which the page keeps room for. Never over the walk.
  const remind =
    open || fullPage || sheet || recordingCard || minutesCard || typing
      ? ""
      : later.map((item) => item.label).join(" · ");
  useEffect(() => {
    if (!remind || reminded.current || (quiet && quietToday(quiet))) {
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
          setSkipped(new Set());
          setTarget({});
        },
      },
      slim: true,
      pillAction: true,
      noReport: true,
      dock: true,
      timeout: 0,
      onDismiss: async () => {
        reminded.current = true;
        if (quiet) keepQuiet(quiet);
      },
    });
  }, [remind, quiet]);

  /** The walk is over: what is left waits for the next open or the reminder. */
  const close = useCallback(
    (how: "done" | "cancel") => {
      if (!walk) return;
      const left = askSteps(walk.steps).filter(
        (step) => step !== "test_call" && stillOpen(step),
      );
      // Back is Not now for what can wait (never the battery or the consent,
      // which are the seller's own words); everything left rests for this open.
      if (how === "cancel") {
        const lasting = left
          .flatMap(stepItems)
          .filter(
            (item) =>
              item.canWait &&
              item.key !== "battery" &&
              item.key !== "autoAnalysis",
          )
          .map(putOffKey);
        if (lasting.length) {
          setVisitLater((value) => new Set([...value, ...lasting]));
          if (storageKey)
            writeLater(storageKey, new Set([...putOff, ...lasting]));
        }
        flow.cancel();
      } else flow.done({ left: left.length });
      setSkipped(
        (value) =>
          new Set([
            ...value,
            ...left.flatMap(stepItems).map((item) => putOffKey(item)),
          ]),
      );
      setWalk(null);
      setTarget(null);
      setNote(null);
      setTest(null);
    },
    [walk, stillOpen, stepItems, storageKey, putOff, flow],
  );

  // Back closes the walk (Redmi QA on production, 10 Nov 2026: Back did nothing).
  useBackClose(open, () => close("cancel"));

  // A modal dialog over every page; Escape doesn't close it.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = frame.current;
    if (open && node && !node.open) node.showModal?.();
  }, [open]);

  if (!showing || !status) return null;

  const tried = (key: PermissionKey) => (tries[key] ?? 0) >= 2;
  const stateOf = (key: PermissionKey) =>
    items.find((item) => item.key === key)?.state;
  const settingsFor = (step: AskStep) =>
    step === "alerts"
      ? stateOf("notifications") === "blocked" || tried("notifications")
      : step === "calls"
        ? stateOf("phone") === "blocked" ||
          tried("phone") ||
          (pending.has("contacts") &&
            (stateOf("contacts") === "blocked" || tried("contacts")))
        : false;

  const refused = (
    next: SetupStatus | null,
    keys: readonly PermissionKey[],
  ) => {
    const after = next
      ? permissionItems(next, { organisation })
      : ([] as PermissionItem[]);
    const still = keys.filter((key) => {
      const row = after.find((item) => item.key === key);
      return row && (row.state === "needed" || row.state === "blocked");
    });
    if (still.length)
      setTries((value) => {
        const copy = { ...value };
        for (const key of still) copy[key] = (copy[key] ?? 0) + 1;
        return copy;
      });
  };

  const onAsk = async (step: AskStep) => {
    setNote(null);
    const settings = settingsFor(step);
    const prompt = WALK_PROMPT[step];
    if (prompt) asked.current = startAsk(prompt, status, settings);
    const leave = (opened: boolean) => {
      if (asked.current) asked.current.opened = opened;
      away.current = true;
      awayStep.current = step;
    };
    setBusy(true);
    try {
      switch (step) {
        case "alerts":
          if (settings) {
            leave(await setupOpen("notifications"));
            return;
          }
          await ask("notifications");
          break;
        case "calls":
          if (settings) {
            leave(await setupOpen("appSettings"));
            return;
          }
          if (pending.has("phone")) await ask("phone");
          if (pending.has("contacts")) await ask("contacts");
          if (pending.has("callLog")) await ask("callLog");
          break;
        case "recordings":
          if (status.recorder?.kind === "private") {
            markPrivateDiallerSeen();
            putAway(stepItems("recordings"));
            return;
          }
          await ask("recordings");
          break;
        case "battery": {
          const what = batteryPhase === "autostart" ? "autostart" : "battery";
          const opened = await setupOpen(what);
          if (!opened) {
            setNote(
              "That page didn't open. Find it in Sales X-Ray's app settings, then come back.",
            );
            leave(await setupOpen("appSettings"));
            return;
          }
          leave(true);
          return;
        }
        case "analyse": {
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
          break;
        }
        case "test_call":
          setTest({ started: Date.now(), found: false, gaveUp: false });
          away.current = true;
          dial(TEST_CALL_NUMBER);
          return;
      }
    } catch {
      // Android said no, or the phone didn't answer: the screen stays.
    } finally {
      setBusy(false);
    }
    const next = await read();
    answered(next);
    if (step === "alerts") refused(next, ["notifications"]);
    if (step === "calls") refused(next, ["phone", "contacts"]);
    if (step === "recordings" && next && !next.folderPicked)
      setNote(
        "No folder chosen yet. Tap Choose folder and pick the one above.",
      );
  };

  const onLater = (step: AskStep) => {
    setNote(null);
    try {
      track("sx.flow", {
        flow: "phone_setup",
        outcome: "skip",
        step: WALK_TELEMETRY[step],
        via: showing.via,
        left: askSteps(showing.steps).filter((each) => stillOpen(each)).length,
      });
    } catch {
      // Telemetry never breaks setup.
    }
    if (step === "test_call") {
      writeKey(testSkippedKey(status.device), "1");
      setTestSkipped(true);
      setTest(null);
      return;
    }
    if (step === "battery") setBatteryPhase("battery");
    // The capture setup's own record of not now: it asks again on its own days.
    if (step === "analyse")
      void recordCaptureSetup({ outcome: "declined" }).catch(() => null);
    putAway(stepItems(step));
  };

  const laterLabel = (step: AskStep) =>
    step === "test_call"
      ? "Skip the test call"
      : `Not now: ${stepItems(step)
          .map((item) => item.label)
          .join(" and ")}`;

  const notice = consent?.view.notice;
  return (
    <dialog
      ref={frame}
      className={`${styles.page} ${walkStyles.walk}`}
      data-permissions=""
      onCancel={(event) => event.preventDefault()}
    >
      <SetupWalk
        steps={showing.steps}
        stillOpen={stillOpen}
        status={status}
        settingsFor={settingsFor}
        questions={callQuestions(pending, status)}
        batteryPhase={batteryPhase}
        test={!test ? "ready" : test.gaveUp ? "missing" : "waiting"}
        consent={
          notice
            ? {
                words:
                  items.find((item) => item.key === "autoAnalysis")?.why ??
                  notice.text,
                terms: consent?.policy.privacy_details || undefined,
              }
            : null
        }
        noCalls={noCalls}
        busy={busy}
        note={note}
        laterLabel={laterLabel}
        onAsk={(step) => void onAsk(step)}
        onLater={onLater}
        onNoCalls={() => {
          writeKey(noCallsKey(status.device), "1");
          setNoCalls(true);
          setWalk((value) =>
            value
              ? {
                  ...value,
                  steps: value.steps.filter(
                    (step) =>
                      !isAsk(step) ||
                      !["calls", "recordings", "battery", "test_call"].includes(
                        step,
                      ),
                  ),
                }
              : value,
          );
        }}
        onShown={(step, index, total) =>
          flow.step(WALK_TELEMETRY[step], index, total)
        }
        onEnd={() => close("done")}
      />
    </dialog>
  );
}
