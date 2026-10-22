"use client";

/**
 * Switches that matter (owner, 23 Oct 2026: "taking leads and not taking
 * leads… still hard to understand from a turn on/off point of view where the
 * user must feel the importance of that, and a popup"). One pattern for every
 * switch whose state changes what happens to someone's work: Taking new
 * leads, Logging calls, AI on calls, lead alerts.
 *
 * - The label names the thing; the line under it says the state in words
 *   ("On: you're receiving new leads"), never just a coloured knob.
 * - Turning it off asks first, in a sheet that says what will happen.
 *   Turning it back on needs no question.
 * - When something else has paused it (work hours), the row says why and
 *   until when, and offers the override when there is one.
 * - The chip (a page header) never flips on a tap: it opens the same row in a
 *   sheet, so a stray tap can't stop someone's leads.
 */

import { useId, useState, type ReactNode } from "react";

import { notify } from "../notice-center";
import { tick } from "./haptics";
import { Button } from "./kit";
import { Sheet } from "./sheet";
import styles from "./state-switch.module.css";

export type SwitchConfirm = {
  /** A question: "Stop taking new leads?" */
  title: string;
  /** What will happen, one plain sentence each. */
  points: string[];
  /** The action, as a verb: "Stop taking leads". */
  confirm: string;
  /** Keeping things as they are: "Keep taking leads". */
  keep: string;
};

export type SwitchHold = {
  /** Paused by something else although the switch is on: "Paused for work hours". */
  title: string;
  /** Why, and until when. */
  reason: string;
  /** The chip's words while paused: "Paused, after hours". */
  chip: string;
  /** A way past the pause, or words saying who can lift it. */
  override?: {
    label: string;
    note?: string;
    confirm: SwitchConfirm;
    run: () => Promise<void>;
  };
  /** When there is no override for this person: who can change it. */
  who?: string;
};

export type StateSwitchProps = {
  icon: ReactNode;
  /** What the switch is: "Taking new leads". */
  label: string;
  /** What ON means, shown where there is room (the sheet). */
  meaning: string;
  /** The state in words. */
  onText: string;
  offText: string;
  /** The chip's words. */
  chipOn: string;
  chipOff: string;
  on: boolean;
  hold?: SwitchHold | null;
  confirmOff: SwitchConfirm;
  /** Saves the new state; a rejection's message is shown. */
  onChange: (next: boolean) => Promise<void>;
  place?: "row" | "chip";
  busy?: boolean;
};

type Step = null | "status" | "off" | "override";

export function StateSwitch(props: StateSwitchProps) {
  const {
    icon,
    label,
    meaning,
    onText,
    offText,
    chipOn,
    chipOff,
    on,
    hold = null,
    confirmOff,
    onChange,
    place = "row",
    busy = false,
  } = props;
  const [step, setStep] = useState<Step>(null);
  const [saving, setSaving] = useState(false);
  const stateId = useId();
  // Paused by something else while the person's own switch is on.
  const held = on ? hold : null;
  const tone = !on ? "off" : held ? "held" : "on";
  const stateText = !on ? offText : held ? held.title : onText;
  const back: Step = place === "chip" ? "status" : null;

  const save = async (run: () => Promise<void>, after: Step) => {
    setSaving(true);
    try {
      await run();
      tick();
      setStep(after);
    } catch (reason) {
      // A corner card, as every error in the app (owner, 29 Sep).
      notify({
        id: `switch-${label}`,
        tone: "error",
        title: `${label} didn't change`,
        message:
          reason instanceof Error && reason.message
            ? reason.message
            : "Not saved. Try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  const flip = () => {
    if (on) setStep("off");
    else void save(() => onChange(true), back);
  };

  const row = (
    <div className={styles.row} data-tone={tone}>
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.words}>
        <strong>{label}</strong>
        <small id={stateId}>
          <span className={styles.dot} aria-hidden="true" />
          {stateText}
        </small>
        {held ? <small className={styles.reason}>{held.reason}</small> : null}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        aria-describedby={stateId}
        className={styles.switch}
        disabled={busy || saving}
        onClick={flip}
      >
        <span aria-hidden="true" />
      </button>
    </div>
  );

  const override = held?.override ? (
    <div className={styles.override}>
      <Button disabled={saving} onClick={() => setStep("override")}>
        {held.override.label}
      </Button>
      {held.override.note ? <small>{held.override.note}</small> : null}
    </div>
  ) : held?.who ? (
    <p className={styles.who}>{held.who}</p>
  ) : null;

  const asking: SwitchConfirm | null =
    step === "off"
      ? confirmOff
      : step === "override" && held?.override
        ? held.override.confirm
        : null;

  const sheet = (
    <Sheet
      open={step !== null}
      onClose={() => setStep(asking ? back : null)}
      title={asking ? asking.title : label}
      footer={
        asking ? (
          <>
            <Button disabled={saving} onClick={() => setStep(back)}>
              {asking.keep}
            </Button>
            <Button
              variant="primary"
              disabled={saving}
              onClick={() =>
                void save(
                  step === "off"
                    ? () => onChange(false)
                    : (held?.override?.run ?? (async () => undefined)),
                  back,
                )
              }
            >
              {saving ? "Saving…" : asking.confirm}
            </Button>
          </>
        ) : undefined
      }
    >
      {asking ? (
        <ul className={styles.points}>
          {asking.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : (
        <div className={styles.status}>
          <p className={styles.meaning}>{meaning}</p>
          {row}
          {override}
        </div>
      )}
    </Sheet>
  );

  if (place === "chip")
    return (
      <>
        <button
          type="button"
          className={styles.chip}
          data-tone={tone}
          aria-haspopup="dialog"
          aria-label={`${label}: ${stateText}`}
          disabled={busy}
          onClick={() => setStep("status")}
        >
          <span className={styles.dot} aria-hidden="true" />
          {!on ? chipOff : held ? held.chip : chipOn}
        </button>
        {sheet}
      </>
    );

  return (
    <div className={styles.place}>
      {row}
      {override}
      {sheet}
    </div>
  );
}
