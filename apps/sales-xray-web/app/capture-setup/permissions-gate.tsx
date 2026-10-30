"use client";

/**
 * The permissions checklist right after sign-in, in the phone app (owner, 30
 * Oct 2026, fix 5: "the app cannot be used until all are granted"). One screen:
 * call log, phone, contacts, notifications and the recordings folder, each with
 * Allow, or Open settings once Android won't ask again. It covers every page
 * until all that this app build can grant are granted; items the build can't
 * ask for say so and never lock anyone out (permissions-rules.ts). There is no
 * Not now here; agreeing to call capture stays its own choice (capture setup).
 *
 * It waits for the Terms card and Home's first run, and call capture setup and
 * "Set up this phone" wait for it. Nothing shows in a browser or an app too
 * old to say what it has.
 */

import {
  Bell,
  CheckCircle2,
  Contact,
  FolderOpen,
  History,
  Phone,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { PLAY_LISTING } from "../app-compatibility-provider";
import styles from "../leads/phone-onboarding.module.css";
import {
  askCallAccess,
  askContacts,
  askNotifications,
  callLogSetup,
  callLogStatus,
  inPhoneApp,
  onPhoneSignal,
  pickRecordingsFolder,
  setupOpen,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import { Button } from "../ui/kit";
import { FIRST_RUN_ATTRIBUTE } from "../welcome/setup-state";
import { useWorkspaceAccess } from "../workspace-access";
import own from "./capture-setup.module.css";
import {
  PERMISSIONS_ATTRIBUTE,
  permissionItems,
  permissionsMissing,
  waitsFor,
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
};

const CONSENT_ATTRIBUTE = "data-sx-consent";

/** The checklist itself, for the gate and the review fixture. */
export function PermissionsChecklist({
  items,
  busy,
  tried,
  onAllow,
  onSettings,
}: {
  items: readonly PermissionItem[];
  busy: PermissionKey | null;
  /** Asked once and still not granted: Android may not ask again. */
  tried: ReadonlySet<PermissionKey>;
  onAllow: (key: PermissionKey) => void;
  onSettings: (key: PermissionKey) => void;
}) {
  const titleId = useId();
  const left = items.filter(waitsFor).length;
  return (
    <div className={own.permissions} aria-labelledby={titleId} role="group">
      <h1 id={titleId} className={styles.title}>
        {named("Allow what Sales X-Ray needs")}
      </h1>
      <p className={styles.line}>
        {left
          ? `Sales X-Ray works once these are allowed. ${left === 1 ? "1 left." : `${left} left.`}`
          : "All set. Sales X-Ray is ready."}
      </p>
      <ul className={own.grants}>
        {items.map((item) => {
          const Icon = ICONS[item.key];
          const settings =
            item.state === "blocked" ||
            (item.state === "needed" && tried.has(item.key));
          return (
            <li key={item.key} data-state={item.state}>
              <span className={own.grantIcon}>
                {item.state === "granted" ? (
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
                        : named(item.why)}
                </small>
              </span>
              {item.state === "granted" ? (
                <span className={own.granted}>Allowed</span>
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
                <Button
                  variant={settings ? "ghost" : "primary"}
                  disabled={busy !== null}
                  aria-busy={busy === item.key || undefined}
                  aria-label={`${settings ? "Open settings for" : "Allow"} ${item.label}`}
                  onClick={() =>
                    settings ? onSettings(item.key) : onAllow(item.key)
                  }
                >
                  {settings ? "Open settings" : "Allow"}
                </Button>
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
  }
}

export function PermissionsGate() {
  const access = useWorkspaceAccess();
  const signedIn = access?.authenticated === true && access.status === "ready";
  const tenant = access?.context?.tenantId;
  // Call logging works only in an organisation's workspace; elsewhere it never blocks.
  const organisation =
    access?.workspaces?.find((item) => item.tenant_id === tenant)?.kind ===
    "organisation";
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [decided, setDecided] = useState(false);
  const [busy, setBusy] = useState<PermissionKey | null>(null);
  const [tried, setTried] = useState<ReadonlySet<PermissionKey>>(new Set());
  const away = useRef(false);

  const read = useCallback(async () => {
    const next = await setupStatus();
    setStatus(next);
    setDecided(true);
    return next;
  }, []);

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
        const next = await setupStatus();
        if (stopped) return;
        setStatus(next);
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
  }, [signedIn]);

  // Back from Android's settings or the folder picker: read again.
  useEffect(
    () =>
      onPhoneSignal((event) => {
        if (event !== "resume" || !away.current) return;
        away.current = false;
        void read();
      }),
    [read],
  );

  const items = status ? permissionItems(status, { organisation }) : [];
  const open = Boolean(status) && permissionsMissing(items);
  const deciding = signedIn && inPhoneApp() && !decided;

  useEffect(() => {
    const html = document.documentElement;
    if (deciding || open) html.setAttribute(PERMISSIONS_ATTRIBUTE, "");
    else html.removeAttribute(PERMISSIONS_ATTRIBUTE);
    return () => html.removeAttribute(PERMISSIONS_ATTRIBUTE);
  }, [deciding, open]);

  // A modal dialog over every page; Escape and Back don't close it.
  const frame = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = frame.current;
    if (open && node && !node.open) node.showModal?.();
  }, [open]);

  if (!open) return null;
  const allow = async (key: PermissionKey) => {
    setBusy(key);
    try {
      await ask(key);
    } catch {
      // Android said no, or the phone didn't answer: Open settings next.
    }
    const next = await read();
    setBusy(null);
    const still = next
      ? permissionItems(next, { organisation }).find((item) => item.key === key)
      : undefined;
    if (still && still.state !== "granted")
      setTried((value) => new Set(value).add(key));
  };
  const settings = (key: PermissionKey) => {
    if (key === "recordings") {
      void allow(key);
      return;
    }
    away.current = true;
    void setupOpen(key === "notifications" ? "notifications" : "appSettings");
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
          onAllow={(key) => void allow(key)}
          onSettings={settings}
        />
      </div>
    </dialog>
  );
}
