"use client";

/**
 * Leads' own settings and tools in one menu (owner, 22 Oct 2026: All leads,
 * Team, Lead sources, Lead stages and Add leads at the bottom of the page were
 * "pathetic"). The ⋯ beside the stage tabs opens it, on phones and computers.
 */

import {
  ChevronRight,
  FlaskConical,
  Import,
  Plug,
  Route,
  UsersRound,
} from "lucide-react";
import type { ReactNode } from "react";

import { Sheet } from "../ui/sheet";
import styles from "./leads.module.css";

export type LeadsMenuItem = {
  key: string;
  label: string;
  note: string;
  onPick: () => void;
};

const ICONS: Record<string, ReactNode> = {
  team: <UsersRound size={20} />,
  sources: <Plug size={20} />,
  stages: <Route size={20} />,
  import: <Import size={20} />,
  test: <FlaskConical size={20} />,
};

export function LeadsMenu({
  open,
  onClose,
  items,
}: {
  open: boolean;
  onClose: () => void;
  items: LeadsMenuItem[];
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Leads settings" wide="center">
      <ul className={styles.menuList}>
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className={styles.menuRow}
              onClick={item.onPick}
            >
              <span className={styles.menuIcon} aria-hidden="true">
                {ICONS[item.key]}
              </span>
              <span className={styles.menuWords}>
                <strong>{item.label}</strong>
                <small>{item.note}</small>
              </span>
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
