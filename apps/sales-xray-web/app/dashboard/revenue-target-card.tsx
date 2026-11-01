"use client";

/**
 * "Monthly revenue target": a card in Home's Team controls (owner meeting,
 * 28 Oct 2026). The owner sets the organisation's month; each seller gets an even
 * share unless they have their own, which the owner sets, or the seller where the
 * workspace allows it. This month and next sit side by side, a row per seller
 * (competitor teardown #8, 1 Nov 2026). The typical deal size stands in for "what it takes" until
 * there are three deals of its own. The Home session renders the card in its
 * list and the detail under its Back button (team-controls.tsx).
 */

import { Check, ChevronRight, Target } from "lucide-react";
import { useEffect, useState } from "react";

import { amountOf } from "../leads/pipeline/blocks";
import { LeadsError } from "../leads/leads-client";
import { notify } from "../notice-center";
import {
  inr,
  monthName,
  readRevenue,
  readRevenueTargets,
  saveRevenueSettings,
  saveRevenueTargets,
  type Revenue,
  type RevenueTargets,
} from "./revenue-client";
import styles from "./revenue.module.css";

/** The card's chip: "₹12 L · split 4 ways", "₹9 L · 3 sellers", or "Not set". */
export function targetChip(targets: RevenueTargets | null): string {
  if (!targets) return "…";
  const people = targets.sellers.length;
  if (targets.organisation)
    return `${inr(targets.organisation)} · split ${people} way${people === 1 ? "" : "s"}`;
  const own = targets.sellers.filter((line) => line.own);
  if (own.length) {
    const sum = own.reduce((total, line) => total + (line.own ?? 0), 0);
    return `${inr(sum)} · ${own.length} seller${own.length === 1 ? "" : "s"}`;
  }
  return "Not set";
}

export function RevenueTargetCard({ onOpen }: { onOpen: () => void }) {
  const [targets, setTargets] = useState<RevenueTargets | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const read = await readRevenueTargets(undefined, controller.signal);
        if (!controller.signal.aborted) setTargets(read);
      } catch {
        // The card still opens; its detail says what didn't load.
      }
    })();
    return () => controller.abort();
  }, []);
  const chip = targetChip(targets);
  return (
    <button
      type="button"
      className={styles.card}
      data-control="revenue"
      onClick={onOpen}
    >
      <span className={styles.icon} aria-hidden="true">
        <Target size={20} />
      </span>
      <span className={styles.cardTitle}>Monthly revenue target</span>
      <span
        className={styles.chip}
        data-tone={chip === "Not set" ? "off" : undefined}
      >
        {chip}
      </span>
      <ChevronRight className={styles.chevron} size={18} aria-hidden="true" />
    </button>
  );
}

function thisAndNext(): [string, string] {
  const now = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const first = (year: number, month: number) =>
    `${year}-${String(month + 1).padStart(2, "0")}-01`;
  const next =
    now.getMonth() === 11
      ? first(now.getFullYear() + 1, 0)
      : first(now.getFullYear(), now.getMonth() + 1);
  return [first(now.getFullYear(), now.getMonth()), next];
}

/** "₹5 L this month → 4 wins → 12 meetings → 40 interested → about 20 calls a day". */
export function takesChain(revenue: Revenue): string | null {
  const needs = revenue.needs;
  if (!needs || revenue.target === null) return null;
  if (revenue.won >= revenue.target) return "This month's target is reached.";
  return `${inr(revenue.target - revenue.won)} to go → ${needs.wins} wins → ${needs.meetings} meetings → ${needs.interested} interested → about ${needs.calls_per_day} calls a day${needs.estimate ? " (estimate)" : ""}`;
}

/** One month's cells: the organisation's amount and each seller's own, as typed. */
type Cells = { org: string; own: Record<string, string> };

/** An amount as people write it, Indian grouping: 15,00,000 (ph1-29: not 1500000). */
const GROUPED = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const textOf = (value: number | null) => (value ? GROUPED.format(value) : "");

