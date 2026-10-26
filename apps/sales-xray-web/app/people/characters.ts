"use client";

/**
 * The characters someone without a photo shows (owner #32, 26 Oct 2026): a
 * small set of illustrated animal faces, never chosen from a name (a name says
 * nothing about a person's gender). The server lists them in its order;
 * someone's default is the first 8 hex digits of their person id modulo the
 * count, as the server picks it. Read once a page; until the files ship the
 * list is empty and avatars keep their initials.
 */

import { useEffect, useSyncExternalStore } from "react";

export const CHARACTERS_PATH = "/v1/people/characters";

export type Character = Readonly<{ key: string; label: string; url: string }>;

const NONE: readonly Character[] = [];
// A failed read is tried again after a minute, not on every avatar.
const RETRY_MS = 60_000;

let list: readonly Character[] | null = null;
let reading: Promise<readonly Character[]> | null = null;
let failedAt = -Infinity;
const listeners = new Set<() => void>();

function parse(value: unknown): readonly Character[] {
  const items = (value as { characters?: unknown } | null)?.characters;
  if (!Array.isArray(items)) return NONE;
  return items.filter(
    (item): item is Character =>
      typeof item?.key === "string" &&
      typeof item?.label === "string" &&
      typeof item?.url === "string" &&
      item.url.startsWith(`${CHARACTERS_PATH}/`),
  );
}

/** The characters, read from the API once a page. */
export function readCharacters(): Promise<readonly Character[]> {
  if (list) return Promise.resolve(list);
  if (Date.now() - failedAt < RETRY_MS) return Promise.resolve(NONE);
  reading ??= fetch(CHARACTERS_PATH, {
    credentials: "same-origin",
    headers: { accept: "application/json" },
  })
    .then(async (response) => {
      if (!response.ok) throw new Error(`characters ${response.status}`);
      list = parse(await response.json());
      for (const listener of listeners) listener();
      return list;
    })
    .catch(() => {
      failedAt = Date.now();
      return NONE;
    })
    .finally(() => {
      reading = null;
    });
  return reading;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The characters once read (none before then); `wanted` false reads nothing. */
export function useCharacters(wanted = true): readonly Character[] {
  const shown = useSyncExternalStore(
    subscribe,
    () => list ?? NONE,
    () => NONE,
  );
  useEffect(() => {
    if (wanted) void readCharacters();
  }, [wanted]);
  return shown;
}

/** Someone's default character: the same one the server picks. */
export function characterFor(
  personId: string,
  characters: readonly Character[],
): Character | null {
  const first = Number.parseInt(personId.replace(/-/g, "").slice(0, 8), 16);
  if (!characters.length || !Number.isFinite(first)) return null;
  return characters[first % characters.length];
}

/** For tests: forget what was read. */
export function resetCharactersForTests() {
  list = null;
  reading = null;
  failedAt = -Infinity;
}
