"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { useProfileFirstName } from "../profile-first-name";
import styles from "./dashboard-greeting.module.css";

const ROTATE_MS = 5000;

export type GreetingLine = { lead: string; trail: string };

const INITIAL_LINES: GreetingLine[] = [{ lead: "Welcome back", trail: "" }];

// Capture the browser's local hour once, matching the greeting's mount-time
// behavior. useSyncExternalStore keeps the server and hydration snapshots alike.
const subscribeToGreetingHour = () => () => {};
const readGreetingHour = () => new Date().getHours();
const readServerGreetingHour = () => null;

function timeOfDay(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  if (hour >= 17 && hour < 22) return "Good evening";
  return "Working late";
}

/** The rotating greetings, time of day first. The name goes between lead and trail. */
export function greetingLines(hour: number): GreetingLine[] {
  return [
    { lead: timeOfDay(hour), trail: "" },
    { lead: "Welcome back", trail: "" },
    { lead: "Ready for your next call", trail: "?" },
    { lead: "Great to see you", trail: "" },
  ];
}

export function DashboardGreeting() {
  const localHour = useSyncExternalStore(
    subscribeToGreetingHour,
    readGreetingHour,
    readServerGreetingHour,
  );
  const lines = localHour === null ? INITIAL_LINES : greetingLines(localHour);
  const [index, setIndex] = useState(0);
  const name = useProfileFirstName();

  useEffect(() => {
    const reduceMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduceMotion) return;
    const timer = window.setInterval(
      () => setIndex((value) => value + 1),
      ROTATE_MS,
    );
    return () => window.clearInterval(timer);
  }, []);

  const line = lines[index % lines.length];
  return (
    <div className={styles.greeting}>
      <h2 className={styles.title}>
        <span key={index} className={styles.line}>
          {line.lead}
          {name ? (
            <>
              , <span className={styles.name}>{name}</span>
            </>
          ) : null}
          {line.trail}
        </span>
        <span key={`wave-${index}`} className={styles.wave} aria-hidden="true">
          👋
        </span>
      </h2>
      <p className={styles.subtitle}>
        Here are your calls, reports and minutes at a glance.
      </p>
    </div>
  );
}
