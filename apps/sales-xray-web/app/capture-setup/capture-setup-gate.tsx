"use client";

/**
 * Call capture setup before Home, Leads and Calls (owner, 30 Oct 2026: "kind of
 * compulsory before moving into the app ... all our old as well as new users").
 *
 * Once per signed-in person and workspace, after the Terms card and Home's first
 * run, it asks the server and (in the phone app) the phone where things stand,
 * then opens the flow over those pages while it is required (capture-setup-
 * rules.ts). Settings and Team stay open. If the check itself fails, nothing
 * opens: the app never locks a seller out on a failed read. Settings can open
 * it again any time (openCaptureSetup), never required then.
 *
 * After a workspace switch (persona QA ph2-15, 1 Nov 2026) a phone that finished
 * in another workspace asks only for this one's consent, or nothing: its Team
 * learns of the phone by itself. The gate always offers to switch back.
 *
 * A phone is done only with its recordings working (orchestrator, 1 Nov 2026:
 * one finished with no folder and was never asked again). Without them the
 * recording check opens again at the next open, a day after a Not now.
 */

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { requestWorkspace } from "../call-ownership";

import {
  autoCaptureStatus,
  inPhoneApp,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import {
  readCaptureSetup,
  recordCaptureSetup,
  type CaptureSetup,
} from "./capture-setup-client";
import {
  CAPTURE_SETUP_ATTRIBUTE,
  finishedPhone,
  isGatedRoute,
  markPersonalSeen,
  personalSeen,
  phoneDone,
  phoneDoneElsewhere,
  phoneFacts,
  phoneReady,
  phoneTried,
  recordingsLive,
  setupRequired,
  type CaptureStep,
} from "./capture-setup-rules";
import { PERMISSIONS_ATTRIBUTE } from "./permissions-rules";

// The flow loads when it opens: most starts never show it.
const CaptureSetupFlow = dynamic(
  () =>
    import("./capture-setup-flow").then((module) => module.CaptureSetupFlow),
  { ssr: false },
);

const OPEN_EVENT = "sx-capture-setup-open";
const CONSENT_ATTRIBUTE = "data-sx-consent";
const READ_TIMEOUT_MS = 10_000;

/** Opens the setup over the page (Settings, Calls), never required; at a step
    when a fix asks for one (the no-recording line, competitor teardown #13). */
export function openCaptureSetup(step?: CaptureStep) {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: step ?? null }));
}

const SEEN_KEY = (person: string) => `sx-workspaces-seen:${person}`;
type Seen = { current: string | null; previous: string | null };

function seen(person: string): Seen | null {
  try {
    const kept: unknown = JSON.parse(
      window.localStorage.getItem(SEEN_KEY(person)) ?? "null",
    );
    if (!kept || typeof kept !== "object") return null;
    const read = (value: unknown) => (typeof value === "string" ? value : null);
    return {
      current: "current" in kept ? read(kept.current) : null,
      previous: "previous" in kept ? read(kept.previous) : null,
    };
  } catch {
    return null;
  }
}

/** The workspace before this one, kept on this phone across restarts. */
export function previousWorkspace(
  person: string,
  tenant: string,
): string | null {
  const kept = seen(person);
  if (!kept) return null;
  return kept.current === tenant ? kept.previous : kept.current;
}

/** Remembers the workspace now open, and the one before it. */
export function rememberWorkspace(person: string, tenant: string) {
  const kept = seen(person);
  if (kept?.current === tenant) return;
  try {
    window.localStorage.setItem(
      SEEN_KEY(person),
      JSON.stringify({ current: tenant, previous: kept?.current ?? null }),
    );
  } catch {
    // Private storage off: Switch back shows only within this run.
  }
}

type Decision = {
  key: string;
  setup: CaptureSetup;
  status: SetupStatus | null;
  /** An organisation's seller, on Home, Leads and Calls. */
  required: boolean;
  /** A personal workspace, once per phone; or asked for from Settings. */
  offer: boolean;
  manual: boolean;
};

