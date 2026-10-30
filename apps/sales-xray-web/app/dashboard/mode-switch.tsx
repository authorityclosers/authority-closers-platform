"use client";

/**
 * Team | Me (owner, 31 Oct 2026: "a real switch"): a pill thumb that springs
 * across and stretches on its way, a people icon and a person icon, a haptic
 * tick on the phone. The arrow keys move between the two, as in any radio
 * group. No motion when the person asks for less.
 */

import { UserRound, UsersRound } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { tick } from "../ui/haptics";
import styles from "./mode-switch.module.css";

export type HomeMode = "team" | "mine";

const MODES: { key: HomeMode; label: string; icon: typeof UsersRound }[] = [
  { key: "team", label: "Team", icon: UsersRound },
  { key: "mine", label: "Me", icon: UserRound },
];

export function ModeSwitch({
  value,
  onChange,
}: {
  value: HomeMode;
  onChange: (next: HomeMode) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  // The stretch plays on a move, not when the page opens.
  const [moved, setMoved] = useState(false);
  const pick = (next: HomeMode) => {
    if (next === value) return;
    tick();
    setMoved(true);
    onChange(next);
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (
      !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
    )
      return;
    event.preventDefault();
    const next: HomeMode = value === "team" ? "mine" : "team";
    pick(next);
    buttons.current[next === "team" ? 0 : 1]?.focus();
  };
  return (
    <div
      className={styles.switch}
      role="radiogroup"
      aria-label="Home for"
      data-value={value}
      onKeyDown={onKey}
    >
      <span className={styles.thumb} aria-hidden="true">
        {/* Keyed by the choice: each move plays the stretch once. */}
        <span
          key={value}
          className={styles.pill}
          data-moved={moved || undefined}
        />
      </span>
      {MODES.map((mode, index) => {
        const Icon = mode.icon;
        const chosen = mode.key === value;
        return (
          <button
            key={mode.key}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={chosen}
            tabIndex={chosen ? 0 : -1}
            className={styles.option}
            onClick={() => pick(mode.key)}
          >
            <Icon size={16} aria-hidden="true" />
            {mode.label}
          </button>
        );
      })}
    </div>
  );
}
