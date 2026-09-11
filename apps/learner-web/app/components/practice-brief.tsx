"use client";
import { useEffect, useId, useRef, useState } from "react";
import {
  ActionButton,
  PracticeCompanion,
  PRACTICE_COMPANIONS,
  type PracticeCompanionKind,
} from "@ac/ui";
import { Info, X } from "lucide-react";
import type { PracticeSet } from "../lib/practice-api";
import { savePracticeCompanion } from "../lib/practice-presentation";
import styles from "./practice-engine.module.css";

/** Secondary information stays available without competing with the start action. */
export function PracticeBrief({
  set,
  timezone,
  companion,
}: {
  set: PracticeSet;
  timezone: string | null;
  companion: PracticeCompanionKind;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const surface = dialog.current;
    const opener = trigger.current;
    const overflow = document.body.style.overflow;
    surface?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      surface?.close();
      opener?.focus({ preventScroll: true });
    };
  }, [open]);
  return (
    <>
      <ActionButton
        ref={trigger}
        variant="quiet"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(true)}
      >
        <Info size={17} /> Practice details
      </ActionButton>
      {open ? (
        <dialog
          ref={dialog}
          id={id}
          className={styles.briefDialog}
          aria-labelledby={`${id}-title`}
          onCancel={(event) => {
            event.preventDefault();
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
        >
          <header>
            <h2 id={`${id}-title`}>Before you play</h2>
            <ActionButton
              variant="icon"
              aria-label="Close practice details"
              onClick={() => setOpen(false)}
            >
              <X size={20} />
            </ActionButton>
          </header>
          <p>{set.description}</p>
          <p>
            Your responses and acknowledged feedback are saved to your academy
            account. Practice is separate from course assessments.
          </p>
          <h3>Your companion</h3>
          <div
            className={styles.companionChoices}
            role="group"
            aria-label="Practice companion"
          >
            {PRACTICE_COMPANIONS.map((choice) => (
              <button
                type="button"
                key={choice.id}
                aria-pressed={companion === choice.id}
                onClick={() => savePracticeCompanion(choice.id)}
                title={choice.description}
              >
                <PracticeCompanion variant={choice.id} size={72} motion="off" />
                <span>{choice.name}</span>
              </button>
            ))}
          </div>
          <p className={styles.note}>
            Companion choice is saved on this browser.
          </p>
          <h3>Practice rewards</h3>
          <p>
            The first two eligible practice families each day earn 10 credits +
            30 XP each after completion and feedback acknowledgement. Three
            practice days in a week earn 40 bonus credits.
          </p>
          <p>
            Replays and hints are free. Leaving never takes earned credits or XP
            away.
          </p>
          {timezone ? (
            <p className={styles.note}>
              Daily rewards follow {timezone}. Change this in the Arcade’s
              practice-week panel.
            </p>
          ) : null}
        </dialog>
      ) : null}
    </>
  );
}
