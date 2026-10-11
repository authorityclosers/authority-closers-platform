"use client";

import { useSyncExternalStore } from "react";

import { useProfileFirstName } from "../profile-first-name";
import styles from "./dashboard-greeting.module.css";

// The hour in India (the dashboard reads "India time"), the same on the
// server and in the browser, so a page rendered on the server keeps its
// greeting when the app starts (no "Welcome back" swapped for the hour).
const IST_HOUR = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Kolkata",
});
const subscribeToGreetingHour = () => () => {};
const readGreetingHour = () => Number(IST_HOUR.format(new Date()));
const readServerGreetingHour = readGreetingHour;

/** One steady greeting by time of day; it never rotates or moves the page. */
export function greetingFor(hour: number | null): string {
  if (hour === null) return "Welcome back";
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  if (hour >= 17 && hour < 22) return "Good evening";
  return "Working late";
}

export function DashboardGreeting({
  subtitle,
  placeholder = false,
}: {
  subtitle: string;
  /** While the page loads: the title's line, without words that may change. */
  placeholder?: boolean;
}) {
  const hour = useSyncExternalStore(
    subscribeToGreetingHour,
    readGreetingHour,
    readServerGreetingHour,
  );
  const name = useProfileFirstName();
  return (
    <div className={styles.greeting}>
      {placeholder ? (
        <p className={styles.title}>
          <i className={styles.placeholder} aria-hidden="true" />
        </p>
      ) : (
        <h1 className={styles.title}>
          {greetingFor(hour)}
          {name ? `, ${name}` : ""}
        </h1>
      )}
      <p className={styles.subtitle}>{subtitle}</p>
    </div>
  );
}
