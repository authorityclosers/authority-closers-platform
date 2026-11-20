"use client";

import { X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { CALLS_PAGE_NAME } from "../calls-page-name";
import { track } from "../telemetry";
import { useAppRouter } from "./app-router";
import { OPEN_ADD_EVENT } from "./shell-store";
import styles from "./desktop-keys.module.css";

/**
 * Keys on a computer (owner, 20 Nov 2026: "Learn how Vitals OS is so great on
 * PC"; board ~/orch/boards/sx-desktop, option B). Vitals teaches its keys on
 * screen; Sales X-Ray had Ctrl K and [ only. Now, on a computer with a mouse,
 * signed in, and when nobody is typing and nothing is open:
 *   /        search (the same command bar as Ctrl K)
 *   N        Add a lead, a call or a task (the shell's + sheet)
 *   G then H, L, C, M, P or S   go to Home, Leads, Calls, Chats, Prospects, Settings
 *   ?        this list
 * Each use is counted (sx.feature_used key_*). Phones never see any of it.
 */

export const DESKTOP_KEYS_QUERY = "(min-width: 1024px) and (hover: hover)";

export const GO_PLACES = [
  { key: "h", label: "Home", href: "/dashboard" },
  { key: "l", label: "Leads", href: "/leads" },
  { key: "c", label: CALLS_PAGE_NAME, href: "/analysis/calls" },
  { key: "m", label: "Chats", href: "/chats" },
  { key: "p", label: "Prospects", href: "/prospects" },
  { key: "s", label: "Settings", href: "/settings" },
] as const;

/** Where G then this key goes, or null. */
export function goPlace(key: string) {
  const lower = key.toLowerCase();
  return GO_PLACES.find((place) => place.key === lower) ?? null;
}

/** How long G waits for its second key. */
const SEQUENCE_MS = 1500;

/** Someone is typing, or a sheet, menu or dialog is up: single keys stay theirs. */
export function keysBusy(target: EventTarget | null): boolean {
  const element = target instanceof Element ? target : null;
  if (
    element?.closest(
      'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="menu"], [role="listbox"]',
    )
  )
    return true;
  return Boolean(
    document.querySelector(
      'dialog[open], [role="dialog"]:not([data-desktop-keys]), [role="alertdialog"], [aria-modal="true"]:not([data-desktop-keys])',
    ),
  );
}

/** The signed-in shell is on screen (not a sign-in page or a report export). */
function shellSignedIn() {
  return Boolean(
    document.querySelector('[data-lightbox-shell][data-authenticated="true"]'),
  );
}

function onComputer() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(DESKTOP_KEYS_QUERY).matches
  );
}

function used(feature: string) {
  track("sx.feature_used", { feature: `key_${feature}` });
}

/** Opens the shell's command bar the way Ctrl K does. */
function openSearch() {
  window.dispatchEvent(
    new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }),
  );
}

function searchKeys() {
  return typeof navigator !== "undefined" &&
    /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
    ? ["⌘", "K"]
    : ["Ctrl", "K"];
}

export function DesktopKeys() {
  const router = useAppRouter();
  const [open, setOpen] = useState(false);
  const goPending = useRef<number | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  const go = useCallback(
    (href: string) => {
      if (router) router.push(href);
      else window.location.assign(href);
    },
    [router],
  );

  const close = useCallback(() => {
    setOpen(false);
    returnTo.current?.focus?.();
    returnTo.current = null;
  }, []);

  useEffect(() => {
    const clearGo = () => {
      if (goPending.current !== null) window.clearTimeout(goPending.current);
      goPending.current = null;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!onComputer() || !shellSignedIn()) return;
      // The list itself is open: Esc closes it; nothing else fires behind it.
      if (document.querySelector("[data-desktop-keys]")) return;
      if (keysBusy(event.target)) {
        clearGo();
        return;
      }
      const key = event.key;
      if (goPending.current !== null) {
        clearGo();
        const place = goPlace(key);
        if (place) {
          event.preventDefault();
          used(`go_${place.key}`);
          go(place.href);
        }
        return;
      }
      if (key === "?") {
        event.preventDefault();
        returnTo.current =
          document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
        used("help");
        setOpen(true);
      } else if (key === "/") {
        event.preventDefault();
        used("search");
        openSearch();
      } else if (key === "n" || key === "N") {
        event.preventDefault();
        used("add");
        window.dispatchEvent(new Event(OPEN_ADD_EVENT));
      } else if (key === "g" || key === "G") {
        goPending.current = window.setTimeout(clearGo, SEQUENCE_MS);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      clearGo();
    };
  }, [go]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  if (!open) return null;
  const rows: { keys: string[][]; what: string }[] = [
    { keys: [searchKeys(), ["/"]], what: "Search places, leads and calls" },
    { keys: [["N"]], what: "Add a lead, a call or a task" },
    ...GO_PLACES.map((place) => ({
      keys: [["G", place.key.toUpperCase()]],
      what: `Go to ${place.label}`,
    })),
    { keys: [["["]], what: "Show or hide the side panel" },
    { keys: [["?"]], what: "Show these keys" },
    { keys: [["Esc"]], what: "Close a sheet or this list" },
  ];
  return (
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby="desktop-keys-title"
        data-desktop-keys=""
      >
        <div className={styles.head}>
          <h2 id="desktop-keys-title">Keyboard shortcuts</h2>
          <button
            ref={closeRef}
            type="button"
            className={styles.close}
            onClick={close}
            aria-label="Close keyboard shortcuts"
            data-sx-feature="keys_sheet_close"
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <ul className={styles.list}>
          {rows.map((row) => (
            <li key={row.what} className={styles.row}>
              <span>{row.what}</span>
              <span className={styles.keys}>
                {row.keys.map((combo, index) => (
                  <span key={combo.join("+")} className={styles.combo}>
                    {index > 0 ? <span className={styles.or}>or</span> : null}
                    {combo.map((cap, capIndex) => (
                      <span key={cap} className={styles.combo}>
                        {capIndex > 0 && combo[0] === "G" ? (
                          <span className={styles.or}>then</span>
                        ) : null}
                        <kbd>{cap}</kbd>
                      </span>
                    ))}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
        <p className={styles.foot}>
          Keys work when you are not typing and nothing else is open.
        </p>
      </div>
    </div>
  );
}
