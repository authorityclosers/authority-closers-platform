"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  ActionButton,
  actionClassName,
  FocusSession,
  LearningSymbol,
  PracticeCompanion,
  PRACTICE_COMPANIONS,
  type PracticeCompanionKind,
  RewardReveal,
  SessionStep,
} from "@ac/ui";
import { ArrowRight, LoaderCircle, X } from "lucide-react";
import {
  createPracticeSoundPlayer,
  readPracticeSounds,
  readPracticeVolume,
  subscribePracticeSounds,
  type PracticeSoundPlayer,
} from "../lib/practice-sounds";
import {
  readPracticeCompanion,
  savePracticeCompanion,
  subscribePracticeCompanion,
} from "../lib/practice-presentation";
import {
  practiceApi,
  PracticeRequestError,
  type PracticeSet,
} from "../lib/practice-api";
import {
  practiceEngineApi,
  PracticeEngineRequestError,
  type PracticeAttempt,
  type PracticeEngineApi,
  type PracticeProfile,
  type PracticeProgress,
} from "../lib/practice-engine-api";
import {
  PracticeQuestion,
  type PracticeEditorialResult,
} from "./practice-arcade";
import styles from "./practice-engine.module.css";
import { PracticeCompanionStage } from "./practice-companion-stage";
import { PracticeSoundControls } from "./practice-sound-controls";
import {
  usePracticeFocus,
  PracticeFocusStatus,
  PracticeFocusEnd,
} from "./practice-focus";
import type { PracticeFocusApi } from "../lib/practice-focus-api";

const newKey = () => crypto.randomUUID();
const setHref = (id: string) => `/practice?set=${encodeURIComponent(id)}`;
const attemptHref = (setId: string, id: string) =>
  `${setHref(setId)}&attempt=${encodeURIComponent(id)}`;
const number = (value: number) => value.toLocaleString("en");

