"use client";

import { useSyncExternalStore } from "react";

import { useProfileFirstName } from "../profile-first-name";
import styles from "./dashboard-greeting.module.css";

// Capture the browser's local hour once. useSyncExternalStore keeps the server
// and hydration snapshots alike ("Welcome back"), then shows the time of day.
const subscribeToGreetingHour = () => () => {};
const readGreetingHour = () => new Date().getHours();
const readServerGreetingHour = () => null;

/** One steady greeting by time of day; it never rotates or moves the page. */
export function greetingFor(hour: number | null): string {
  if (hour === null) return "Welcome back";
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  if (hour >= 17 && hour < 22) return "Good evening";
  return "Working late";
}

export function DashboardGreeting({ subtitle }: { subtitle: string }) {
  const hour = useSyncExternalStore(
    subscribeToGreetingHour,
    readGreetingHour,
    readServerGreetingHour,
  );
  const name = useProfileFirstName();
  return (
    <div className={styles.greeting}>
      <h1 className={styles.title}>
        {greetingFor(hour)}
        {name ? `, ${name}` : ""}
      </h1>
      <p className={styles.subtitle}>{subtitle}</p>
    </div>
  );
}
