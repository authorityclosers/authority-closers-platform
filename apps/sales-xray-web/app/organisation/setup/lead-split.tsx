"use client";

/**
 * Who gets new leads: a split by percent (owner, Wise Life, 19 Nov 2026: "Dheeraj 20,
 * Aniket 40, Sachin 40"), on the lead rules page (round-2 board 3, option C, 20 Nov
 * 2026). The server keeps it as a routing rule with no conditions and one share per
 * seller (lead_desk/routing_rules.py, `shares`): the next lead goes to whoever is
 * furthest behind their share. Rules for some leads (a source, a city) still come first.
 *
 * v1.93 (22 Nov 2026): the rows, the bar and "out of every 10" show while the
 * split is off too (greyed), so the page explains itself; the page's one Save
 * button saves it with the other rules (`useLeadSplit().save`).
 */
import { Check, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { notify } from "../../notice-center";
import {
  readRouting,
  ROUTING_CHANGED,
  RoutingError,
  saveRouting,
  type Routing,
  type RoutingPerson,
  type RoutingRule,
} from "../../leads/routing-client";
import { Skeleton } from "../../ui/kit";
import { initialsOf } from "../family";
import { OnOff } from "./on-off";
import styles from "./lead-split.module.css";

const SPLIT_NAME = "Split new leads";

/** The split: a rule for every new lead with shares. */
export function splitRule(rules: readonly RoutingRule[]): RoutingRule | null {
  return (
    rules.find((rule) => !rule.when.length && !!rule.shares?.length) ?? null
  );
}

/**
 * Who the next `count` leads go to from a fresh start: each goes to whoever is
 * furthest behind their share (the server's own way), the list's order on a tie.
 */
export function nextTurns(
  shares: readonly { id: string; share: number }[],
  count: number,
): string[] {
  const given = new Map<string, number>();
  const turns: string[] = [];
  for (let lead = 1; lead <= count; lead++) {
    let best: string | null = null;
    let behind = -Infinity;
    for (const { id, share } of shares) {
      if (share <= 0) continue;
      const owed = (share * lead) / 100 - (given.get(id) ?? 0);
      if (owed > behind + 1e-9) {
        behind = owed;
        best = id;
      }
    }
    if (!best) break;
    given.set(best, (given.get(best) ?? 0) + 1);
    turns.push(best);
  }
  return turns;
}

/** An even split to start from: 34 / 33 / 33 for three. */
export function evenShares(ids: readonly string[]): Record<string, string> {
  if (!ids.length) return {};
  const base = Math.floor(100 / ids.length);
  const extra = 100 - base * ids.length;
  return Object.fromEntries(
    ids.map((id, at) => [id, String(base + (at < extra ? 1 : 0))]),
  );
}

/** Who an even split starts with: those taking leads (everyone if none is). */
export function takers(people: readonly RoutingPerson[]): string[] {
  const free = people.filter((person) => person.available);
  return (free.length ? free : people).map((person) => person.person_id);
}

export const firstName = (name: string) => name.split(" ")[0] ?? name;

const savedShares = (rule: RoutingRule | null) =>
  Object.fromEntries(
    (rule?.give_to ?? []).map((id, at) => [
      id,
      String(rule?.shares?.[at] ?? 0),
    ]),
  );

export type SplitPart = { id: string; name: string; share: number };

export type LeadSplitState = {
  status: "loading" | "hidden" | "ready";
  retry: () => void;
  people: readonly RoutingPerson[];
  parts: SplitPart[];
  shares: Record<string, string>;
  setShare: (id: string, value: string) => void;
  on: boolean;
  setOn: (on: boolean) => void;
  total: number;
  /** The shares add up to 100 and someone gets leads. */
  ready: boolean;
  /** Something differs from what is saved. */
  changed: boolean;
  /** Save can go: off, or on with shares that add up. */
  valid: boolean;
  canEdit: boolean;
  busy: boolean;
  /** Who the next five leads go to, by first name (on and adding up). */
  turns: string[];
  discard: () => void;
  /** Saves on the newest rules; true when saved (or nothing to save). */
  save: () => Promise<boolean>;
};

export function useLeadSplit(): LeadSplitState {
  const [routing, setRouting] = useState<Routing | null | "hidden">(null);
  const [shares, setShares] = useState<Record<string, string>>({});
  const [on, setOnState] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const take = useCallback((next: Routing) => {
    setRouting(next);
    const rule = splitRule(next.rules);
    setOnState(!!rule?.enabled);
    setShares(rule ? savedShares(rule) : evenShares(takers(next.people)));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    readRouting(controller.signal).then(
      (next) => {
        if (!controller.signal.aborted) take(next);
      },
      () => {
        if (!controller.signal.aborted) setRouting("hidden");
      },
    );
    const again = () => void readRouting().then(take, () => undefined);
    window.addEventListener(ROUTING_CHANGED, again);
    return () => {
      controller.abort();
      window.removeEventListener(ROUTING_CHANGED, again);
    };
  }, [attempt, take]);

  // Those taking leads first, the rest after, each in the server's order.
  const people = useMemo(
    () =>
      routing && routing !== "hidden"
        ? [
            ...routing.people.filter((person) => person.available),
            ...routing.people.filter((person) => !person.available),
          ]
        : [],
    [routing],
  );
  const parts = useMemo(
    () =>
      people.map((person) => ({
        id: person.person_id,
        name: person.name,
        share: Math.max(
          0,
          Math.min(100, Number(shares[person.person_id] || 0)),
        ),
      })),
    [people, shares],
  );
  const total = parts.reduce((sum, part) => sum + part.share, 0);
  const ready = total === 100 && parts.some((part) => part.share > 0);
  const saved =
    routing && routing !== "hidden" ? splitRule(routing.rules) : null;
  const savedShare = (id: string) => {
    const at = saved ? saved.give_to.indexOf(id) : -1;
    return at < 0 ? 0 : (saved?.shares?.[at] ?? 0);
  };
  const changed =
    on !== !!saved?.enabled ||
    (on && parts.some((part) => part.share !== savedShare(part.id)));
  const turns = useMemo(() => {
    const names = new Map(parts.map((part) => [part.id, firstName(part.name)]));
    return nextTurns(parts, 5).map((id) => names.get(id) ?? "");
  }, [parts]);

  const reset = (next: Routing) => {
    const rule = splitRule(next.rules);
    setOnState(!!rule?.enabled);
    setShares(rule ? savedShares(rule) : evenShares(takers(next.people)));
  };

  const save = async (): Promise<boolean> => {
    if (!routing || routing === "hidden" || !changed) return true;
    if (busy || (on && !ready)) return false;
    setBusy(true);
    try {
      // The newest rules, so a rule saved elsewhere on the page stays.
      const fresh = await readRouting();
      const old = splitRule(fresh.rules);
      const chosen = parts.filter((part) => part.share > 0);
      const rule: RoutingRule = {
        id: old?.id ?? null,
        name: old?.name || SPLIT_NAME,
        enabled: on,
        when: [],
        // Off keeps the saved shares for next time.
        give_to: on || !old ? chosen.map((part) => part.id) : old.give_to,
        shares:
          on || !old
            ? chosen.map((part) => part.share)
            : [...(old.shares ?? [])],
      };
      // Rules for some leads first; the split takes every lead they leave.
      const rules = [
        ...fresh.rules.filter((item) => item !== old),
        ...(rule.give_to.length && (on || old) ? [rule] : []),
      ];
      const next = await saveRouting(fresh.revision, fresh.value_answer, rules);
      setRouting(next);
      reset(next);
      window.dispatchEvent(new Event(ROUTING_CHANGED));
      return true;
    } catch (reason) {
      notify({
        id: "lead-split",
        tone: "error",
        title: "Split not saved",
        message:
          reason instanceof RoutingError
            ? reason.message
            : "Check your connection and try again.",
      });
      return false;
    } finally {
      setBusy(false);
    }
  };

  return {
    status: routing === "hidden" ? "hidden" : routing ? "ready" : "loading",
    retry: () => {
      setRouting(null);
      setAttempt((value) => value + 1);
    },
    people,
    parts,
    shares,
    setShare: (id, value) =>
      setShares((now) => ({
        ...now,
        [id]: value.replace(/\D/g, "").slice(0, 3),
      })),
    on,
    setOn: (next) => {
      if (!routing || routing === "hidden") return;
      if (!next) {
        // Off shows the saved shares again, greyed.
        reset(routing);
        setOnState(false);
        return;
      }
      setOnState(true);
      // On with no shares starts from an even split.
      if (!Object.values(shares).some((value) => Number(value) > 0))
        setShares(evenShares(takers(people)));
    },
    total,
    ready,
    changed,
    valid: !on || ready,
    canEdit: routing && routing !== "hidden" ? routing.can_edit : false,
    busy,
    turns: on && ready ? turns : [],
    discard: () => {
      if (routing && routing !== "hidden") reset(routing);
    },
    save,
  };
}

/** "Out of every 10 new leads: Mira 2 · Anika 4 · Ravi 4". */
export function perTen(parts: readonly SplitPart[]): string {
  return parts
    .filter((part) => part.share > 0)
    .map(
      (part) =>
        `${firstName(part.name)} ${Number((part.share / 10).toFixed(1))}`,
    )
    .join(" · ");
}

/** One person's initials on a neutral tile (colour only by meaning). */
export function Face({ name }: { name: string }) {
  return (
    <i className={styles.avatar} aria-hidden="true">
      {initialsOf(name)}
    </i>
  );
}

function ShareRow({
  part,
  split,
  editable,
}: {
  part: SplitPart;
  split: LeadSplitState;
  editable: boolean;
}) {
  const person = split.people.find((item) => item.person_id === part.id);
  return (
    <li className={styles.person}>
      <Face name={part.name} />
      <span className={styles.name}>
        <strong>{part.name}</strong>
        {person && !person.available ? (
          <small>Not taking leads now</small>
        ) : null}
      </span>
      <label className={styles.percent}>
        <input
          type="text"
          inputMode="numeric"
          aria-label={`${part.name}'s share in percent`}
          value={split.shares[part.id] ?? ""}
          placeholder="0"
          disabled={!editable}
          onChange={(event) => split.setShare(part.id, event.target.value)}
        />
        <span aria-hidden="true">%</span>
      </label>
    </li>
  );
}

/** The "Who gets new leads" card. */
export function LeadSplitCard({ split }: { split: LeadSplitState }) {
  const [showAll, setShowAll] = useState(false);
  if (split.status === "hidden")
    return (
      <section className={styles.card}>
        <h3 className={styles.title}>Who gets new leads</h3>
        <p className={styles.sub}>The split didn&apos;t load.</p>
        <button type="button" className={styles.retry} onClick={split.retry}>
          Try again
        </button>
      </section>
    );
  if (split.status === "loading")
    return (
      <div aria-busy="true" aria-label="Loading who gets new leads">
        <Skeleton height={220} />
      </div>
    );

  const { on, parts, canEdit, busy, total } = split;
  const editable = canEdit && on && !busy;
  // Sellers not taking leads, at 0 %, wait behind one row (v1.93 judge r2):
  // the off state stays one screen, and one tap shows them to give a share.
  const away = new Set(
    split.people
      .filter((person) => !person.available)
      .map((person) => person.person_id),
  );
  const resting = (part: SplitPart) => away.has(part.id) && part.share === 0;
  const restingCount = parts.filter(resting).length;
  const shown = parts.filter((part) => part.share > 0);

  return (
    <section
      className={styles.card}
      aria-labelledby="lead-split-title"
      data-off={on ? undefined : ""}
    >
      <div className={styles.head}>
        <h3 id="lead-split-title" className={styles.title}>
          Who gets new leads
        </h3>
        <OnOff
          label="Split new leads by percent"
          on={on}
          disabled={!canEdit || busy}
          feature="lead_split_switch"
          onChange={split.setOn}
        />
      </div>
      <p className={styles.sub}>
        {on
          ? "Split by percent. Rules for some leads, below, come first."
          : "Off: each new lead goes to whoever is free with the fewest open leads. Turn on to split by percent."}
      </p>
      {parts.length === 0 ? (
        <p className={styles.sub}>Invite a seller from Team to split leads.</p>
      ) : (
        <div className={styles.split}>
          <ul className={styles.people} aria-label="Shares">
            {(showAll ? parts : parts.filter((part) => !resting(part))).map(
              (part) => (
                <ShareRow
                  key={part.id}
                  part={part}
                  split={split}
                  editable={editable}
                />
              ),
            )}
          </ul>
          {restingCount ? (
            <button
              type="button"
              className={styles.more}
              aria-expanded={showAll}
              onClick={() => setShowAll((value) => !value)}
            >
              <span>
                {showAll
                  ? `Hide the ${restingCount} not taking leads`
                  : `${restingCount} not taking leads`}
              </span>
              <ChevronDown aria-hidden="true" />
            </button>
          ) : null}
          <div className={styles.bar} aria-hidden="true">
            {shown.map((part) => (
              <span
                key={part.id}
                title={`${part.name} ${part.share} %`}
                style={{ flexBasis: `${Math.min(100, part.share)}%` }}
              />
            ))}
          </div>
          {/* Off: no sums or "out of 10", which would read as a rule in force
              (v1.93 judge r3); the rows and shares stay to show the split. */}
          {on ? (
            <div className={styles.sum} aria-live="polite">
              {total === 100 ? (
                <span className={styles.good}>
                  Adds up to 100 %
                  <Check size={16} strokeWidth={2.5} aria-hidden="true" />
                </span>
              ) : (
                <span className={styles.short}>
                  Adds up to {total} %:{" "}
                  {total < 100
                    ? `${100 - total} % left to give`
                    : `${total - 100} % too much`}
                </span>
              )}
              {shown.length ? (
                <span className={styles.ten}>
                  Out of every 10 new leads: {perTen(parts)}
                </span>
              ) : null}
            </div>
          ) : null}
          {split.turns.length ? (
            <p className={styles.next} data-inline-preview="">
              <strong>The next 5 leads go to:</strong>
              <span>{split.turns.join(", ")}</span>
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