export function isPracticeTimezone(value: string) {
  if (!/^[A-Za-z0-9_+./-]{1,64}$/.test(value)) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

const rejectedInput = (reason: unknown) =>
  reason instanceof PracticeEngineRequestError &&
  (reason.status === 400 || reason.status === 422);

function Failure({ error, retry }: { error: unknown; retry: () => void }) {
  const status =
    error instanceof PracticeEngineRequestError ||
    error instanceof PracticeRequestError
      ? error.status
      : 0;
  const signIn = status === 401;
  const unavailable = status === 403 || status === 404;
  return (
    <div className={styles.error} role="alert">
      <p>
        {signIn
          ? "Sign in again to open your saved practice."
          : unavailable
            ? "This practice isn’t available to your account. Your other academy activities are still there."
            : "Practice couldn’t connect. Your saved work is still there."}
      </p>
      {signIn ? (
        <Link className={actionClassName("secondary")} href="/login">
          Sign in
        </Link>
      ) : unavailable ? (
        <Link
          className={actionClassName("secondary")}
          href={status === 403 ? "/home" : "/practice"}
        >
          {status === 403 ? "Back to academy" : "Back to practice"}
        </Link>
      ) : (
        <ActionButton variant="secondary" onClick={retry}>
          Try again
        </ActionButton>
      )}
    </div>
  );
}

function RewardsExplainer() {
  return (
    <details className={styles.explainer}>
      <summary>How practice rewards work</summary>
      <p>
        Earn 10 credits and 30 XP for each of your first two eligible practice
        families each day. Complete every prompt and read its feedback. You
        don’t need a perfect answer.
      </p>
      <p>
        Practise on three days in the same week to earn a further 40 credits.
        Replays and hints are free. Credits cannot be purchased, and leaving a
        game does not take any away.
      </p>
      <p>
        Practice rewards are separate from course progress, assessments and
        certificates.
      </p>
    </details>
  );
}

function TimezoneInput({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <label className={styles.timezone}>
      <span>Your practice timezone</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
        placeholder="For example, Asia/Kolkata"
        list="practice-timezones"
        maxLength={80}
      />
      <datalist id="practice-timezones">
        {[
          "Asia/Kolkata",
          "UTC",
          "Asia/Dubai",
          "Asia/Singapore",
          "Europe/London",
          "Europe/Paris",
          "America/New_York",
          "America/Chicago",
          "America/Los_Angeles",
          "Australia/Sydney",
        ].map((zone) => (
          <option key={zone} value={zone} />
        ))}
      </datalist>
      <small>
        Daily rewards follow this timezone. Later changes take effect at the
        start of the next week.
      </small>
    </label>
  );
}

/** A read-only view of server journal totals, never a locally incremented wallet. */
export function PracticeRecognition({
  api = practiceEngineApi,
}: {
  api?: PracticeEngineApi;
}) {
  const [progress, setProgress] = useState<PracticeProgress | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [epoch, setEpoch] = useState(0);
  const [editZone, setEditZone] = useState(false);
  const [zone, setZone] = useState("");
  const [saving, setSaving] = useState(false);
  const [zoneLocked, setZoneLocked] = useState(false);
  const [zoneInvalid, setZoneInvalid] = useState(false);
  const pending = useRef<{
    body: { timezone: string; expected_revision: number };
    key: string;
  } | null>(null);
  const busy = useRef(false);
  const saveRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void api
      .progress(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setProgress(value);
          setZone(value.profile.timezone ?? "");
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason);
      });
    return () => controller.abort();
  }, [api, epoch]);
  useEffect(() => () => saveRequest.current?.abort(), []);
  const saveZone = async () => {
    if (!progress || busy.current || !zone.trim()) return;
    if (!pending.current && !isPracticeTimezone(zone.trim())) {
      setZoneInvalid(true);
      return;
    }
    busy.current = true;
    setSaving(true);
    setError(null);
    setZoneInvalid(false);
    pending.current ??= {
      body: {
        timezone: zone.trim(),
        expected_revision: progress.profile.revision,
      },
      key: newKey(),
    };
    setZoneLocked(true);
    const controller = new AbortController();
    saveRequest.current = controller;
    try {
      const profile = await api.updateProfile(
        pending.current.body,
        pending.current.key,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setProgress({ ...progress, profile });
        pending.current = null;
        setZoneLocked(false);
        setEditZone(false);
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (rejectedInput(reason)) {
          pending.current = null;
          setZoneLocked(false);
          setZoneInvalid(true);
        } else setError(reason);
      }
    } finally {
      if (!controller.signal.aborted) {
        busy.current = false;
        setSaving(false);
      }
    }
  };
  if (!progress)
    return error ? (
      <Failure error={error} retry={() => setEpoch((n) => n + 1)} />
    ) : (
      <div className={styles.walletLoading} role="status">
        Loading your practice…
      </div>
    );
  const active = progress.recent_attempts.find(
    (attempt) => attempt.state === "in_progress",
  );
  return (
    <section className={styles.recognition} aria-label="Your saved practice">
      <div className={styles.wallet}>
        <div>
          <LearningSymbol kind="credits" size={46} />
          <p>
            <strong>{number(progress.credits_balance)}</strong>
            <span>Earned credits</span>
          </p>
        </div>
        <div>
          <LearningSymbol kind="experience" size={46} />
          <p>
            <strong>{number(progress.xp_total)}</strong>
            <span>Practice XP</span>
          </p>
        </div>
        <div>
          <LearningSymbol kind="rhythm" size={46} />
          <p>
            <strong>{progress.actual_practice_days_this_week}</strong>
            <span>Practice days this week</span>
          </p>
        </div>
      </div>
      <div className={styles.rhythm}>
        <p>
          <strong>Make room for a little practice.</strong>
          <span>Three practice days in a week earn 40 bonus credits.</span>
        </p>
        <div
          className={styles.rhythmSteps}
          role="progressbar"
          aria-label="Practice days towards the weekly bonus"
          aria-valuemin={0}
          aria-valuemax={3}
          aria-valuenow={Math.min(3, progress.actual_practice_days_this_week)}
        >
          {[1, 2, 3].map((day) => (
            <span
              key={day}
              aria-hidden="true"
              data-filled={progress.actual_practice_days_this_week >= day}
            />
          ))}
        </div>
      </div>
      {active ? (
        <Link
          className={styles.resume}
          href={attemptHref(active.set_id, active.id)}
        >
          <span>
            <strong>Pick up where you left off</strong>
            <small>
              {active.title} · {active.acknowledged_count} of{" "}
              {active.item_count} prompts saved
            </small>
          </span>
          <ArrowRight size={20} aria-hidden="true" />
        </Link>
      ) : null}
      <RewardsExplainer />
      {progress.recent_awards.length ? (
        <details className={styles.explainer}>
          <summary>Your recent rewards</summary>
          <ul className={styles.rewardHistory}>
            {progress.recent_awards.slice(0, 5).map((award) => (
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
                <span>
                  +{number(award.credits)} credits
                  {award.xp ? ` · +${number(award.xp)} XP` : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className={styles.zoneSummary}>
        <span>
          {progress.profile.timezone
            ? `Practice timezone: ${progress.profile.timezone}`
            : "Choose your timezone when you start your first practice."}
        </span>
        <ActionButton
          variant="quiet"
          onClick={() => setEditZone((value) => !value)}
          disabled={saving}
        >
          Change timezone
        </ActionButton>
      </div>
      {progress.profile.pending_timezone ? (
        <p className={styles.note} role="status">
          {progress.profile.pending_timezone} is scheduled for{" "}
          {new Date(progress.profile.pending_effective_at!).toLocaleDateString(
            "en",
            {
              dateStyle: "medium",
              timeZone: progress.profile.timezone ?? "UTC",
            },
          )}
          .
        </p>
      ) : null}
      {editZone ? (
        <div className={styles.zoneEditor}>
          <TimezoneInput
            value={zone}
            onChange={setZone}
            disabled={saving || zoneLocked}
          />
          <ActionButton
            onClick={() => void saveZone()}
            disabled={saving || !zone.trim()}
          >
            {saving ? "Saving…" : "Save timezone"}
          </ActionButton>
          {zoneInvalid ? (
            <p role="alert">
              Choose a valid timezone, such as Asia/Kolkata, then save again.
            </p>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <div className={styles.error} role="alert">
          <p>
            That change could not be confirmed. Retry the same change, or reload
            your saved preferences.
          </p>
          <ActionButton
            variant="quiet"
            onClick={() => {
              pending.current = null;
              setZoneLocked(false);
              setZoneInvalid(false);
              setEpoch((n) => n + 1);
            }}
          >
            Reload saved preferences
          </ActionButton>
        </div>
      ) : null}
    </section>
  );
}

export function PracticeEngine({
  setId,
  attemptId,
  api = practiceEngineApi,
  contentApi = practiceApi,
  defaultCompanion = "echo",
  focusApi,
}: {
  setId: string;
  attemptId?: string;
  api?: PracticeEngineApi;
  contentApi?: Pick<typeof practiceApi, "set">;
  defaultCompanion?: PracticeCompanionKind;
  focusApi?: PracticeFocusApi;
}) {
  const selectedCompanion = useSyncExternalStore(
    subscribePracticeCompanion,
    readPracticeCompanion,
    () => null,
  );
  const companion = selectedCompanion ?? defaultCompanion;
  const soundPlayer = useRef<PracticeSoundPlayer | null>(null);
  const [freshCompletion, setFreshCompletion] = useState(false);
  useEffect(() => {
    const player = createPracticeSoundPlayer();
    soundPlayer.current = player;
    const sync = () => {
      player.setEnabled(readPracticeSounds());
      player.setVolume(readPracticeVolume());
    };
    sync();
    const unsubscribe = subscribePracticeSounds(sync);
    const visibility = () => {
      if (document.visibilityState !== "visible") player.stop();
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      unsubscribe();
      document.removeEventListener("visibilitychange", visibility);
      player.dispose();
      if (soundPlayer.current === player) soundPlayer.current = null;
    };
  }, []);
  const interact = (kind: "select" | "submit") => {
    soundPlayer.current?.prepare();
    if (kind === "select") soundPlayer.current?.play("select");
  };
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null);
  const focus = usePracticeFocus(attempt, focusApi);
  const current = useRef<PracticeAttempt | null>(null);
  const [set, setSet] = useState<PracticeSet | null>(null);
  const [profile, setProfile] = useState<PracticeProfile | null>(null);
  const [progress, setProgress] = useState<PracticeProgress | null>(null);
  const [zone, setZone] = useState("");
  const [epoch, setEpoch] = useState(0);
  const [syncEpoch, setSyncEpoch] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const [startLocked, setStartLocked] = useState(false);
  const [zoneInvalid, setZoneInvalid] = useState(false);
  const [startConflict, setStartConflict] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [exitOpen, setExitOpen] = useState(false);
  const exitDialog = useRef<HTMLDialogElement>(null);
  const exitButton = useRef<HTMLButtonElement>(null);
  const finishHeading = useRef<HTMLHeadingElement>(null);
  const operation = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const startPlan = useRef<{
    zone: string;
    profileRevision: number;
    profileKey: string;
    issueKey: string;
  } | null>(null);
  const commandKeys = useRef(new Map<string, string>());
  const install = (value: PracticeAttempt) => {
    if (value.set_id !== setId)
      throw new Error("Practice attempt does not match this set");
    current.current = value;
    setAttempt(value);
  };
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      if (attemptId) {
        const value = await api.attempt(attemptId, controller.signal);
        if (!controller.signal.aborted) install(value);
      } else {
        const [value, content] = await Promise.all([
          api.progress(controller.signal),
          contentApi.set(setId, controller.signal),
        ]);
        if (!controller.signal.aborted) {
          setProgress(value);
          setProfile(value.profile);
          setSet(content);
          // A suggestion only. The explicit start action below saves the chosen timezone.
          setZone(
            value.profile.timezone ??
              Intl.DateTimeFormat().resolvedOptions().timeZone,
          );
        }
      }
      if (!controller.signal.aborted) setError(null);
    };
    void load().catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason);
    });
    return () => controller.abort();
    // install only validates the current set and updates state; it is not a load dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId, attemptId, api, contentApi, epoch]);
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    if (exitOpen) exitDialog.current?.showModal();
  }, [exitOpen]);
  useEffect(() => {
    if (attempt?.state === "completed")
      finishHeading.current?.focus({ preventScroll: true });
  }, [attempt?.state]);
  const keyFor = (kind: string, body: unknown) => {
    const fingerprint = JSON.stringify([kind, body]);
    let key = commandKeys.current.get(fingerprint);
    if (!key) {
      key = newKey();
      commandKeys.current.set(fingerprint, key);
    }
    return key;
  };
  const start = async () => {
    soundPlayer.current?.prepare();
    if (
      !profile ||
      busy.current ||
      startConflict ||
      (!profile.timezone && !zone.trim())
    )
      return;
    if (
      !profile.timezone &&
      !startPlan.current &&
      !isPracticeTimezone(zone.trim())
    ) {
      setZoneInvalid(true);
      return;
    }
    busy.current = true;
    setStarting(true);
    setError(null);
    setZoneInvalid(false);
    const controller = new AbortController();
    operation.current = controller;
    startPlan.current ??= {
      zone: zone.trim(),
      profileRevision: profile.revision,
      profileKey: newKey(),
      issueKey: newKey(),
    };
    setStartLocked(true);
    const plan = startPlan.current;
    let savingProfile = !profile.timezone;
    try {
      if (!profile.timezone) {
        const saved = await api.updateProfile(
          { timezone: plan.zone, expected_revision: plan.profileRevision },
          plan.profileKey,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setProfile(saved);
        savingProfile = false;
      }
      const value = await api.issue(setId, plan.issueKey, controller.signal);
      if (controller.signal.aborted) return;
      install(value);
      window.history.replaceState(
        window.history.state,
        "",
        attemptHref(value.set_id, value.id),
      );
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (savingProfile && rejectedInput(reason)) {
          startPlan.current = null;
          setStartLocked(false);
          setZoneInvalid(true);
        } else {
          setError(reason);
          if (
            reason instanceof PracticeEngineRequestError &&
            reason.status === 409
          )
            setStartConflict(true);
        }
      }
    } finally {
      if (!controller.signal.aborted) {
        busy.current = false;
        setStarting(false);
      }
    }
  };
  const conflict = (reason: unknown) => {
    if (reason instanceof PracticeEngineRequestError && reason.status === 409)
      setNeedsRefresh(true);
    throw reason;
  };
  const refresh = async () => {
    if (!current.current || busy.current) return;
    busy.current = true;
    const controller = new AbortController();
    operation.current = controller;
    try {
      const value = await api.attempt(current.current.id, controller.signal);
      if (!controller.signal.aborted) {
        install(value);
        setNeedsRefresh(false);
        setSyncEpoch((n) => n + 1);
        setError(null);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason);
    } finally {
      if (!controller.signal.aborted) busy.current = false;
    }
  };
  const header = (
    <div className={styles.header}>
      <ActionButton
        ref={exitButton}
        variant="icon"
        aria-label="Leave practice"
        onClick={() => {
          soundPlayer.current?.stop();
          setExitOpen(true);
        }}
      >
        <X size={21} />
      </ActionButton>
      <div className={styles.headerTitle}>
        <span>{attempt?.set.skill ?? set?.skill ?? "Practice Arcade"}</span>
        <strong>{attempt?.set.title ?? set?.title ?? "Getting ready"}</strong>
      </div>
      {attempt ? (
        <span className={styles.savedCount}>
          {attempt.acknowledged_item_ids.length}/{attempt.set.items.length}
        </span>
      ) : null}
      <PracticeSoundControls getPlayer={() => soundPlayer.current} />
      {attempt ? (
        <div
          className={styles.meter}
          role="progressbar"
          aria-label="Prompts saved in this practice"
          aria-valuemin={0}
          aria-valuemax={attempt.set.items.length}
          aria-valuenow={attempt.acknowledged_item_ids.length}
        >
          <span
            style={{
              width: `${(attempt.acknowledged_item_ids.length / attempt.set.items.length) * 100}%`,
            }}
          />
        </div>
      ) : null}
      {needsRefresh ? (
        <div className={styles.conflict} role="alert">
          <span>
            This practice changed in another request. Reload the saved attempt
            before continuing.
          </span>
          <ActionButton variant="secondary" onClick={() => void refresh()}>
            Reload saved attempt
          </ActionButton>
        </div>
      ) : null}
      {attempt?.state !== "completed" ? (
        <PracticeFocusStatus
          focus={focus}
          attempt={attempt}
          onReload={() => {
            focus.reload();
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
  const item = attempt?.set.items.find(
    (value) => !attempt.acknowledged_item_ids.includes(value.id),
  );
  const initialState = attempt?.item_states.find(
    (state) => state.item_id === item?.id,
  );
  const active = progress?.recent_attempts.find(
    (value) => value.set_id === setId && value.state === "in_progress",
  );
  return (
    <FocusSession header={header}>
      {!attempt ? (
        !profile || !set ? (
          error ? (
            <Failure error={error} retry={() => setEpoch((n) => n + 1)} />
          ) : (
            <div className={styles.loading} role="status">
              <LoaderCircle size={24} />
              Getting your practice ready…
            </div>
          )
        ) : (
          <SessionStep
            labelledBy="practice-start-title"
            footer={
              <ActionButton
                onClick={() => void start()}
                disabled={
                  starting ||
                  startConflict ||
                  (!profile.timezone && !zone.trim())
                }
              >
                {starting
                  ? "Getting ready…"
                  : profile.timezone
                    ? "Start a new practice"
                    : "Save timezone & start"}
                <ArrowRight size={18} />
              </ActionButton>
            }
          >
            <section className={styles.start}>
              <PracticeCompanionStage
                variant={companion}
                mood="ready"
                size={132}
                active={!exitOpen}
              />
              <p className={styles.eyebrow}>A few focused minutes</p>
              <h1 id="practice-start-title">{set.title}</h1>
              <p>{set.description}</p>
              <p className={styles.note}>
                {set.items.length} prompts · Your responses and feedback
                acknowledgement will be saved to your academy account.
              </p>
              {active ? (
                <Link
                  className={styles.resume}
                  href={attemptHref(setId, active.id)}
                >
                  <span>
                    <strong>Resume your saved practice</strong>
                    <small>
                      {active.acknowledged_count} of {active.item_count} prompts
                      saved
                    </small>
                  </span>
                  <ArrowRight size={20} />
                </Link>
              ) : null}
              {!profile.timezone ? (
                <TimezoneInput
                  value={zone}
                  onChange={setZone}
                  disabled={starting || startLocked}
                />
              ) : (
                <p className={styles.note}>
                  Daily rewards follow {profile.timezone}.
                </p>
              )}
              <RewardsExplainer />
              <details className={styles.explainer}>
                <summary>Choose your practice companion</summary>
                <div
                  className={styles.companionChoices}
                  role="group"
                  aria-label="Practice companion"
                >
                  {PRACTICE_COMPANIONS.map((choice) => (
                    <button
                      key={choice.id}
                      aria-pressed={companion === choice.id}
                      onClick={() => savePracticeCompanion(choice.id)}
                      title={choice.description}
                    >
                      <PracticeCompanion
                        variant={choice.id}
                        size={80}
                        motion="off"
                      />
                      <span>{choice.name}</span>
                    </button>
                  ))}
                </div>
                <p>
                  Just your companion on this browser. Your academy content and
                  rewards stay the same.
                </p>
              </details>
              {zoneInvalid ? (
                <p className={styles.error} role="alert">
                  Choose a valid timezone, such as Asia/Kolkata, then start
                  again.
                </p>
              ) : null}
              {startConflict ? (
                <div className={styles.error} role="alert">
                  <p>
                    Your saved preferences changed. Reload them before starting.
                  </p>
                  <ActionButton
                    variant="secondary"
                    onClick={() => {
                      startPlan.current = null;
                      setStartLocked(false);
                      setStartConflict(false);
                      setProfile(null);
                      setSet(null);
                      setError(null);
                      setEpoch((n) => n + 1);
                    }}
                  >
                    Reload saved preferences
                  </ActionButton>
                </div>
              ) : error instanceof PracticeEngineRequestError &&
                error.status === 401 ? (
                <Failure error={error} retry={() => void start()} />
              ) : error ? (
                <div className={styles.error} role="alert">
                  We couldn’t confirm that request. Retry using the button
                  below; you won’t receive duplicate rewards.
                </div>
              ) : null}
            </section>
          </SessionStep>
        )
      ) : attempt.state === "completed" ? (
        <SessionStep
          labelledBy="practice-earned-title"
          footer={
            <Link className={actionClassName()} href="/practice">
              Back to practice
              <ArrowRight size={18} />
            </Link>
          }
        >
          <section className={styles.finish}>
            <RewardReveal
              earned={attempt.reward_receipts.length > 0}
              animate={freshCompletion}
            />
            <p className={styles.eyebrow}>Practice saved</p>
            <h1 id="practice-earned-title" ref={finishHeading} tabIndex={-1}>
              One rep closer.
            </h1>
            <p>
              You explored {attempt.set.items.length} prompts and acknowledged
              their feedback. Take one useful idea into your next conversation.
            </p>
            {attempt.reward_receipts.length ? (
              <div
                className={styles.receipts}
                aria-label="Rewards confirmed by your academy"
              >
                {attempt.reward_receipts.map((receipt) => (
                  <div key={receipt.id}>
                    <span>
                      {receipt.kind === "weekly_rhythm"
                        ? "Three-day practice bonus"
                        : "Daily practice reward"}
                    </span>
                    <strong>
                      +{number(receipt.credits)} credits
                      {receipt.xp ? ` · +${number(receipt.xp)} XP` : ""}
                    </strong>
                  </div>
                ))}
              </div>
            ) : (
              <p className={styles.note}>
                Your practice is saved. No new reward was added for this set.
              </p>
            )}
            <p className={styles.note}>
              Practice rewards don’t change your course result or assessment.
            </p>
          </section>
        </SessionStep>
      ) : item ? (
        <PracticeQuestion
          key={`${attempt.id}:${item.id}:${syncEpoch}`}
          item={item}
          setId={setId}
          last={
            attempt.acknowledged_item_ids.length ===
            attempt.set.items.length - 1
          }
          initialState={initialState}
          disabled={needsRefresh || focus.busy || focus.uncertain}
          onInteraction={interact}
          onNext={() => undefined}
          checkResponse={async (selections, signal) => {
            const latest = current.current!;
            const body = {
              item_id: item.id,
              selections,
              expected_revision: latest.revision,
            };
            try {
              const value = await api.respond(
                latest.id,
                body,
                keyFor("respond", body),
                signal,
              );
              if (signal.aborted)
                throw new DOMException("Aborted", "AbortError");
              const savedResponse = value.item_states.find(
                (state) => state.item_id === item.id,
              );
              const feedback = savedResponse?.feedback;
              if (!feedback) throw new Error("Response feedback unavailable");
              install(value);
              if (!exitDialog.current?.open && savedResponse?.response_id)
                soundPlayer.current?.play(
                  "confirm",
                  `response:${savedResponse.response_id}`,
                );
              return feedback as PracticeEditorialResult;
            } catch (reason) {
              return conflict(reason);
            }
          }}
          onAdvance={async (signal) => {
            const latest = current.current!;
            const response = latest.item_states.find(
              (state) => state.item_id === item.id,
            );
            if (
              !response?.response_id ||
              response.feedback?.kind !== "feedback"
            )
              throw new Error(
                "Feedback must be available before acknowledgement",
              );
            const body = { expected_revision: latest.revision };
            try {
              const value = await api.acknowledge(
                latest.id,
                response.response_id,
                body,
                keyFor(`ack:${response.response_id}`, body),
                signal,
              );
              if (signal.aborted) return;
              if (latest.state !== "completed" && value.state === "completed") {
                setFreshCompletion(true);
                if (!exitDialog.current?.open)
                  soundPlayer.current?.play(
                    value.reward_receipts.length ? "reward" : "confirm",
                    `completion:${value.id}`,
                  );
              }
              install(value);
            } catch (reason) {
              conflict(reason);
            }
          }}
        />
      ) : (
        <Failure
          error={new Error("Saved practice state unavailable")}
          retry={() => void refresh()}
        />
      )}
      {attempt && error ? (
        <div className={styles.error} role="alert">
          Saved practice could not be refreshed. Try again when connected.
        </div>
      ) : null}
      {exitOpen ? (
        <dialog
          ref={exitDialog}
          className={styles.exitDialog}
          aria-labelledby="practice-leave-title"
          aria-describedby="practice-leave-description"
          onCancel={(event) => {
            event.preventDefault();
            // Let the native close event restore focus before React unmounts it.
            exitDialog.current?.close();
            exitButton.current?.focus();
          }}
          onClose={() => {
            setExitOpen(false);
            exitButton.current?.focus();
          }}
        >
          <PracticeCompanionStage
            variant={companion}
            mood={attempt?.state === "completed" ? "celebrate" : "pause"}
            size={156}
          />
          <p className={styles.exitEyebrow}>
            {attempt?.state === "in_progress"
              ? `${attempt.acknowledged_item_ids.length} of ${attempt.set.items.length} prompts saved`
              : "At your own pace"}
          </p>
          <h2 id="practice-leave-title">
            {attempt?.state === "completed"
              ? "A good place to finish."
              : "Taking a breather?"}
          </h2>
          <p id="practice-leave-description">
            {attempt?.state === "in_progress"
              ? "Your saved answers will be waiting. Any choice you haven’t checked yet won’t be saved."
              : attempt?.state === "completed"
                ? "Your practice and confirmed rewards are saved. Bring one useful idea into your next conversation."
                : "You can come back and start when you’re ready."}
          </p>
          {attempt?.state === "in_progress" ? (
            <p className={styles.exitReassurance}>
              Finish the set to complete this rep. Your earned credits and XP
              stay yours.
            </p>
          ) : null}
          <div className={styles.exitActions}>
            <ActionButton autoFocus onClick={() => exitDialog.current?.close()}>
              Keep practising
            </ActionButton>
            <Link className={actionClassName("secondary")} href="/practice">
              {focus.active ? "Pause & save · free" : "Leave practice"}
            </Link>
          </div>
          {attempt ? (
            <PracticeFocusEnd
              focus={focus}
              attempt={attempt}
              onReload={() => {
                focus.reload();
                void refresh();
              }}
            />
          ) : null}
        </dialog>
      ) : null}
    </FocusSession>
  );
}
