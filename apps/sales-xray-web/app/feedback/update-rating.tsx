"use client";

/**
 * "How is this update?" inside What's new: one tap on a face under the newest
 * update's list of changes. Once answered it says thanks and stays answered on
 * this device.
 */

import { Frown, Meh, Smile } from "lucide-react";
import { useState } from "react";

import { commandId } from "../bug-report/command-id";
import { reportContext } from "../bug-report/device";
import { scrubRoute } from "../bug-report/scrub";
import { tick } from "../ui/haptics";
import { feedbackRequest, postFeedbackRequest } from "./feedback-client";
import styles from "./feedback.module.css";

const KEY = "sx-update-rated";
const FACES = [
  { rating: 1, label: "Not good", Icon: Frown },
  { rating: 2, label: "Okay", Icon: Meh },
  { rating: 3, label: "Great", Icon: Smile },
] as const;

function rated(update: string): number | null {
  try {
    const all = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<
      string,
      number
    >;
    return all[update] ?? null;
  } catch {
    return null;
  }
}

function remember(update: string, rating: number): void {
  try {
    const all = JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Record<
      string,
      number
    >;
    const kept = Object.entries({ ...all, [update]: rating }).slice(-30);
    window.localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // Private mode: it may ask again on the next visit.
  }
}

export function UpdateRating({ update }: { update: string }) {
  const [chosen, setChosen] = useState<number | null>(() =>
    typeof window === "undefined" ? null : rated(update),
  );
  return (
    <div className={styles.update}>
      <p className={styles.updateLabel}>
        {chosen === null
          ? "How is this update?"
          : "Thanks for rating this update."}
      </p>
      <div
        className={styles.updateFaces}
        role="group"
        aria-label="Rate this update"
      >
        {FACES.map(({ rating, label, Icon }) => (
          <button
            key={rating}
            type="button"
            className={styles.updateFace}
            aria-pressed={chosen === rating}
            disabled={chosen !== null}
            onClick={async () => {
              tick();
              setChosen(rating);
              remember(update, rating);
              try {
                await postFeedbackRequest(
                  feedbackRequest({
                    commandId: commandId(),
                    moment: "app_update",
                    kind: "rating",
                    rating,
                    subject:
                      `update:${update.replace(/[^A-Za-z0-9_.:-]/g, "-")}`.slice(
                        0,
                        64,
                      ),
                    route: scrubRoute(window.location.pathname),
                    context: await reportContext(),
                  }),
                );
              } catch {
                // A rating is a nicety: if it fails, nothing else is affected.
              }
            }}
          >
            <Icon size={15} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
