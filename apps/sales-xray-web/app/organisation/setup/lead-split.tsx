"use client";

/**
 * Who gets new leads: a split by percent (owner, Wise Life, 19 Nov 2026: "Dheeraj 20,
 * Aniket 40, Sachin 40"), on the lead rules page (round-2 board 3, option C, 20 Nov
 * 2026). The server keeps it as a routing rule with no conditions and one share per
 * seller (lead_desk/routing_rules.py, `shares`): the next lead goes to whoever is
 * furthest behind their share. Rules for some leads (a source, a city) still come first.
 */
import { Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { notify } from "../../notice-center";
import {
  readRouting,
  ROUTING_CHANGED,
  RoutingError,
  saveRouting,
  type Routing,
  type RoutingRule,
} from "../../leads/routing-client";
import { Avatar, Skeleton } from "../../ui/kit";
import setup from "./setup.module.css";
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

const firstName = (name: string) => name.split(" ")[0] ?? name;

export function LeadSplit() {
  const [routing, setRouting] = useState<Routing | null | "hidden">(null);
  const [shares, setShares] = useState<Record<string, string>>({});
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const take = (next: Routing) => {
      if (controller.signal.aborted) return;
      setRouting(next);
      const rule = splitRule(next.rules);
      setOn(!!rule?.enabled);
      setShares(
        Object.fromEntries(
          (rule?.give_to ?? []).map((id, at) => [
            id,
            String(rule?.shares?.[at] ?? 0),
          ]),
        ),
      );
    };
    readRouting(controller.signal).then(take, () => {
      if (!controller.signal.aborted) setRouting("hidden");
    });
    const again = () => void readRouting().then(take, () => undefined);
    window.addEventListener(ROUTING_CHANGED, again);
    return () => {
      controller.abort();
      window.removeEventListener(ROUTING_CHANGED, again);
    };
  }, [attempt]);

  const people = useMemo(
    () => (routing && routing !== "hidden" ? routing.people : []),
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
  const turns = useMemo(() => nextTurns(parts, 5), [parts]);

  if (routing === "hidden")
    return (
      <section className={setup.card}>
        <h3>Who gets new leads</h3>
        <p className={setup.help}>
          The split didn&apos;t load.{" "}
          <button
            type="button"
            className={setup.button}
            onClick={() => {
              setRouting(null);
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        </p>
      </section>
    );
  if (!routing)
    return (
      <div aria-busy="true" aria-label="Loading who gets new leads">
        <Skeleton height={200} />
      </div>
    );

  const saved = splitRule(routing.rules);
  const ready = total === 100 && parts.some((part) => part.share > 0);
  const savedShare = (id: string) => {
    const at = saved ? saved.give_to.indexOf(id) : -1;
    return at < 0 ? 0 : (saved?.shares?.[at] ?? 0);
  };
  const changed =
    on !== !!saved?.enabled ||
    parts.some((part) => part.share !== savedShare(part.id));

  const save = async (turnOn: boolean) => {
    if (busy || (turnOn && !ready)) return;
    setBusy(true);
    try {
      // The newest rules, so a rule saved elsewhere on the page stays.
      const fresh = await readRouting();
      const old = splitRule(fresh.rules);
      const chosen = parts.filter((part) => part.share > 0);
      const rule: RoutingRule = {
        id: old?.id ?? null,
        name: old?.name || SPLIT_NAME,
        enabled: turnOn,
        when: [],
        give_to: turnOn || !old ? chosen.map((part) => part.id) : old.give_to,
        shares:
          turnOn || !old
            ? chosen.map((part) => part.share)
            : [...(old.shares ?? [])],
      };
      // Rules for some leads first; the split takes every lead they leave.
      const rules = [
        ...fresh.rules.filter((item) => item !== old),
        ...(rule.give_to.length ? [rule] : []),
      ];
      const next = await saveRouting(fresh.revision, fresh.value_answer, rules);
      setRouting(next);
      setOn(turnOn);
      window.dispatchEvent(new Event(ROUTING_CHANGED));
      notify({
        id: "lead-split",
        tone: "success",
        title: turnOn ? "Split saved" : "Split off",
        message: turnOn
          ? "New leads go by these shares from now on."
          : "New leads go to whoever is free with the fewest open leads.",
      });
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
    } finally {
      setBusy(false);
    }
  };

  const nameOf = (id: string) =>
    firstName(parts.find((part) => part.id === id)?.name ?? "");
  const canEdit = routing.can_edit;

  return (
    <section className={setup.card} aria-labelledby="lead-split-title">
      <div className={setup.head}>
        <div>
          <h3 id="lead-split-title">Who gets new leads</h3>
          <p>
            {on
              ? "Split by percent. Rules for some leads, below, come first."
              : "Off: each new lead goes to whoever is free with the fewest open leads."}
          </p>
        </div>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            role="switch"
            className={styles.switch}
            aria-label="Split new leads by percent"
            checked={on}
            disabled={!canEdit || busy}
            data-sx-feature="lead_split_switch"
            onChange={(event) => {
              const next = event.target.checked;
              // Turning on waits for shares that add up; turning off saves.
              if (next) setOn(true);
              else if (saved?.enabled) void save(false);
              else setOn(false);
            }}
          />
          {on ? "On" : "Off"}
        </label>
      </div>
      {on ? (
        <>
          <ul className={styles.people} aria-label="Shares">
            {parts.map((part) => {
              const person = people.find((item) => item.person_id === part.id);
              return (
                <li key={part.id} className={styles.person}>
                  <Avatar name={part.name} size={32} />
                  <span className={styles.name}>
                    <strong>{part.name}</strong>
                    {person && !person.available ? (
                      <small>Not taking leads now</small>
                    ) : null}
                  </span>
                  <label className={styles.percent}>
                    <input
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={100}
                      step={5}
                      aria-label={`${part.name}'s share in percent`}
                      value={shares[part.id] ?? ""}
                      placeholder="0"
                      disabled={!canEdit || busy}
                      onChange={(event) =>
                        setShares((now) => ({
                          ...now,
                          [part.id]: event.target.value
                            .replace(/\D/g, "")
                            .slice(0, 3),
                        }))
                      }
                    />
                    %
                  </label>
                </li>
              );
            })}
          </ul>
          <div className={styles.bar} aria-hidden="true">
            {parts
              .filter((part) => part.share > 0)
              .map((part) => (
                <span
                  key={part.id}
                  style={{ width: `${Math.min(100, part.share)}%` }}
                />
              ))}
          </div>
          <p className={styles.sum} aria-live="polite">
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
          </p>
          {ready ? (
            <p className={styles.preview}>
              <strong>Out of every 10 new leads</strong>
              <span>
                {parts
                  .filter((part) => part.share > 0)
                  .map(
                    (part) =>
                      `${firstName(part.name)} ${Number((part.share / 10).toFixed(1))}`,
                  )
                  .join(" · ")}
              </span>
              <span>From a fresh start: {turns.map(nameOf).join(", ")}…</span>
            </p>
          ) : null}
          {canEdit ? (
            <div className={styles.actions}>
              <button
                type="button"
                className={setup.primary}
                disabled={!ready || busy || !changed}
                data-sx-feature="lead_split_saved"
                onClick={() => void save(true)}
              >
                {busy ? "Saving…" : "Save split"}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
