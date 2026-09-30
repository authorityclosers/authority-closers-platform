"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

/**
 * What a person confirmed, corrected or added about a call's key facts.
 * Kept on this device until the account API stores them (AUT-312, AUT-341).
 */
export type CallFacts = Readonly<{
  /** Fact ids the person confirmed as heard. */
  confirmed: Readonly<Record<string, true>>;
  /** Values the person typed or picked, by fact id. */
  values: Readonly<Record<string, string>>;
  /** What each heard number means, by number id. */
  numberLabels: Readonly<Record<string, string>>;
}>;

export const FACTS_EVENT = "sales-xray:facts";
const EMPTY: CallFacts = { confirmed: {}, values: {}, numberLabels: {} };
const MAX_VALUE = 120;
const key = (callId: string) => `ac.xray.facts.v1:${callId}`;

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function parse(raw: string | null): CallFacts {
  if (!raw) return EMPTY;
  try {
    const data = record(JSON.parse(raw));
    const confirmed: Record<string, true> = {};
    for (const [id, value] of Object.entries(record(data.confirmed)))
      if (value === true) confirmed[id] = true;
    const clean = (source: unknown) => {
      const out: Record<string, string> = {};
      for (const [id, value] of Object.entries(record(source)))
        if (typeof value === "string" && value.trim())
          out[id] = value.trim().slice(0, MAX_VALUE);
      return out;
    };
    return {
      confirmed,
      values: clean(data.values),
      numberLabels: clean(data.numberLabels),
    };
  } catch {
    return EMPTY;
  }
}

function readRaw(callId: string | null): string | null {
  if (!callId) return null;
  try {
    return localStorage.getItem(key(callId));
  } catch {
    return null;
  }
}

export function readCallFacts(callId: string | null): CallFacts {
  return parse(readRaw(callId));
}

/** Removes this call's locally confirmed facts after server deletion succeeds. */
export function clearCallFacts(callId: string): boolean {
  try {
    localStorage.removeItem(key(callId));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(FACTS_EVENT, { detail: { callId } }));
  return true;
}

type Change =
  | { kind: "confirm"; id: string; value: boolean }
  | { kind: "value"; id: string; value: string | null }
  | { kind: "number"; id: string; value: string | null };

export function saveCallFact(callId: string, change: Change): boolean {
  const current = readCallFacts(callId);
  const confirmed = { ...current.confirmed };
  const values = { ...current.values };
  const numberLabels = { ...current.numberLabels };
  if (change.kind === "confirm") {
    if (change.value) confirmed[change.id] = true;
    else delete confirmed[change.id];
  } else {
    const target = change.kind === "value" ? values : numberLabels;
    const next = change.value?.trim().slice(0, MAX_VALUE);
    if (next) target[change.id] = next;
    else delete target[change.id];
  }
  try {
    localStorage.setItem(
      key(callId),
      JSON.stringify({ confirmed, values, numberLabels }),
    );
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(FACTS_EVENT, { detail: { callId } }));
  return true;
}

function subscribe(notify: () => void) {
  window.addEventListener(FACTS_EVENT, notify);
  window.addEventListener("storage", notify);
  return () => {
    window.removeEventListener(FACTS_EVENT, notify);
    window.removeEventListener("storage", notify);
  };
}

export function useCallFacts(callId: string | null) {
  const raw = useSyncExternalStore(
    subscribe,
    () => readRaw(callId),
    () => null,
  );
  const facts = useMemo(() => parse(raw), [raw]);
  const save = useCallback(
    (change: Change) => (callId ? saveCallFact(callId, change) : false),
    [callId],
  );
  return { facts, save, canSave: callId !== null };
}

/** What a heard number can mean, in plain words. */
export const NUMBER_MEANINGS = [
  "Yearly sales",
  "Sales with material",
  "Profit",
  "Money stuck with customers",
  "Price",
  "Budget",
  "Team size",
  "Other",
  "Not important",
] as const;

/** How firm the next step is, from none to committed. */
export const NEXT_STEP_FIRMNESS = [
  "No next step",
  "Loose: no time set",
  "A call with a set time",
  "Invite sent",
  "Committed or paid",
] as const;
