"use client";

/**
 * Leads' own settings and tools in one menu (owner, 22 Oct 2026: All leads,
 * Team, Lead sources, Lead stages and Add leads at the bottom of the page were
 * "pathetic"). The ⋯ beside the stage tabs opens it, on phones and computers.
 */

import {
  ChartNoAxesCombined,
  FlaskConical,
  Import,
  Plug,
  Route,
  Split,
  UsersRound,
} from "lucide-react";
import type { ReactNode } from "react";

import { ActionList, ActionRow } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import styles from "./leads-menu.module.css";

export type LeadsMenuItem = {
  key: string;
  label: string;
  note: string;
  onPick: () => void;
};

const ICONS: Record<string, ReactNode> = {
  team: <UsersRound size={20} />,
  share: <Split size={20} />,
  numbers: <ChartNoAxesCombined size={20} />,
  sources: <Plug size={20} />,
  stages: <Route size={20} />,
  import: <Import size={20} />,
  test: <FlaskConical size={20} />,
};

const GROUPS = [
  { label: "Set up leads", keys: ["sources", "stages", "team"] },
  { label: "Manage leads", keys: ["share", "import", "numbers", "test"] },
];

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
    <Sheet
      open={open}
      onClose={onClose}
      title="Leads settings"
      wide="center"
      className={styles.sheet}
    >
      <div className={styles.groups}>
        {GROUPS.map((group) => {
          const rows = group.keys.flatMap((key) =>
            items.filter((item) => item.key === key),
          );
          if (!rows.length) return null;
          return (
            <section key={group.label} aria-label={group.label}>
              <h3 className={styles.label}>{group.label}</h3>
              <ActionList label={group.label}>
                {rows.map((item) => (
                  <ActionRow
                    key={item.key}
                    icon={ICONS[item.key]}
                    title={item.label}
                    note={item.note}
                    onClick={item.onPick}
                  />
                ))}
              </ActionList>
            </section>
          );
        })}
      </div>
    </Sheet>
  );
}