export function CaptureSetupGate() {
  const access = useWorkspaceAccess();
  const pathname = usePathname();
  const context =
    access?.authenticated === true && access.status === "ready"
      ? access.context
      : null;
  const personId = context?.personId ?? "";
  const tenantId = context?.tenantId ?? "";
  const key = context ? `${personId}:${tenantId}:${context.sessionId}` : "";
  const organisation =
    access?.workspaces?.find((item) => item.tenant_id === tenantId)?.name ??
    null;
  const [decision, setDecision] = useState<Decision | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [asked, setAsked] = useState(0);
  const [startAt, setStartAt] = useState<CaptureStep | undefined>();

  // Where the seller came from, for "Switch back to …" (ph2-15).
  useEffect(() => {
    if (personId && tenantId) rememberWorkspace(personId, tenantId);
  }, [personId, tenantId]);

  // Asked for from Settings: read again, then open, never required.
  useEffect(() => {
    const open = (event: Event) => {
      setStartAt(
        (event as CustomEvent<CaptureStep | null>).detail ?? undefined,
      );
      setAsked((value) => value + 1);
    };
    window.addEventListener(OPEN_EVENT, open);
    return () => window.removeEventListener(OPEN_EVENT, open);
  }, []);

  useEffect(() => {
    if (!key) return;
    const manual = asked > 0;
    let stopped = false;
    let started = false;
    // The time limit starts with the read, not with the page: a seller can spend
    // minutes on the screens that go first (Redmi, 31 Oct 2026: a fresh install
    // never saw the setup after the permissions checklist).
    const controller = new AbortController();
    let timer: number | undefined;
    const html = document.documentElement;
    // The Terms card, Home's first run and the permissions checklist go first.
    const waiting = () =>
      !manual &&
      (html.hasAttribute(CONSENT_ATTRIBUTE) ||
        html.hasAttribute(FIRST_RUN_ATTRIBUTE) ||
        html.hasAttribute(PERMISSIONS_ATTRIBUTE));
    const start = async () => {
      if (stopped || started || waiting()) return;
      started = true;
      timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
      try {
        const app = inPhoneApp();
        const [setup, status, capture] = await Promise.all([
          readCaptureSetup(controller.signal),
          app ? setupStatus() : Promise.resolve(null),
          app ? autoCaptureStatus() : Promise.resolve(null),
        ]);
        if (stopped) return;
        const facts = phoneFacts(status, capture);
        const required = setupRequired(setup, facts, Date.now());
        // Agreed here, and nothing to ask: this workspace's Team learns of the
        // phone by itself when it finished in another workspace (ph2-15), or
        // when it went through here without recordings and they work now (a
        // call's recording was found; orchestrator, 1 Nov 2026).
        const quiet =
          !manual &&
          !required &&
          facts &&
          setup.required &&
          setup.workspace === "organisation" &&
          setup.consent === "on" &&
          setup.profile_complete !== false &&
          facts.captureSupported
            ? facts
            : null;
        const finished = !quiet
          ? null
          : phoneDoneElsewhere(setup, quiet) && recordingsLive(quiet)
            ? finishedPhone(quiet, true)
            : !phoneDone(setup, quiet) &&
                phoneTried(setup, quiet) &&
                phoneReady(setup, quiet)
              ? finishedPhone(quiet)
              : null;
        if (finished)
          void recordCaptureSetup({
            outcome: "completed",
            phone: finished,
          }).catch(() => undefined);
        setDecision({
          key,
          setup,
          status,
          required: required && !manual,
          offer:
            manual ||
            (!required &&
              setup.workspace === "personal" &&
              app &&
              facts?.captureSupported === true &&
              !personalSeen(personId, tenantId)),
          manual,
        });
      } catch {
        if (!stopped) setFailed(key);
      } finally {
        window.clearTimeout(timer);
      }
    };
    void start();
    const watch = new MutationObserver(() => void start());
    watch.observe(html, {
      attributes: true,
      attributeFilter: [
        CONSENT_ATTRIBUTE,
        FIRST_RUN_ATTRIBUTE,
        PERMISSIONS_ATTRIBUTE,
      ],
    });
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
      watch.disconnect();
    };
  }, [key, personId, tenantId, asked]);

  const current = decision?.key === key ? decision : null;
  const deciding = Boolean(key) && !current && failed !== key;
  const open = Boolean(
    current &&
      (current.manual ||
        ((current.required || current.offer) && isGatedRoute(pathname))),
  );

  // "Set up this phone" waits while this decides and while it is open.
  useEffect(() => {
    const html = document.documentElement;
    if (deciding || open) html.setAttribute(CAPTURE_SETUP_ATTRIBUTE, "");
    else html.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
    return () => html.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
  }, [deciding, open]);

  const settle = useCallback(
    (setup: CaptureSetup | null) => {
      if (current?.setup.workspace === "personal")
        markPersonalSeen(personId, tenantId);
      setDecision((value) =>
        value
          ? {
              ...value,
              setup: setup ?? value.setup,
              required: false,
              offer: false,
              manual: false,
            }
          : value,
      );
    },
    [current, personId, tenantId],
  );
  const close = useCallback(() => settle(null), [settle]);
  if (!open || !current) return null;
  const previous = previousWorkspace(personId, tenantId);
  const back =
    previous && previous !== tenantId
      ? access?.workspaces?.find((item) => item.tenant_id === previous)
      : undefined;
  return (
    <CaptureSetupFlow
      setup={current.setup}
      phone={inPhoneApp() ? { status: current.status } : null}
      inApp={inPhoneApp()}
      required={current.required}
      organisation={
        current.setup.workspace === "organisation" ? organisation : null
      }
      onFinish={settle}
      onDeclined={settle}
      onClose={close}
      startAt={current.manual ? startAt : undefined}
      switchBack={
        back
          ? {
              name: back.name,
              run: () => requestWorkspace(back.tenant_id),
            }
          : null
      }
    />
  );
}
