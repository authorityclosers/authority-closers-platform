"use client";

import { Settings, X } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

const preferenceKey = "sales-xray:show-live-data-banner";
const preferenceEvent = "sales-xray:banner-preference";
const SettingsContext = createContext<(() => void) | null>(null);
let fallbackVisible = false;

function readPreference() {
  try {
    return window.localStorage.getItem(preferenceKey) === "true";
  } catch {
    return fallbackVisible;
  }
}

function setPreference(visible: boolean) {
  fallbackVisible = visible;
  try {
    window.localStorage.setItem(preferenceKey, String(visible));
  } catch {
    // The control still works when browser storage is unavailable.
  }
  window.dispatchEvent(new Event(preferenceEvent));
}

function subscribe(onChange: () => void) {
  window.addEventListener(preferenceEvent, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(preferenceEvent, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function LocalSettingsButton({ className }: { className?: string }) {
  const openSettings = useContext(SettingsContext);
  if (!openSettings) return null;
  return (
    <button type="button" className={className} onClick={openSettings} title="Settings" aria-haspopup="dialog">
      <Settings size={18} aria-hidden="true" />
      <span>Settings</span>
    </button>
  );
}

function LiveDataDetails() {
  return (
    <>
      <strong>Local development · live AC data</strong>
      <span>
        Sign in normally. This browser reads your production account, and any
        explicit save, delete, workspace, or analysis action affects real data.
      </span>
      <a
        href="https://admin.authorityclosers.com/sales-xray/settings"
        target="_blank"
        rel="noreferrer"
      >
        Production provider settings · authorized admins
      </a>
    </>
  );
}

export function LiveDataBanner({ children }: { children?: ReactNode }) {
  const visible = useSyncExternalStore(subscribe, readPreference, () => false);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.defaultPrevented || event.repeat || event.isComposing ||
        !event.ctrlKey || !event.altKey || event.shiftKey || event.metaKey ||
        event.key.toLowerCase() !== "b" ||
        (target instanceof HTMLElement &&
          (target.closest("input, textarea, select") || target.isContentEditable))
      ) return;
      event.preventDefault();
      setPreference(!readPreference());
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);

  return (
    <SettingsContext.Provider value={() => dialog.current?.showModal()}>
      {visible ? (
        <aside className="sales-xray-live-data-banner" role="note">
          <LiveDataDetails />
          <button type="button" onClick={() => setPreference(false)} aria-label="Hide live data banner" title="Hide banner (Ctrl+Alt+B)">
            <X size={16} aria-hidden="true" />
          </button>
        </aside>
      ) : null}
      {children}
      <dialog ref={dialog} className="sales-xray-local-settings" aria-labelledby="local-settings-title">
        <header>
          <h2 id="local-settings-title">Settings</h2>
          <button type="button" aria-label="Close settings" onClick={() => dialog.current?.close()}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <section aria-label="Development environment" className="sales-xray-local-settings-details">
          <LiveDataDetails />
        </section>
        <label className="sales-xray-local-settings-toggle">
          <span>Show development banner<small>Remembered in this browser.</small></span>
          <input type="checkbox" checked={visible} onChange={(event) => setPreference(event.target.checked)} aria-keyshortcuts="Control+Alt+B" />
        </label>
        <p className="sales-xray-local-settings-shortcut">Toggle the banner with <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>B</kbd>.</p>
      </dialog>
    </SettingsContext.Provider>
  );
}
