"use client";

/**
 * Screens add their own commands to the command bar (ui/command-bar.tsx)
 * while they are on screen: Leads offers "Start calling", a lead's page
 * "Call <name>". A screen may also add a search: the bar asks every search
 * for the words typed and lists what each finds under its own group.
 *
 *   useCommandSource("leads", {
 *     commands: [{ id: "leads:start", group: "Actions", label: "Start calling", icon, run }],
 *     search: (text, signal) => findLeads(text, signal),
 *   });
 *
 * Pass null to add nothing (not signed in, not loaded yet). Sources go when
 * their screen unmounts. A key used twice keeps the newest source. A search
 * added under "leads" stands in for the shell's own lead search.
 */

import { useEffect, useSyncExternalStore } from "react";

import type { Command } from "./command-bar";

export type CommandSearch = (
  text: string,
  signal: AbortSignal,
) => Promise<Command[]>;

export type CommandSource = {
  commands?: readonly Command[];
  search?: CommandSearch;
};

type Registered = {
  /** Who has added something: the shell skips its own lead search when a
      screen adds one under "leads". */
  keys: string[];
  commands: Command[];
  searches: CommandSearch[];
};

const sources = new Map<string, CommandSource>();
const listeners = new Set<() => void>();
const EMPTY: Registered = { keys: [], commands: [], searches: [] };
let snapshot: Registered = EMPTY;

function publish() {
  const all = [...sources.values()];
  snapshot = all.length
    ? {
        keys: [...sources.keys()],
        commands: all.flatMap((source) => source.commands ?? []),
        searches: all.flatMap((source) =>
          source.search ? [source.search] : [],
        ),
      }
    : EMPTY;
  listeners.forEach((listener) => listener());
}

/** Adds a source under a key; the returned function takes it away again. */
export function addCommandSource(key: string, source: CommandSource) {
  sources.set(key, source);
  publish();
  return () => {
    if (sources.get(key) !== source) return;
    sources.delete(key);
    publish();
  };
}

/** A screen's commands and search, for as long as it is mounted. */
export function useCommandSource(key: string, source: CommandSource | null) {
  useEffect(() => {
    if (!source) return;
    return addCommandSource(key, source);
  }, [key, source]);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Everything screens have added: for the shell that opens the bar. */
export function useRegisteredCommands(): Registered {
  return useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => EMPTY,
  );
}
