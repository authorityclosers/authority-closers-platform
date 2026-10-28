"use client";

import { ArrowLeft, ArrowRight, CircleHelp } from "lucide-react";
import { useEffect, useState } from "react";

import { useWorkspaceAccess } from "../workspace-access";
import { tick } from "../ui/haptics";
import styles from "./assign-sheet.module.css";

const STEPS = [
  {
    title: "Choose how to share",
    text: "Under How, choose Even for equal shares, or Balanced to help sellers with fewer open leads. By source and By city let you choose who gets each group.",
  },
  {
    title: "Pick who gets them",
    text: "Under To, tick the sellers who should get these leads. For a source or city, pick sellers for each group. Leads already assigned stay put unless you choose to move them.",
  },
  {
    title: "Check, then give out",
    text: "The plan shows each seller’s share and any leads that cannot move. Check it, then tap Give out leads. Nothing moves until you tap that button.",
  },
];

function Guide({ person, active }: { person: string | null; active: boolean }) {
  const storageKey = person ? `sx.leads.share-guide.v1:${person}` : null;
  const [step, setStep] = useState<number | null>(() => {
    try {
      return storageKey && localStorage.getItem(storageKey) ? null : 0;
    } catch {
      return 0;
    }
  });
  useEffect(() => {
    if (!active || step === null || !storageKey) return;
    try {
      localStorage.setItem(storageKey, "seen");
    } catch {
      /* Help stays available when storage is off. */
    }
  }, [active, step, storageKey]);
  const go = (next: number | null) => {
    tick();
    setStep(next);
  };
  return (
    <div className={styles.guideArea}>
      <button
        type="button"
        className={styles.guideHelp}
        aria-label="How to share out leads"
        aria-expanded={step !== null}
        onClick={() => go(step === null ? 0 : null)}
      >
        <CircleHelp size={20} aria-hidden="true" />
        How it works
      </button>
      {step !== null ? (
        <section
          className={styles.guide}
          aria-label="Share out leads walkthrough"
        >
          <div
            className={styles.guideProgress}
            aria-label={`Step ${step + 1} of 3`}
          >
            {STEPS.map((item, index) => (
              <span
                key={item.title}
                data-current={index === step || undefined}
              />
            ))}
            <small>{step + 1} of 3</small>
          </div>
          <div role="status" aria-live="polite" aria-atomic="true">
            <strong>{STEPS[step].title}</strong>
            <p>{STEPS[step].text}</p>
          </div>
          <div className={styles.guideActions}>
            <button type="button" onClick={() => go(null)}>
              Skip guide
            </button>
            {step > 0 ? (
              <button
                type="button"
                aria-label="Previous guide step"
                onClick={() => go(step - 1)}
              >
                <ArrowLeft size={18} aria-hidden="true" />
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => go(step === 2 ? null : step + 1)}
            >
              {step === 2 ? "Got it" : "Next"}
              <ArrowRight size={18} aria-hidden="true" />
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** Once per person on this browser; the help icon can always reopen it. */
export function ShareGuide({ active }: { active: boolean }) {
  const access = useWorkspaceAccess();
  const person = access?.context?.personId ?? null;
  return <Guide key={person} person={person} active={active} />;
}
