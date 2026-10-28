"use client";

import {
  Empty,
  List,
  Meter,
  Panel,
  Row,
  Skeleton,
  SkeletonRow,
} from "@ac/ui/kit";
import {
  BookOpen,
  Play,
  PenLine,
  Wrench,
  MessageSquare,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../lib/learner-api";
import { PracticeEngineRequestError } from "../lib/practice-engine-api";
import { PracticeRequestError } from "../lib/practice-api";
import { type SurfaceState } from "../lib/surface-state";
import { firstActionableActivity } from "../lib/next-learning-action";
import { courseHref, percent, type Course } from "./data";
import styles from "./screens.module.css";

export { styles };

export function useRead<T>(
  read: (signal: AbortSignal) => Promise<T>,
  enabled = true,
) {
  const [epoch, setEpoch] = useState(0);
  // Each answer remembers which read and retry it belongs to, so a new read or a retry shows
  // loading at once without a synchronous setState in the effect.
  const [settled, setSettled] = useState<{
    read?: (signal: AbortSignal) => Promise<T>;
    epoch: number;
    data?: T;
    error?: unknown;
  }>({ epoch: -1 });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void read(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ read, epoch, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setSettled({ read, epoch, error });
      });
    return () => controller.abort();
  }, [read, enabled, epoch]);
  const current = settled.read === read && settled.epoch === epoch;
  return {
    data: current ? settled.data : undefined,
    error: current ? settled.error : undefined,
    loading: !current,
    retry: () => setEpoch((value) => value + 1),
  };
}

export function Screen({
  children,
  state = "DEFAULT",
  retryHref = "/home",
}: {
  children: ReactNode;
  state?: SurfaceState;
  retryHref?: string;
}) {
  return (
    <main id="main-content" tabIndex={-1} className={styles.screen}>
      {state === "PARTIAL" || state === "SUCCESS_FEEDBACK" ? (
        <SimulatedState state={state} retryHref={retryHref} />
      ) : null}
      {children}
    </main>
  );
}

