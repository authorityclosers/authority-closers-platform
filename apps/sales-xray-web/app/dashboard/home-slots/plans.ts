/**
 * Home's blocks as named slots (Home studio, 4 Nov 2026): Dipak's blocks in his
 * order (docs/handoffs/dipak-home-20261102), then the owner's H5 pick (10 Nov
 * 2026): Today's list and Done today in place of tasks, follow-ups, recent
 * calls and performance. Adding, removing or moving
 * a block is an edit here, not in the screen. From 1024 px the work sits left
 * (seven columns) and what it opens sits right (five). Compact (8 px between
 * blocks on a phone): an owner's busiest Home, with a waiting answer and
 * Cold, keeps its Call above the tab bar on a Redmi (393 x 815 in the app).
 */

import { slotPlan } from "../../ui/slots/slot-layout";

export type SellerSlot = "finish" | "side" | "cards" | "next" | "list" | "done";

export const SELLER_HOME = slotPlan<SellerSlot>(
  ["finish", "side", "cards", "next", "list", "done"],
  {
    wide: {
      cards: 7,
      next: 5,
      list: 7,
      done: 5,
    },
    rhythm: "compact",
  },
);
