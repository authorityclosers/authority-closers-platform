"use client";

import { ShieldAlert, X } from "lucide-react";
import { useSyncExternalStore } from "react";

export const DEV_STAGING_NOTICE_STORAGE_KEY = "ac-dev-staging-notice-hidden";

export function getSessionStorage(): Storage | null {
  try {
    if (typeof window !== "undefined" && window.sessionStorage) {
      return window.sessionStorage;
    }
  } catch {}
  try {
    if (typeof sessionStorage !== "undefined") {
      return sessionStorage;
    }
  } catch {}
  return null;
}

export function isNoticeDismissed(
  storage: Storage | null = getSessionStorage(),
): boolean {
  try {
    if (!storage) return false;
    return storage.getItem(DEV_STAGING_NOTICE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setNoticeDismissed(
  dismissed: boolean,
  storage: Storage | null = getSessionStorage(),
): boolean {
  try {
    if (!storage) return false;
    if (dismissed) {
      storage.setItem(DEV_STAGING_NOTICE_STORAGE_KEY, "true");
    } else {
      storage.removeItem(DEV_STAGING_NOTICE_STORAGE_KEY);
    }
    return true;
  } catch {
    return false;
  }
}

let fallbackHidden = false;
const noticeListeners = new Set<() => void>();

function noticeSnapshot(): boolean {
  const storage = getSessionStorage();
  if (!storage) return fallbackHidden;
  try {
    return storage.getItem(DEV_STAGING_NOTICE_STORAGE_KEY) === "true";
  } catch {
    return fallbackHidden;
  }
}

function publishNoticeState(hidden: boolean): void {
  fallbackHidden = hidden;
  setNoticeDismissed(hidden);
  for (const listener of noticeListeners) listener();
}

export function toggleDevNotice(event: KeyboardEvent): boolean {
  if (!isDevNoticeToggleShortcut(event)) return false;
  event.preventDefault();
  publishNoticeState(!noticeSnapshot());
  return true;
}

function subscribeToNotice(listener: () => void): () => void {
  noticeListeners.add(listener);
  const handleKeyDown = (event: KeyboardEvent) => {
    toggleDevNotice(event);
  };
  window.addEventListener("keydown", handleKeyDown, { capture: true });
  return () => {
    noticeListeners.delete(listener);
    window.removeEventListener("keydown", handleKeyDown, { capture: true });
  };
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as HTMLElement;
  if (typeof element.tagName !== "string") return false;
  const tag = element.tagName.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  if (element.isContentEditable) {
    return true;
  }
  if (typeof element.getAttribute === "function") {
    const role = element.getAttribute("role");
    if (role === "textbox" || role === "searchbox" || role === "combobox") {
      return true;
    }
  }
  return false;
}

export function isDevNoticeToggleShortcut(event: KeyboardEvent): boolean {
  if (event.repeat) {
    return false;
  }
  if (isEditableTarget(event.target)) {
    return false;
  }
  const isAlt = event.altKey;
  const isShift = event.shiftKey;
  const isModifierMatch = isAlt && isShift && !event.ctrlKey && !event.metaKey;
  if (!isModifierMatch) {
    return false;
  }
  const key = event.key;
  const code = event.code;
  return (
    key === "d" || key === "D" || key === "∂" || key === "Î" || code === "KeyD"
  );
}

export function DevStagingBridgeNoticeClient() {
  const hidden = useSyncExternalStore(
    subscribeToNotice,
    noticeSnapshot,
    () => false,
  );

  if (hidden) {
    return null;
  }

  return (
    <details
      className="dev-staging-bridge-notice"
      aria-label="Development staging data notice"
    >
      <summary>
        <span className="dev-staging-bridge-notice__icon">
          <ShieldAlert size={15} aria-hidden="true" />
        </span>
        <span className="dev-staging-bridge-notice__heading">
          <strong>Dev · staging data</strong>
          <kbd
            className="dev-staging-bridge-notice__shortcut"
            title="Toggle notice shortcut: Alt+Shift+D (or Option+Shift+D on Mac)"
          >
            Alt+Shift+D
          </kbd>
        </span>
        <button
          type="button"
          className="dev-staging-bridge-notice__dismiss"
          aria-label="Dismiss staging notice (Alt+Shift+D to restore)"
          title="Dismiss notice (Alt+Shift+D)"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            publishNoticeState(true);
          }}
        >
          <X size={14} aria-hidden="true" />
        </button>
      </summary>
      <div className="dev-staging-bridge-notice__body">
        <p>
          Signed-in reads and mutations use the real staging learner account.
          This local session expires when the dev server restarts or after 8
          hours.
        </p>
        <div className="dev-staging-bridge-notice__hint-row">
          <span>Shortcut:</span>
          <kbd>Alt+Shift+D</kbd>
          <span className="dev-staging-bridge-notice__hint-mac">
            (Option+Shift+D)
          </span>
        </div>
      </div>
    </details>
  );
}