export function Failure({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  const signIn =
    (error instanceof ApiError ||
      error instanceof PracticeRequestError ||
      error instanceof PracticeEngineRequestError) &&
    error.status === 401;
  return (
    <div role="alert">
      <Empty
        link={Link}
        icon={BookOpen}
        title={
          signIn
            ? "Sign in to keep learning."
            : "This couldn’t load. Please try again."
        }
        action={
          signIn
            ? { href: "/login", label: "Sign in" }
            : { onClick: retry, label: "Try again" }
        }
      />
    </div>
  );
}

export function SimulatedState({
  state,
  retryHref,
  signInHref = "/login",
}: {
  state: SurfaceState;
  retryHref: string;
  /** Where Sign in goes; Today keeps the course the learner came for. */
  signInHref?: string;
}) {
  if (state === "DEFAULT" || state === "LOADING") return null;
  const title =
    state === "PARTIAL"
      ? "Some of your learning couldn’t load."
      : state === "SUCCESS_FEEDBACK"
        ? "You’re ready for your next step."
        : state === "EMPTY"
          ? "There’s nothing here yet."
          : state === "OFFLINE"
            ? "Reconnect to keep learning."
            : state === "LOCKED"
              ? "Finish the earlier steps first."
              : state === "PERMISSION_DENIED"
                ? "Sign in to open your learning."
                : "This couldn’t load. Please try again.";
  return (
    <Empty
      link={Link}
      icon={BookOpen}
      title={title}
      action={{
        href: state === "PERMISSION_DENIED" ? signInHref : retryHref,
        label:
          state === "PERMISSION_DENIED"
            ? "Sign in"
            : state === "SUCCESS_FEEDBACK"
              ? "Continue"
              : "Try again",
      }}
    />
  );
}

export function Artwork({ large = false }: { large?: boolean }) {
  // Existing catalogue presentation artwork, never represented as lesson media.
  return (
    <Image
      src="/media/ac-course-hero-v1.png"
      alt=""
      width={large ? 192 : 56}
      height={large ? 128 : 56}
      sizes={large ? "(min-width: 760px) 600px, 100vw" : "56px"}
      className={large ? styles.cover : styles.thumb}
    />
  );
}

export function Progress({ value, title }: { value: number; title: string }) {
  const amount = percent(value);
  return (
    <span className={styles.progress}>
      <Meter value={amount} max={100} label={`${title}: ${amount}% complete`} />
      <small>{amount}% complete</small>
    </span>
  );
}

export function CourseRows({ courses }: { courses: Course[] }) {
  return (
    <List label="Your courses">
      {courses.map(({ summary, learning }) => (
        <Row
          key={summary.enrollment_id}
          link={Link}
          icon={<Artwork />}
          title={summary.program_title}
          href={courseHref(summary.program_slug)}
          meta={[
            learning
              ? (firstActionableActivity(learning)?.title ?? "Open your course")
              : "Course unavailable",
            summary.projection ? (
              <Progress
                key="progress"
                value={summary.projection.percentage}
                title={summary.program_title}
              />
            ) : null,
          ]}
        />
      ))}
    </List>
  );
}

export function KindIcon({ kind }: { kind: string }) {
  const icons: Record<string, typeof BookOpen> = {
    VIDEO: Play,
    REFLECTION: PenLine,
    IMPLEMENTATION_CHALLENGE: Wrench,
    REVIEW: MessageSquare,
    IMPROVE: RotateCcw,
  };
  const Icon = icons[kind.toUpperCase()] ?? BookOpen;
  return <Icon size={20} aria-hidden="true" />;
}

export function WeekDots({ days }: { days: number }) {
  return (
    <div className={styles.week}>
      <p>{days} of 7 days practised this week</p>
      <ol aria-label="Practice days this week">
        {Array.from({ length: 7 }, (_, index) => (
          <li
            key={index}
            data-done={index < days ? "" : undefined}
            aria-label={`Practice day ${index + 1}: ${index < days ? "done" : "still to go"}`}
          >
            <span aria-hidden="true">{index < days ? "✓" : index + 1}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function ScreenSkeleton({
  kind,
  practiceEnabled = false,
}: {
  kind: "today" | "learn" | "explore" | "course" | "module" | "practice";
  practiceEnabled?: boolean;
}) {
  if (kind === "explore")
    return (
      <section
        className={styles.stack}
        role="status"
        aria-label="Loading"
        aria-busy="true"
      >
        <h2>Courses from Closers&apos; Academy</h2>
        <div className={styles.grid}>
          {[0, 1, 2].map((index) => (
            <Panel key={index} title="Course">
              <div className={styles.primaryBody}>
                <Skeleton height={160} />
                <Skeleton width="60%" />
                <Skeleton height={44} />
              </div>
            </Panel>
          ))}
        </div>
      </section>
    );
  return (
    <div
      role="status"
      aria-label="Loading"
      aria-busy="true"
      className={styles.stack}
    >
      {kind === "today" ? (
        <header className={styles.greeting}>
          <Skeleton width="65%" height={26} />
          <Skeleton width="40%" />
        </header>
      ) : null}
      {kind === "course" ? (
        <header className={styles.courseHeader}>
          <Artwork large />
          <Skeleton width="60%" height={26} />
          <Skeleton />
          <Skeleton height={32} />
        </header>
      ) : null}
      {kind === "module" ? (
        <>
          <Skeleton height={44} />
          <Skeleton width="60%" height={26} />
        </>
      ) : null}
      {kind === "course" ? <Skeleton height={48} /> : null}
      {kind === "practice" ? (
        <Panel title="This week">
          <div className={styles.week}>
            <Skeleton height={83} />
          </div>
        </Panel>
      ) : null}
      {kind === "today" || kind === "practice" ? (
        <Panel title={kind === "today" ? "Continue learning" : "Today’s set"}>
          <div
            className={`${styles.primaryBody} ${kind === "today" ? styles.continueBody : ""}`}
          >
            <Skeleton width="75%" height={24} />
            <Skeleton />
            {kind === "today" ? (
              <>
                <Skeleton width="60%" height={20} />
                <Skeleton height={32} />
              </>
            ) : null}
            <Skeleton height={44} />
          </div>
        </Panel>
      ) : null}
      {kind === "today" && practiceEnabled ? (
        <Panel title="Today’s practice">
          <div className={styles.week}>
            <Skeleton height={83} />
          </div>
          <Skeleton height={44} />
        </Panel>
      ) : null}
      <Panel
        title={
          kind === "today"
            ? "Your courses"
            : kind === "practice"
              ? "Available sets"
              : kind === "course"
                ? "Modules"
                : kind === "module"
                  ? "Steps"
                  : "My courses"
        }
      >
        <List>
          {[0, 1, 2].map((index) => (
            <li
              className={`${styles.loadingRow} ${kind === "today" || kind === "learn" ? styles.courseRow : ""}`}
              key={index}
            >
              <SkeletonRow
                avatar={kind === "course" || kind === "module" ? false : 56}
                lines={3}
                end={false}
              />
            </li>
          ))}
        </List>
      </Panel>
    </div>
  );
}