/** What was typed and not saved, kept when the card closes (ph1-29: Back
 *  discarded it silently); it comes back the next time the card opens. */
let draft: Record<string, Cells> | null = null;

/** For tests: start without a draft. */
export function forgetTargetDraft() {
  draft = null;
}

const cellsOf = (read: RevenueTargets): Cells => ({
  org: textOf(read.organisation),
  own: Object.fromEntries(
    read.sellers.map((line) => [line.person_id, textOf(line.own)]),
  ),
});

/** A cell in rupees: empty is no target (0); null when it doesn't read. */
const amount = (text: string): number | null =>
  text.trim() === "" ? 0 : amountOf(text);

/** What a month's cells change: the organisation's, and the sellers whose own
 *  target changed, compared as amounts ("4 L" is 400000). */
function changesOf(read: RevenueTargets, cells: Cells, manage: boolean) {
  const org = amount(cells.org);
  const sellers = read.sellers
    .map((line) => ({
      person_id: line.person_id,
      amount: amount(cells.own[line.person_id] ?? ""),
      was: line.own ?? 0,
    }))
    .filter((line) => line.amount === null || line.amount !== line.was)
    .map(({ person_id, amount: value }) => ({ person_id, amount: value }));
  return {
    org,
    orgChanged: manage && org !== null && org !== (read.organisation ?? 0),
    sellers,
    invalid: org === null || sellers.some((line) => line.amount === null),
  };
}

/** "Sellers add up to ₹12 L, ₹3 L short of ₹15 L" (competitor teardown #8,
 *  1 Nov 2026): each seller's own target or even share against the
 *  organisation's, once a seller has one of their own. */
export function mismatch(cells: Cells, people: string[]): string | null {
  const org = amount(cells.org);
  const owns = people.map((id) => cells.own[id] ?? "");
  if (!org || !owns.some((text) => text.trim() !== "")) return null;
  const share = Math.floor(org / Math.max(1, people.length));
  let sum = 0;
  for (const text of owns) {
    const value = text.trim() === "" ? share : amount(text);
    if (value === null) return null;
    sum += value;
  }
  // An even split rounds down by under a rupee a seller.
  if (Math.abs(org - sum) < people.length) return null;
  return `Sellers add up to ${inr(sum)}, ${inr(Math.abs(org - sum))} ${
    sum < org ? "short of" : "over"
  } ${inr(org)}`;
}

/** The sellers x month grid (competitor teardown #8, 1 Nov 2026): this month
 *  and next, the organisation's row, each seller's row; Split equally, Apply to
 *  all, and a warning when the sellers don't add up to the organisation's. */
