"use client";

/**
 * "Monthly revenue target": the sixth card in Home's Team controls (owner meeting,
 * 28 Oct 2026). The owner sets the organisation's month; each seller gets an even
 * share unless they have their own, which the owner sets, or the seller where the
 * workspace allows it. The typical deal size stands in for "what it takes" until
 * there are three deals of its own. The Home session renders the card in its
 * list and the detail under its Back button (team-controls.tsx).
 */

import { ChevronRight, Target } from "lucide-react";
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

export function RevenueTargetDetail() {
  const [this_, next] = thisAndNext();
  const [month, setMonth] = useState(this_);
  const [targets, setTargets] = useState<RevenueTargets | null>(null);
  const [failed, setFailed] = useState(false);
  const [team, setTeam] = useState<Revenue | null>(null);
  const [org, setOrg] = useState("");
  const [own, setOwn] = useState<Record<string, string>>({});
  const [typical, setTypical] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const read = await readRevenueTargets(month, controller.signal);
        if (controller.signal.aborted) return;
        setTargets(read);
        setFailed(false);
        setOrg(read.organisation ? String(read.organisation) : "");
        setOwn(
          Object.fromEntries(
            read.sellers.map((line) => [
              line.person_id,
              line.own ? String(line.own) : "",
            ]),
          ),
        );
        setTypical(read.typical_deal ? String(read.typical_deal) : "");
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    })();
    return () => controller.abort();
  }, [month]);

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
  if (!targets) return <div className={styles.detail} aria-busy="true" />;

  const manage = targets.can_manage;
  const orgAmount = org.trim() === "" ? 0 : amountOf(org);
  const changedOwn = targets.sellers
    .filter(
      (line) =>
        (own[line.person_id] ?? "") !== (line.own ? String(line.own) : ""),
    )
    .map((line) => {
      const text = own[line.person_id] ?? "";
      return {
        person_id: line.person_id,
        amount: text.trim() === "" ? 0 : amountOf(text),
      };
    });
  const invalid =
    orgAmount === null || changedOwn.some((line) => line.amount === null);
  const orgChanged =
    manage && (orgAmount ?? -1) !== (targets.organisation ?? 0);
  const dirty = orgChanged || changedOwn.length > 0;
  // A seller sees only their own line, and edits it where the workspace allows.
  const editable = manage || targets.sellers_set_own;
  const chain = month === this_ && team ? takesChain(team) : null;

  const save = async () => {
    if (invalid || !dirty || saving) return;
    setSaving(true);
    try {
      const saved = await saveRevenueTargets(month, {
        ...(orgChanged ? { organisation: orgAmount ?? 0 } : {}),
        ...(changedOwn.length
          ? {
              sellers: changedOwn.map((line) => ({
                person_id: line.person_id,
                amount: line.amount ?? 0,
              })),
            }
          : {}),
      });
      setTargets(saved);
      notify({
        id: "revenue-target",
        tone: "success",
        title: `${monthName(month)} target saved`,
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
      const saved = await saveRevenueSettings(
        targets.revision,
        setOwnNext,
        deal,
      );
      setTargets(saved);
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
      <div className={styles.months} role="group" aria-label="Month">
        {[this_, next].map((value) => (
          <button
            key={value}
            type="button"
            className={styles.monthChip}
            aria-pressed={month === value}
            onClick={() => setMonth(value)}
          >
            {monthName(value)}
          </button>
        ))}
      </div>
      {chain ? <p className={styles.takesLine}>{chain}</p> : null}
      <div className={styles.group}>
        <label className={styles.row}>
          <span className={styles.rowLabel}>Organisation</span>
          <input
            className={styles.input}
            inputMode="decimal"
            placeholder="₹12 L"
            value={org}
            disabled={!manage}
            aria-invalid={orgAmount === null}
            onChange={(event) => setOrg(event.target.value)}
          />
        </label>
        {targets.sellers.map((line) => (
          <label key={line.person_id} className={styles.row}>
            <span className={styles.rowLabel}>
              {line.name}
              {line.split && !own[line.person_id] ? (
                <small>Even share {inr(line.split)}</small>
              ) : null}
            </span>
            <input
              className={styles.input}
              inputMode="decimal"
              placeholder={line.split ? inr(line.split) : "—"}
              value={own[line.person_id] ?? ""}
              disabled={!editable}
              aria-invalid={
                (own[line.person_id] ?? "").trim() !== "" &&
                amountOf(own[line.person_id] ?? "") === null
              }
              onChange={(event) =>
                setOwn((current) => ({
                  ...current,
                  [line.person_id]: event.target.value,
                }))
              }
            />
          </label>
        ))}
      </div>
      {manage || targets.sellers_set_own ? (
        <button
          type="button"
          className={styles.save}
          disabled={!dirty || invalid || saving}
          aria-busy={saving || undefined}
          onClick={() => void save()}
        >
          Save {monthName(month)}
        </button>
      ) : null}
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
              aria-checked={targets.sellers_set_own}
              aria-labelledby="revenue-set-own"
              onClick={() =>
                void saveSettings(!targets.sellers_set_own, typical)
              }
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
                const was = targets.typical_deal
                  ? String(targets.typical_deal)
                  : "";
                if (typical !== was)
                  void saveSettings(targets.sellers_set_own, typical);
              }}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}
