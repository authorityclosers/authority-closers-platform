/**
 * Home's blocks as named slots (Home studio, 4 Nov 2026): Dipak's eight blocks
 * in his order (docs/handoffs/dipak-home-20261102). Adding, removing or moving
 * a block is an edit here, not in the screen. From 1024 px the work sits left
 * (seven columns) and what it opens sits right (five). Compact (8 px between
 * blocks on a phone): an owner's busiest Home, with a waiting answer and
 * Cold, keeps its Call above the tab bar on a Redmi (393 x 815 in the app).
 */

import { slotPlan } from "../../ui/slots/slot-layout";

export type SellerSlot =
  | "finish"
  | "side"
  | "cards"
  | "next"
  | "tasks"
  | "follow"
  | "recent"
  | "perf";

export const SELLER_HOME = slotPlan<SellerSlot>(
  ["finish", "side", "cards", "next", "tasks", "follow", "recent", "perf"],
  {
    wide: {
      cards: 7,
      next: 5,
      tasks: 6,
      follow: 6,
      recent: 5,
      perf: 7,
    },
    rhythm: "compact",
  },
);
