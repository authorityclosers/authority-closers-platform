/**
 * A screen as named slots (Home studio, 3 Nov 2026: "adding or removing a
 * block on Home, or on any screen, is a config change, not a rewrite").
 *
 * A plan lists a screen's slots in phone order, top to bottom, and how many of
 * the 12 columns each takes from 1024 px. A screen hands in one block per slot
 * it has; a slot whose block is null or missing takes no room and no gap, so a
 * block that has nothing to say (a finish row with no waiting call, the side
 * switch for someone with one side) never leaves a hole.
 *
 *   const HOME = slotPlan(["finish", "scope", "counts", "next"], {
 *     wide: { counts: 7, next: 5 },
 *   });
 *   <SlotLayout plan={HOME} blocks={{ finish, scope, counts, next }} />
 */

import type { CSSProperties, ReactNode } from "react";

import styles from "./slot-layout.module.css";

export type SlotPlan<K extends string> = {
  /** The slots, in phone order. */
  readonly order: readonly K[];
  /** Columns of 12 from 1024 px; a slot left out takes the whole row. */
  readonly wide: Partial<Record<K, number>>;
  /** Space between slots on a phone: "compact" 8 px, "tight" 12 px (the
   *  default), "loose" 24 px. */
  readonly rhythm: "compact" | "tight" | "loose";
};

export function slotPlan<K extends string>(
  order: readonly K[],
  options: {
    wide?: Partial<Record<K, number>>;
    rhythm?: "compact" | "tight" | "loose";
  } = {},
): SlotPlan<K> {
  return { order, wide: options.wide ?? {}, rhythm: options.rhythm ?? "tight" };
}

/** The plan without some slots: a role or a setting that drops a block. */
export function withoutSlots<K extends string>(
  plan: SlotPlan<K>,
  ...gone: K[]
): SlotPlan<K> {
  return { ...plan, order: plan.order.filter((slot) => !gone.includes(slot)) };
}

export function SlotLayout<K extends string>({
  plan,
  blocks,
  className,
  label,
}: {
  plan: SlotPlan<K>;
  blocks: Partial<Record<K, ReactNode>>;
  className?: string;
  /** A name for the group, when the screen has no heading of its own. */
  label?: string;
}) {
  return (
    <div
      className={className ? `${styles.slots} ${className}` : styles.slots}
      data-rhythm={plan.rhythm}
      aria-label={label}
    >
      {plan.order.map((slot) => {
        const block = blocks[slot];
        if (block === null || block === undefined || block === false)
          return null;
        const span = plan.wide[slot];
        return (
          <div
            key={slot}
            className={styles.slot}
            data-area={slot}
            style={span ? ({ "--span": span } as CSSProperties) : undefined}
          >
            {block}
          </div>
        );
      })}
    </div>
  );
}