export function RevenueTargetDetail() {
  const [this_, next] = thisAndNext();
  const [targets, setTargets] = useState<Record<string, RevenueTargets>>({});
  const [cells, setCells] = useState<Record<string, Cells>>({});
  const [failed, setFailed] = useState(false);
  const [team, setTeam] = useState<Revenue | null>(null);
  const [typical, setTypical] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  useEffect(() => {
    if (!savedNote) return;
    const timer = window.setTimeout(() => setSavedNote(null), 3000);
    return () => window.clearTimeout(timer);
  }, [savedNote]);

  useEffect(() => {
    const controller = new AbortController();
    const months = [this_, next];
    void (async () => {
      try {
        const read = await Promise.all(
          months.map((month) => readRevenueTargets(month, controller.signal)),
        );
        if (controller.signal.aborted) return;
        setTargets(Object.fromEntries(months.map((m, i) => [m, read[i]])));
        const kept = draft;
        setCells(
          kept && months.every((month) => kept[month])
            ? kept
            : Object.fromEntries(months.map((m, i) => [m, cellsOf(read[i])])),
        );
        setTypical(textOf(read[0].typical_deal));
        setFailed(false);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    return () => controller.abort();
  }, [this_, next]);

  // Unsaved edits stay as a draft; a save that leaves nothing to save clears it.
  useEffect(() => {
    const shown = [this_, next];
    if (!shown.every((month) => targets[month] && cells[month])) return;
    const manage = targets[this_].can_manage;
    const changed = shown.some((month) => {
      const change = changesOf(targets[month], cells[month], manage);
      return change.invalid || change.orgChanged || change.sellers.length > 0;
    });
    draft = changed ? cells : null;
  }, [cells, targets, this_, next]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const read = await readRevenue("team", controller.signal);
        if (!controller.signal.aborted) setTeam(read);
      } catch {
        // Sellers don't see the team's month; the line just isn't shown.
      }
    })();
    return () => controller.abort();
  }, [targets]);

  if (failed)
    return (
      <p className={styles.small} role="status">
        Targets didn&apos;t load. Go back and try again in a moment.
      </p>
    );
  const months = [this_, next];
  const first = targets[this_];
  if (!first || months.some((month) => !targets[month] || !cells[month]))
    return <div className={styles.detail} aria-busy="true" />;

  const manage = first.can_manage;
  // A seller sees only their own line, and edits it where the workspace allows.
  const editable = manage || first.sellers_set_own;
  const people = first.sellers.map((line) => line.person_id);
  const changes = months.map((month) => ({
    month,
    ...changesOf(targets[month], cells[month], manage),
  }));
  const invalid = changes.some((change) => change.invalid);
  const dirty = changes.some(
    (change) => change.orgChanged || change.sellers.length > 0,
  );
  const chain = team ? takesChain(team) : null;
  const edit = (month: string, change: (current: Cells) => Cells) =>
    setCells((all) => ({ ...all, [month]: change(all[month]) }));

  // Each seller the organisation's amount over the sellers, in every month that has one.
  const splitEqually = () =>
    setCells((all) =>
      Object.fromEntries(
        months.map((month) => {
          const org = amount(all[month].org);
          if (!org) return [month, all[month]];
          const share = textOf(Math.floor(org / Math.max(1, people.length)));
          return [
            month,
            {
              ...all[month],
              own: Object.fromEntries(people.map((id) => [id, share])),
            },
          ];
        }),
      ),
    );
  // This month's targets for every month shown.
  const applyToAll = () =>
    setCells((all) => ({
      ...all,
      ...Object.fromEntries(
        months
          .slice(1)
          .map((month) => [
            month,
            { org: all[this_].org, own: { ...all[this_].own } },
          ]),
      ),
    }));

  const save = async () => {
    if (invalid || !dirty || saving) return;
    setSaving(true);
    try {
      const saved: Record<string, RevenueTargets> = {};
      for (const change of changes) {
        if (!change.orgChanged && !change.sellers.length) continue;
        saved[change.month] = await saveRevenueTargets(change.month, {
          ...(change.orgChanged ? { organisation: change.org ?? 0 } : {}),
          ...(change.sellers.length
            ? {
                sellers: change.sellers.map((line) => ({
                  person_id: line.person_id,
                  amount: line.amount ?? 0,
                })),
              }
            : {}),
        });
      }
      setTargets((all) => ({ ...all, ...saved }));
      const words = `${Object.keys(saved).map(monthName).join(" and ")} saved`;
      // Said here, by the button: the corner notice sits under this sheet.
      setSavedNote(words);
      notify({
        id: "revenue-target",
        tone: "success",
        title: words,
        timeout: 3000,
      });
    } catch (reason) {
      notify({
        id: "revenue-target",
        tone: "error",
        title: "Not saved",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  const saveSettings = async (setOwnNext: boolean, typicalText: string) => {
    const deal = typicalText.trim() === "" ? null : amountOf(typicalText);
    if (typicalText.trim() !== "" && deal === null) return;
    try {
      const saved = await saveRevenueSettings(first.revision, setOwnNext, deal);
      setTargets((all) => ({ ...all, [this_]: saved }));
    } catch (reason) {
      notify({
        id: "revenue-settings",
        tone: "error",
        title: "Not saved",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    }
  };

  return (
    <div className={styles.detail}>
      {chain ? <p className={styles.takesLine}>{chain}</p> : null}
      <div className={styles.grid}>
        <div className={styles.gridRow}>
          <span className={styles.gridName} />
          {months.map((month) => (
            <span key={month} className={styles.gridMonth}>
              {monthName(month)}
            </span>
          ))}
        </div>
        <div className={styles.gridRow}>
          <span className={styles.gridName}>Organisation</span>
          {months.map((month) => (
            <input
              key={month}
              className={styles.input}
              inputMode="decimal"
              placeholder="₹12 L"
              aria-label={`Organisation, ${monthName(month)}`}
              value={cells[month].org}
              disabled={!manage}
              aria-invalid={amount(cells[month].org) === null}
              onChange={(event) => {
                const value = event.target.value;
                edit(month, (current) => ({ ...current, org: value }));
              }}
            />
          ))}
        </div>
        {first.sellers.map((line) => (
          <div key={line.person_id} className={styles.gridRow}>
            <span className={styles.gridName}>{line.name}</span>
            {months.map((month) => {
              const split =
                targets[month].sellers.find(
                  (each) => each.person_id === line.person_id,
                )?.split ?? null;
              const text = cells[month].own[line.person_id] ?? "";
              return (
                <input
                  key={month}
                  className={styles.input}
                  inputMode="decimal"
                  placeholder={split ? inr(split) : "—"}
                  aria-label={`${line.name}, ${monthName(month)}`}
                  value={text}
                  disabled={!editable}
                  aria-invalid={amount(text) === null}
                  onChange={(event) => {
                    const value = event.target.value;
                    edit(month, (current) => ({
                      ...current,
                      own: { ...current.own, [line.person_id]: value },
                    }));
                  }}
                />
              );
            })}
          </div>
        ))}
      </div>
      {manage ? (
        <div className={styles.gridActions}>
          <button
            type="button"
            className={styles.gridAction}
            onClick={splitEqually}
          >
            Split equally
          </button>
          <button
            type="button"
            className={styles.gridAction}
            title={`${monthName(this_)}'s targets for ${monthName(next)} too`}
            onClick={applyToAll}
          >
            Apply to all
          </button>
        </div>
      ) : null}
      {months.map((month) => {
        const words = mismatch(cells[month], people);
        return words ? (
          <p key={month} className={styles.mismatch} role="status">
            {`${monthName(month)}: ${words}`}
          </p>
        ) : null;
      })}
      {dirty ? (
        <p className={styles.small} role="status">
          Not saved yet
        </p>
      ) : null}
      {editable ? (
        <button
          type="button"
          className={styles.save}
          disabled={!dirty || invalid || saving}
          aria-busy={saving || undefined}
          onClick={() => void save()}
        >
          Save
        </button>
      ) : null}
      <p className={styles.savedNote} role="status">
        {savedNote ? (
          <>
            <Check size={16} aria-hidden="true" />
            {savedNote}
          </>
        ) : null}
      </p>
      {manage ? (
        <div className={styles.group}>
          <div className={styles.row}>
            <span className={styles.rowLabel} id="revenue-set-own">
              Sellers set their own
            </span>
            <button
              type="button"
              role="switch"
              className={styles.toggle}
              aria-checked={first.sellers_set_own}
              aria-labelledby="revenue-set-own"
              onClick={() => void saveSettings(!first.sellers_set_own, typical)}
            />
          </div>
          <label className={styles.row}>
            <span className={styles.rowLabel}>
              Typical deal
              <small>Until there are three won deals</small>
            </span>
            <input
              className={styles.input}
              inputMode="decimal"
              placeholder="₹60,000"
              value={typical}
              aria-invalid={typical.trim() !== "" && amountOf(typical) === null}
              onChange={(event) => setTypical(event.target.value)}
              onBlur={() => {
                if (typical !== textOf(first.typical_deal))
                  void saveSettings(first.sellers_set_own, typical);
              }}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}
