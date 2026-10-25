"use client";

/**
 * Alerts by urgency (owner program, 25 Oct 2026, item 3). Work that needs the
 * seller, never app problems (those stay corner cards, notice-center.tsx):
 * - normal: a banner at the top of the screen, its edge glowing softly a few
 *   times, a light haptic; it leaves by itself after a few seconds;
 * - urgent: a larger card in the middle with the one thing to do, in the
 *   urgent colour with the urgent haptic; it stays until done or put off.
 * One of each at a time: a newer alert of a level replaces the older one.
 */

import { BellRing, Siren, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useSyncExternalStore } from "react";

import styles from "./alerts.module.css";
import { useBackClose } from "./back-close";
import { haptic } from "./haptics";

export type AlertLevel = "normal" | "urgent";

export type AppAlert = Readonly<{
  id: string;
  level: AlertLevel;
  title: string;
  message?: string;
  /** The one thing to do: a step here, or a page to open. */
  action?: Readonly<{ label: string; run?: () => void; href?: string }>;
  /** A normal alert leaves after this many ms (8 s); an urgent one stays. */
  timeout?: number;
  /** The urgent card's way to put it off ("Later"). */
  laterLabel?: string;
}>;

type Shown = Readonly<{ banner: AppAlert | null; urgent: AppAlert | null }>;

const NONE: Shown = { banner: null, urgent: null };
const BANNER_MS = 8_000;

let shown: Shown = NONE;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

/** Raise an alert; the same id again replaces it without a second buzz. */
export function raiseAlert(alert: AppAlert) {
  const slot = alert.level === "urgent" ? "urgent" : "banner";
  const again = shown[slot]?.id === alert.id;
  shown = { ...shown, [slot]: alert };
  emit();
  if (!again) haptic(alert.level === "urgent" ? "urgent" : "tap");
}

export function clearAlert(id: string) {
  const next = {
    banner: shown.banner?.id === id ? null : shown.banner,
    urgent: shown.urgent?.id === id ? null : shown.urgent,
  };
  if (next.banner === shown.banner && next.urgent === shown.urgent) return;
  shown = next;
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function Act({ alert, className }: { alert: AppAlert; className: string }) {
  const { action } = alert;
  if (!action) return null;
  const done = () => {
    action.run?.();
    clearAlert(alert.id);
  };
  return action.href ? (
    <Link className={className} href={action.href} onClick={done}>
      {action.label}
    </Link>
  ) : (
    <button type="button" className={className} onClick={done}>
      {action.label}
    </button>
  );
}

function Banner({ alert }: { alert: AppAlert }) {
  const held = useRef(false);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!held.current) clearAlert(alert.id);
    }, alert.timeout ?? BANNER_MS);
    return () => window.clearInterval(timer);
  }, [alert.id, alert.timeout]);
  const hold = () => {
    held.current = true;
  };
  const free = () => {
    held.current = false;
  };
  return (
    <div
      className={styles.banner}
      role="status"
      data-capture-skip=""
      onPointerEnter={hold}
      onPointerLeave={free}
      onFocus={hold}
      onBlur={free}
    >
      <span className={styles.bannerIcon} aria-hidden="true">
        <BellRing size={18} />
      </span>
      <div className={styles.words}>
        <strong>{alert.title}</strong>
        {alert.message ? <span>{alert.message}</span> : null}
      </div>
      <Act alert={alert} className={styles.bannerAction} />
      <button
        type="button"
        className={styles.close}
        aria-label="Close"
        onClick={() => clearAlert(alert.id)}
      >
        <X size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

function Urgent({ alert }: { alert: AppAlert }) {
  const title = useId();
  const words = useId();
  const first = useRef<HTMLDivElement>(null);
  const later = () => clearAlert(alert.id);
  // Back, Escape and the scrim put it off, as every overlay closes.
  useBackClose(true, later);
  useEffect(() => {
    first.current?.querySelector<HTMLElement>("a, button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") later();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert.id]);
  return (
    <div className={styles.urgentLayer} data-capture-skip="">
      <div className={styles.scrim} aria-hidden="true" onClick={later} />
      <div
        className={styles.urgent}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={title}
        aria-describedby={alert.message ? words : undefined}
      >
        <span className={styles.urgentIcon} aria-hidden="true">
          <Siren size={28} />
        </span>
        <h2 id={title} className={styles.urgentTitle}>
          {alert.title}
        </h2>
        {alert.message ? (
          <p id={words} className={styles.urgentWords}>
            {alert.message}
          </p>
        ) : null}
        <div className={styles.urgentActions} ref={first}>
          <Act alert={alert} className={styles.primary} />
          <button type="button" className={styles.later} onClick={later}>
            {alert.laterLabel ?? "Later"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Where alerts appear; mounted once, beside the corner cards. */
export function AlertHost() {
  const now = useSyncExternalStore(
    subscribe,
    () => shown,
    () => NONE,
  );
  return (
    <>
      {now.banner ? <Banner key={now.banner.id} alert={now.banner} /> : null}
      {now.urgent ? <Urgent key={now.urgent.id} alert={now.urgent} /> : null}
    </>
  );
}
