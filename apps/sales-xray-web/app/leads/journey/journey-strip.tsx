"use client";

/**
 * One line in Lead sources that says where lead stages go, and opens Lead
 * stages (it replaced the old "Lead stages back to Meta" card, 20 Oct).
 */

import { ChevronRight, Route } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Skeleton } from "../../ui/kit";
import { LEADS_PATH } from "../leads-client";
import { call } from "./journey-client";
import styles from "./journey-strip.module.css";

export type JourneySummary = {
  stages: number;
  industry: string | null;
  providersOn: string[];
  needsCheck: number;
  lastDeliveredAt: string | null;
};

const NAMES: Record<string, string> = {
  meta: "Meta",
  google_ads: "Google Ads",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
  microsoft_ads: "Microsoft Ads",
};

/** Only the fields the line needs; anything else (or nothing) shows the plain line. */
export function readSummary(value: unknown): JourneySummary | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<JourneySummary>;
  if (typeof item.stages !== "number" || !Array.isArray(item.providersOn))
    return null;
  return {
    stages: item.stages,
    industry: typeof item.industry === "string" ? item.industry : null,
    providersOn: item.providersOn.filter(
      (id): id is string => typeof id === "string",
    ),
    needsCheck: typeof item.needsCheck === "number" ? item.needsCheck : 0,
    lastDeliveredAt:
      typeof item.lastDeliveredAt === "string" ? item.lastDeliveredAt : null,
  };
}

export function stripLine(summary: JourneySummary): string {
  const parts = [`${summary.stages} stages`];
  if (summary.providersOn.length)
    parts.push(
      `going to ${summary.providersOn.map((id) => NAMES[id] ?? id).join(", ")}`,
    );
  else parts.push("not going to your ads yet");
  if (summary.needsCheck)
    parts.push(
      `${summary.needsCheck} new match${summary.needsCheck === 1 ? "" : "es"} to check`,
    );
  return parts.join(" · ");
}

export function JourneyStrip() {
  const [summary, setSummary] = useState<JourneySummary | null | undefined>(
    undefined,
  );
  useEffect(() => {
    let live = true;
    call<unknown>("/journey/summary")
      .then((next) => {
        if (live) setSummary(readSummary(next));
      })
      .catch(() => {
        if (live) setSummary(null);
      });
    return () => {
      live = false;
    };
  }, []);
  return (
    <Link
      href={`${LEADS_PATH}?tab=stages`}
      scroll={false}
      className={styles.strip}
    >
      <span className={styles.icon} aria-hidden="true">
        <Route size={16} />
      </span>
      <span className={styles.text}>
        <strong>Lead stages back to your ads</strong>
        {summary === undefined ? (
          <Skeleton width={220} height={11} />
        ) : (
          <small>
            {summary
              ? stripLine(summary)
              : "Your ads learn which leads became customers"}
          </small>
        )}
      </span>
      <ChevronRight size={16} className={styles.chevron} aria-hidden="true" />
    </Link>
  );
}
