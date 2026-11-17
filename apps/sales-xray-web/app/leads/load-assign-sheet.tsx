"use client";

/**
 * Assign with each seller's load (owner pick 17 Nov 2026, M1-C: "perfect,
 * needed"; lead-management study 02 §4.4, M3). "Give 12 leads to", each seller
 * with their open and late leads and a bar against the busiest, the lead rules
 * as the last choice, a preview of what changes, then one pill naming the
 * seller. The loads are GET /team/load, read when ticking started
 * (readLoadsSoon); the change is one bulk job with Undo.
 */

import { Search, Shuffle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Avatar } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { commandId, type SellerLoad, type SellerLoads } from "./leads-client";
import {
  failWords,
  leadsWord,
  readLoadsSoon,
  runWithUndo,
  selectionCount,
  selectionRequest,
  type Selection,
} from "./manage-bar";
import styles from "./load-assign-sheet.module.css";

const RULES = "rules";

/** "Rohan Patil" → "Rohan". */
const firstName = (name: string) => displayName(name).split(" ")[0] || name;

/** How many of the ticked leads a seller already has (ids only). */
export function alreadyWith(
  selection: Selection,
  owners: ReadonlyMap<string, string | null>,
  person: string,
): number {
  if (selection.kind !== "ids") return 0;
  return selection.ids.filter((id) => owners.get(id) === person).length;
}

export function LoadAssignSheet({
  open,
  selection,
  side,
  owners,
  onClose,
  onDone,
}: {
  open: boolean;
  selection: Selection;
  side: "inbound" | "cold";
  /** Each ticked lead's owner, as listed: the preview's "already with". */
  owners: ReadonlyMap<string, string | null>;
  onClose: () => void;
  onDone: () => void;
}) {
  const [loads, setLoads] = useState<SellerLoads | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [command] = useState(commandId);
  const count = selectionCount(selection);
  const leads = leadsWord(count);

  useEffect(() => {
    if (!open || loads) return;
    let live = true;
    readLoadsSoon(side).then(
      (next) => {
        if (live) setLoads(next);
      },
      (reason: unknown) => {
        if (live) setFailed(failWords(reason, "Your team didn't load."));
      },
    );
    return () => {
      live = false;
    };
  }, [open, loads, side]);

  // People who work leads now; someone who only still holds leads isn't offered.
  const sellers = useMemo(
    () => (loads?.sellers ?? []).filter((seller) => seller.role !== null),
    [loads],
  );
  const busiest = Math.max(
    1,
    ...sellers.map((seller) => seller.max_open ?? seller.load.open),
    ...sellers.map((seller) => seller.load.open),
  );
  const words = query.trim().toLowerCase();
  const shown = words
    ? sellers.filter((seller) => seller.name.toLowerCase().includes(words))
    : sellers;
  const chosen = sellers.find((seller) => seller.person_id === pick) ?? null;
  const already = chosen ? alreadyWith(selection, owners, chosen.person_id) : 0;

  const give = async () => {
    if (!pick) return;
    setBusy(true);
    try {
      await runWithUndo(
        {
          ...selectionRequest(selection),
          action: "assign",
          person_id: pick === RULES ? null : pick,
        },
        command,
      );
      onDone();
    } catch (reason) {
      notify({
        id: "bulk-job",
        tone: "error",
        title: "Those leads weren't given",
        message: failWords(reason, "Check your connection and try again."),
      });
      setBusy(false);
    }
  };

  const row = (seller: SellerLoad) => {
    const name = displayName(seller.name);
    const on = pick === seller.person_id;
    const width = Math.min(100, Math.round((seller.load.open / busiest) * 100));
    const after =
      on && selection.kind === "ids"
        ? seller.load.open + count - already
        : on
          ? seller.load.open + count
          : null;
    return (
      <li key={seller.person_id}>
        <label className={styles.seller} data-on={on ? "" : undefined}>
          <Avatar name={seller.name} size={40} />
          <span className={styles.who}>
            <span className={styles.name}>{name}</span>
            <span className={styles.load}>
              {`${seller.load.open} open · ${seller.load.late} late`}
              {after !== null ? ` · after: ${after}` : ""}
              {seller.takes_new_leads ? "" : " · not taking new leads"}
            </span>
            <span className={styles.bar} aria-hidden="true">
              <span style={{ width: `${width}%` }} />
            </span>
          </span>
          <input
            type="radio"
            name="give-to"
            className={styles.radio}
            checked={on}
            onChange={() => setPick(seller.person_id)}
          />
        </label>
      </li>
    );
  };

  const pillWords = !pick
    ? "Choose who gets them"
    : pick === RULES
      ? `Share ${leads} by the lead rules`
      : chosen
        ? `Give ${leads} to ${firstName(chosen.name)}`
        : "Choose who gets them";

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={`Give ${leads} to`}
      description="They keep their stage and follow-ups."
      wide="center"
      className={styles.sheet}
      footer={
        <span className={styles.footer}>
          {chosen && selection.kind === "ids" ? (
            <span className={styles.preview} role="status">
              {already
                ? `${count} selected · ${count - already} will change owner · ${already} already with ${firstName(chosen.name)}`
                : `${count} selected · all ${count} will change owner`}
            </span>
          ) : null}
          <button
            type="button"
            className={styles.pill}
            disabled={!pick || busy || (!!chosen && already === count)}
            onClick={() => void give()}
          >
            {busy ? "Giving…" : pillWords}
          </button>
        </span>
      }
    >
      <div className={styles.body} aria-busy={!loads && !failed}>
        {sellers.length > 5 ? (
          <label className={styles.search}>
            <Search size={20} aria-hidden="true" />
            <input
              type="search"
              placeholder="Find a seller"
              aria-label="Find a seller"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        ) : null}
        {failed ? (
          <p className={styles.note}>{failed}</p>
        ) : !loads ? (
          <ul className={styles.list} aria-label="Loading your team">
            {[0, 1, 2].map((key) => (
              <li key={key} className={styles.ghost} />
            ))}
          </ul>
        ) : (
          <ul className={styles.list} aria-label="Sellers">
            {shown.map(row)}
            {words && !shown.length ? (
              <li className={styles.note}>{`Nobody called “${query}”`}</li>
            ) : null}
            <li>
              <label
                className={styles.seller}
                data-on={pick === RULES ? "" : undefined}
              >
                <span className={styles.rulesMark} aria-hidden="true">
                  <Shuffle size={20} />
                </span>
                <span className={styles.who}>
                  <span className={styles.name}>Share between sellers</span>
                  <span className={styles.load}>By your lead rules</span>
                </span>
                <input
                  type="radio"
                  name="give-to"
                  className={styles.radio}
                  checked={pick === RULES}
                  onChange={() => setPick(RULES)}
                />
              </label>
            </li>
          </ul>
        )}
      </div>
    </Sheet>
  );
}
