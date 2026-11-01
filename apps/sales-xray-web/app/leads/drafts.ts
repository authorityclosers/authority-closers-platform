"use client";

/**
 * Drafts kept on this device (ph2-19, 1 Nov 2026: drafts outlive the app):
 * the after-call note, a lead's note, quick add's name and phone, a task's
 * title. Back, Forward, a refresh or a closed app never lose what was typed;
 * saving clears it. Storage may be missing (private mode, full): the draft
 * then lives in the page only.
 */

import { useState, useSyncExternalStore } from "react";

const DRAFTS = "sx-draft:";

export function readDraft(key: string): string {
  try {
    return localStorage.getItem(DRAFTS + key) ?? "";
  } catch {
    return "";
  }
}

export function keepDraft(key: string, text: string) {
  try {
    if (text.trim()) localStorage.setItem(DRAFTS + key, text);
    else localStorage.removeItem(DRAFTS + key);
  } catch {
    // Private mode or full storage: the draft lives in the page only.
  }
}

const never = () => () => undefined;

/**
 * A text field's value kept as a draft under `key`: restored once the page
 * has hydrated (never in the server's render, so nothing mismatches), and
 * kept as it changes; setting "" clears it (the robot, 1 Nov 2026: quick add
 * and Add task lost their words on Back, Forward and refresh).
 */
export function useDraft(key: string): [string, (text: string) => void] {
  const hydrated = useSyncExternalStore(
    never,
    () => true,
    () => false,
  );
  const [text, setText] = useState("");
  const [restored, setRestored] = useState<string | null>(null);
  if (hydrated && restored !== key) {
    setRestored(key);
    setText(readDraft(key));
  }
  const change = (next: string) => {
    setText(next);
    keepDraft(key, next);
  };
  return [text, change];
}
