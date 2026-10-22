"use client";

/**
 * Leads' own settings and tools in one menu (owner, 22 Oct 2026: All leads,
 * Team, Lead sources, Lead stages and Add leads at the bottom of the page were
 * "pathetic"). The ⋯ beside the stage tabs opens it, on phones and computers.
 */

import { FlaskConical, Import, Plug, Route, UsersRound } from "lucide-react";
import type { ReactNode } from "react";

import { ActionList, ActionRow } from "../ui/kit";
import { Sheet } from "../ui/sheet";

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
      <ActionList label="Leads settings">
        {items.map((item) => (
          <ActionRow
            key={item.key}
            icon={ICONS[item.key]}
            title={item.label}
            note={item.note}
            onClick={item.onPick}
          />
        ))}
      </ActionList>
    </Sheet>
  );
}
