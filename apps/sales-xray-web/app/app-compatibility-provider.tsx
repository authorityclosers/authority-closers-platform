"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  type AppConfig,
  type FeatureKey,
  REMIND_AFTER_MS,
  reminderHeld,
  updateState,
  validConfig,
} from "./app-compatibility";
import { BrandMark } from "./shell/brand-lockup";
import { Button } from "./ui/kit";
import styles from "./app-compatibility.module.css";

const FeaturesOff = createContext<readonly FeatureKey[]>([]);
export function useFeatureEnabled(key: FeatureKey): boolean {
  return !useContext(FeaturesOff).includes(key);
}
export function FeatureGate({
  feature,
  children,
}: {
  feature: FeatureKey;
  children: ReactNode;
}) {
  return useFeatureEnabled(feature) ? children : null;
}
export const PLAY_LISTING =
  "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray";
const REMINDER_KEY = "sx-app-update-remind-after";
const NAME = "Sales X-Ray";

/** The product's name never splits at its hyphen (orchestrator, 29 Oct 2026). */
function withName(text: string): ReactNode {
  return text.split(NAME).flatMap((part, index) =>
    index === 0
      ? [part]
      : [
          <span key={index} className={styles.name}>
            {NAME}
          </span>,
          part,
        ],
  );
}

export function UpdateCard({
  required,
  message,
  onLater,
}: {
  required: boolean;
  message?: string | null;
  onLater: () => void;
}) {
  return (
    <main className={styles.screen}>
      <section className={styles.card} aria-labelledby="app-update-title">
        {/* The app's own mark, as its icon on the phone shows it. */}
        <span className={styles.icon}>
          <BrandMark markOnly />
        </span>
        <h1 id="app-update-title">{withName(`Update ${NAME}`)}</h1>
        <p>
          {withName(
            message ||
              (required
                ? `Update the app to keep using ${NAME}.`
                : "A newer version is ready. Update when you have a moment."),
          )}
        </p>
        <a className={styles.update} href={PLAY_LISTING}>
          Open Google Play
        </a>
        {!required && (
          <Button variant="ghost" onClick={onLater}>
            Not now
          </Button>
        )}
      </section>
    </main>
  );
}

export function AppCompatibilityProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [held, setHeld] = useState(false);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    async function refresh() {
      try {
        const response = await fetch("/v1/app/config", {
          credentials: "omit",
          signal: controller.signal,
        });
        if (!response.ok) return;
        const next: unknown = await response.json();
        if (active && validConfig(next)) {
          setConfig(next);
          try {
            setHeld(
              reminderHeld(localStorage.getItem(REMINDER_KEY), Date.now()),
            );
          } catch {
            setHeld(false);
          }
        }
      } catch {
        /* An unreachable config must not block the app. */
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, []);
  const state = config
    ? updateState(
        typeof navigator === "undefined" ? "" : navigator.userAgent,
        config,
      )
    : null;
  const show = state === "required" || (state === "recommended" && !held);
  function later() {
    try {
      localStorage.setItem(REMINDER_KEY, String(Date.now() + REMIND_AFTER_MS));
    } catch {
      /* Still dismiss for this visit. */
    }
    setHeld(true);
  }
  return (
    <FeaturesOff.Provider value={config?.features_off ?? []}>
      {show ? (
        <UpdateCard
          required={state === "required"}
          message={config?.message}
          onLater={later}
        />
      ) : (
        children
      )}
    </FeaturesOff.Provider>
  );
}
