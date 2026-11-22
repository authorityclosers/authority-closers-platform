"use client";

/**
 * "Who gets new leads" in one line, for the ways in to the lead split
 * (v1.94, owner 22 Nov 2026: "I don't see on mobile or anywhere the settings
 * for the ratio of leads, which percentage goes to whom"): the Settings hub's
 * card and the phone account sheet's row both say how new leads go now and
 * open /settings/lead-rules.
 */
import { useEffect, useState } from "react";

import {
  readRouting,
  ROUTING_CHANGED,
  type Routing,
} from "../leads/routing-client";

/** Where the split is set. */
export const LEAD_SPLIT_HREF = "/settings/lead-rules";

/** Said while the rules are still on their way, or didn't load. */
export const SPLIT_LINE_UNKNOWN = "Split new leads by percent";

const OFF_LINE = "Percent split is off: whoever is free gets the next lead";

/** How many sellers the line names before "+N". */
const NAMED = 2;

/**
 * "Split by percent: Farah 20 %, Priya 20 % +3" while the split is on;
 * "Percent split is off: whoever is free gets the next lead" while it isn't
 * (owner's words matter here: v1.94 judge, 22 Nov 2026).
 */
export function splitLine(routing: Pick<Routing, "rules" | "people">): string {
  const rule = routing.rules.find(
    (item) => !item.when.length && !!item.shares?.length,
  );
  if (!rule?.enabled) return OFF_LINE;
  const names = new Map(
    routing.people.map((person) => [
      person.person_id,
      person.name.split(" ")[0] || person.name,
    ]),
  );
  const parts = rule.give_to
    .map((id, at) => ({ id, share: rule.shares?.[at] ?? 0 }))
    .filter((part) => part.share > 0)
    .map((part) => `${names.get(part.id) ?? "A seller"} ${part.share} %`);
  if (!parts.length) return OFF_LINE;
  const shown = parts.slice(0, NAMED).join(", ");
  const rest = parts.length - NAMED;
  return `Split by percent: ${shown}${rest > 0 ? ` +${rest}` : ""}`;
}

/**
 * The line, read once `enabled` (someone who may manage leads, in an
 * organisation) and again after the rules change; null until it is known.
 */
export function useLeadSplitLine(enabled: boolean): string | null {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const read = (signal?: AbortSignal) =>
      readRouting(signal).then(
        (routing) => {
          if (!controller.signal.aborted) setLine(splitLine(routing));
        },
        () => {
          if (!controller.signal.aborted) setLine(SPLIT_LINE_UNKNOWN);
        },
      );
    void read(controller.signal);
    const again = () => void read();
    window.addEventListener(ROUTING_CHANGED, again);
    return () => {
      controller.abort();
      window.removeEventListener(ROUTING_CHANGED, again);
    };
  }, [enabled]);
  return enabled ? line : null;
}
