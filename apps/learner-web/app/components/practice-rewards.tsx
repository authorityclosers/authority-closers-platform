"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { LearningSymbol } from "@ac/ui";
import { ArrowRight, Check, ChevronRight, X } from "lucide-react";
import type { PracticeProgress } from "../lib/practice-engine-api";
import styles from "./practice-rewards.module.css";

type Panel = "credits" | "experience" | "rhythm";
const labels: Record<Panel, string> = {
  credits: "Earned credits",
  experience: "Practice XP",
  rhythm: "Your practice week",
};
const format = (value: number) => value.toLocaleString("en");

/** Presentation of confirmed journal data. Opening a panel never grants a reward. */
export function PracticeRewards({
  progress,
  timezoneControls,
}: {
  progress: PracticeProgress;
  timezoneControls: ReactNode;
}) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [activity, setActivity] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const id = useId();
  const days = progress.actual_practice_days_this_week;
  const pilot = progress.policy_version === "arcade-earned-pilot-2026-09-08-v1";
  useEffect(() => {
    if (!panel) return;
    const surface = dialog.current;
    const previousOverflow = document.body.style.overflow;
    surface?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
      surface?.close();
      trigger.current?.focus({ preventScroll: true });
    };
  }, [panel]);
  const open = (next: Panel, button: HTMLButtonElement) => {
    trigger.current = button;
    setActivity(false);
    setPanel(next);
  };
  return (
    <>
      <div className={styles.stats} aria-label="Practice rewards and activity">
        {(
          [
            [
              "credits",
              progress.credits_balance,
              "Earned credits",
              "Your reward wallet",
            ],
            [
              "experience",
              progress.xp_total,
              "Practice XP",
              "Every rep counts",
            ],
            ["rhythm", days, "Practice days", "This week"],
          ] as const
        ).map(([kind, value, label, hint]) => (
          <button
            key={kind}
            type="button"
            className={styles.stat}
            data-tone={kind}
            aria-label={`${format(value)} ${label.toLowerCase()}. View details`}
            aria-haspopup="dialog"
            aria-expanded={panel === kind}
            aria-controls={panel === kind ? id : undefined}
            onClick={(event) => open(kind, event.currentTarget)}
          >
            <span className={styles.symbol}>
              <LearningSymbol kind={kind} size={54} />
            </span>
            <span className={styles.value}>{format(value)}</span>
            <span className={styles.label}>{label}</span>
            <span className={styles.hint}>
              {hint} <ChevronRight size={12} />
            </span>
          </button>
        ))}
      </div>
      <div className={styles.week}>
        <button
          className={styles.weekCopy}
          type="button"
          aria-label="View your week"
          aria-describedby={`${id}-week-state`}
          aria-haspopup="dialog"
          aria-expanded={panel === "rhythm"}
          aria-controls={panel === "rhythm" ? id : undefined}
          onClick={(event) => open("rhythm", event.currentTarget)}
        >
          <strong>Weekly target</strong>
          <span>{Math.min(3, days)} of 3 days</span>
        </button>
        <span id={`${id}-week-state`} className="sr-only">
          {Math.min(3, days)} of 3 practice days this week.
          {pilot ? " 40-credit weekly bonus." : ""}
        </span>
        <span
          className={styles.steps}
          role="progressbar"
          aria-label="Practice days towards the weekly bonus"
          aria-valuemin={0}
          aria-valuemax={3}
          aria-valuenow={Math.min(3, days)}
        >
          {[1, 2, 3].map((day) => (
            <span key={day} data-filled={days >= day} aria-hidden="true">
              {days >= day ? <Check size={15} strokeWidth={3} /> : day}
            </span>
          ))}
        </span>
        {pilot ? (
          <span className={styles.bonus}>
            +40<small>credits</small>
          </span>
        ) : (
          <ChevronRight size={18} />
        )}
      </div>
      {panel ? (
        <dialog
          ref={dialog}
          id={id}
          className={styles.dialog}
          data-tone={panel}
          aria-labelledby={`${id}-title`}
          onCancel={(event) => {
            event.preventDefault();
            setPanel(null);
          }}
          onClose={() => setPanel(null)}
        >
          <header className={styles.dialogHeader}>
            <div className={styles.symbol}>
              <LearningSymbol kind={panel} size={54} />
            </div>
            <div>
              <p className={styles.eyebrow}>Your practice</p>
              <h2 id={`${id}-title`}>{labels[panel]}</h2>
            </div>
            <button
              type="button"
              className={styles.close}
              aria-label="Close reward details"
              onClick={() => setPanel(null)}
            >
              <X size={20} />
            </button>
          </header>
          <div className={styles.dialogBody}>
            <div className={styles.rewardHero}>
              <p className={styles.balance}>
                <strong>
                  {format(
                    panel === "credits"
                      ? progress.credits_balance
                      : panel === "experience"
                        ? progress.xp_total
                        : days,
                  )}
                </strong>
                <span>
                  {panel === "credits"
                    ? "credits earned"
                    : panel === "experience"
                      ? "confirmed practice XP"
                      : "practice days this week"}
                </span>
              </p>
              <div className={styles.heroSymbol}>
                <LearningSymbol kind={panel} size={132} />
              </div>
            </div>
            {panel !== "rhythm" ? (
              <div
                className={styles.viewSwitch}
                role="group"
                aria-label="Reward detail view"
              >
                <button
                  type="button"
                  aria-pressed={!activity}
                  onClick={() => setActivity(false)}
                >
                  Overview
                </button>
                <button
                  type="button"
                  aria-pressed={activity}
                  onClick={() => setActivity(true)}
                >
                  Reward activity
                </button>
              </div>
            ) : null}
            {panel === "rhythm" ? (
              <>
                <div
                  className={styles.questTrail}
                  aria-label={`${Math.min(3, days)} of 3 weekly practice days completed`}
                >
                  {[1, 2, 3].map((day) => (
                    <span key={day} data-filled={days >= day}>
                      <span>{days >= day ? <Check size={22} /> : day}</span>
                      <small>Day {day}</small>
                    </span>
                  ))}
                  {pilot ? (
                    <strong>
                      +40<small>credits</small>
                    </strong>
                  ) : null}
                </div>
                <p>
                  {pilot
                    ? "Complete a practice on three different days in the same week to earn 40 bonus credits. They don’t have to be consecutive."
                    : "Each day you complete a practice is a day you showed up."}
                </p>
                <p>
                  This is your weekly activity, not a consecutive-day streak.
                </p>
                <section
                  className={styles.timezone}
                  aria-label="Practice timezone settings"
                >
                  {timezoneControls}
                </section>
              </>
            ) : (
              <>
                {!activity ? (
                  <section className={styles.rule}>
                    <h3>
                      {panel === "credits"
                        ? "Made to be earned"
                        : "Effort worth recognising"}
                    </h3>
                    <p>
                      {pilot
                        ? `Your first two different practice families each day earn ${panel === "credits" ? "10 credits and 30 XP each" : "30 XP each"}. Complete the prompts and acknowledge the feedback. A perfect answer isn’t required.`
                        : "Rewards are confirmed when an eligible practice is complete."}
                    </p>
                    <p>
                      {panel === "credits"
                        ? "Replays and hints are free. You can’t buy credits, and leaving a practice won’t take earned credits away."
                        : "Practice XP recognises participation. It is separate from course progress, assessments and certificates."}
                    </p>
                    {pilot ? (
                      <div className={styles.ruleSteps}>
                        <span>
                          <strong>1</strong>Complete a practice
                        </span>
                        <span>
                          <strong>2</strong>Read the feedback
                        </span>
                        <span>
                          <strong>3</strong>
                          {panel === "credits" ? "+10 credits" : "+30 XP"}
                        </span>
                      </div>
                    ) : null}
                    <Link
                      className={styles.primaryAction}
                      href="/practice#practice-library-title"
                      onClick={() => setPanel(null)}
                    >
                      Find your next practice <ArrowRight size={17} />
                    </Link>
                  </section>
                ) : null}
                {activity ? (
                  <section aria-labelledby={`${id}-history`}>
                    <h3 id={`${id}-history`}>Your recent rewards</h3>
                    {progress.recent_awards.length ? (
                      <ul className={styles.history}>
                        {progress.recent_awards.map((award) => (
                          <li key={award.id}>
                            <span>
                              <strong>
                                {award.kind === "weekly_rhythm"
                                  ? "Three-day rhythm"
                                  : "Practice complete"}
                              </strong>
                              <small>
                                {new Date(
                                  `${award.local_day}T12:00:00Z`,
                                ).toLocaleDateString("en", {
                                  month: "short",
                                  day: "numeric",
                                  timeZone: "UTC",
                                })}
                              </small>
                            </span>
                            <span className={styles.award}>
                              +{format(award.credits)} credits
                              {award.xp ? ` · +${format(award.xp)} XP` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className={styles.empty}>
                        Your first reward belongs here. Finish an eligible
                        practice and read its feedback to get started.
                      </p>
                    )}
                  </section>
                ) : null}
                {panel === "experience" ? (
                  <Link className={styles.link} href="/leaderboard">
                    View your academy leaderboard <ArrowRight size={16} />
                  </Link>
                ) : null}
              </>
            )}
          </div>
        </dialog>
      ) : null}
    </>
  );
}
