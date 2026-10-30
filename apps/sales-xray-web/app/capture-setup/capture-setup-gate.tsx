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
 */

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  autoCaptureStatus,
  inPhoneApp,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import { readCaptureSetup, type CaptureSetup } from "./capture-setup-client";
import {
  CAPTURE_SETUP_ATTRIBUTE,
  isGatedRoute,
  markPersonalSeen,
  personalSeen,
  phoneFacts,
  setupRequired,
} from "./capture-setup-rules";

// The flow loads when it opens: most starts never show it.
const CaptureSetupFlow = dynamic(
  () =>
    import("./capture-setup-flow").then((module) => module.CaptureSetupFlow),
  { ssr: false },
);

const OPEN_EVENT = "sx-capture-setup-open";
const CONSENT_ATTRIBUTE = "data-sx-consent";
const READ_TIMEOUT_MS = 10_000;

/** Opens the setup over the page (Settings, Calls), never required. */
export function openCaptureSetup() {
  window.dispatchEvent(new Event(OPEN_EVENT));
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

  // Asked for from Settings: read again, then open, never required.
  useEffect(() => {
    const open = () => setAsked((value) => value + 1);
    window.addEventListener(OPEN_EVENT, open);
    return () => window.removeEventListener(OPEN_EVENT, open);
  }, []);

  useEffect(() => {
    if (!key) return;
    const manual = asked > 0;
    let stopped = false;
    let started = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
    const html = document.documentElement;
    // The Terms card and Home's first run go first.
    const waiting = () =>
      !manual &&
      (html.hasAttribute(CONSENT_ATTRIBUTE) ||
        html.hasAttribute(FIRST_RUN_ATTRIBUTE));
    const start = async () => {
      if (stopped || started || waiting()) return;
      started = true;
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
      attributeFilter: [CONSENT_ATTRIBUTE, FIRST_RUN_ATTRIBUTE],
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
    />
  );
}
