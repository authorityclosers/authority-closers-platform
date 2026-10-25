"use client";

/**
 * Leads per seller on All leads (owner, 25 Oct 2026: there was no way to see
 * one seller's assigned leads): Everyone, each seller with their count, and
 * No owner, one tap each. Counts follow the list's other filters when the
 * server sends them (owner_counts); until then each seller's open leads.
 */

import { displayName } from "../display-name";
import { Avatar } from "../ui/kit";
import type { RepView } from "./leads-client";
import styles from "./seller-chips.module.css";

export type SellerPick = { owner: string | null; unassigned: boolean };

export function SellerChips({
  reps,
  counts,
  unassigned,
  pick,
  onPick,
}: {
  reps: readonly RepView[];
  /** Leads per seller id (and "none") for the list's other filters. */
  counts: Readonly<Record<string, number>>;
  /** Leads with no owner, when known. */
  unassigned: number | null;
  pick: SellerPick;
  onPick: (next: SellerPick) => void;
}) {
  const count = (id: string) => counts[id] ?? 0;
  const sellers = [...reps].sort(
    (a, b) => count(b.person_id) - count(a.person_id),
  );
  const none = counts.none ?? unassigned;
  const everyone = Object.values(counts).reduce((sum, value) => sum + value, 0);
  return (
    <div className={styles.strip} role="group" aria-label="Whose leads">
      <button
        type="button"
        className={styles.chip}
        aria-pressed={!pick.owner && !pick.unassigned}
        onClick={() => onPick({ owner: null, unassigned: false })}
      >
        Everyone
        {everyone ? <span className={styles.count}>{everyone}</span> : null}
      </button>
      {sellers.map((rep) => (
        <button
          key={rep.person_id}
          type="button"
          className={styles.chip}
          aria-pressed={pick.owner === rep.person_id}
          aria-label={`${displayName(rep.name)}, ${count(rep.person_id)} leads`}
          onClick={() =>
            onPick({
              owner: pick.owner === rep.person_id ? null : rep.person_id,
              unassigned: false,
            })
          }
        >
          <Avatar name={rep.name} size={24} />
          {displayName(rep.name).split(" ")[0]}
          <span className={styles.count}>{count(rep.person_id)}</span>
        </button>
      ))}
      {none !== null ? (
        <button
          type="button"
          className={styles.chip}
          data-tone={none ? "warn" : undefined}
          aria-pressed={pick.unassigned}
          onClick={() => onPick({ owner: null, unassigned: !pick.unassigned })}
        >
          No owner
          <span className={styles.count}>{none}</span>
        </button>
      ) : null}
    </div>
  );
}
