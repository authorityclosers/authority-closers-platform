"use client";

/**
 * Settings → Privacy (owner, 24 Oct 2026, telemetry option B: on by default,
 * a per-person opt-out, and owners and admins can turn it off for the
 * workspace). Usage analytics, in the words of the privacy page's notice; the
 * switches save to /v1/telemetry/preferences (an audit record each time).
 */
import { Activity, Building2, FlaskConical } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { tellPhoneTelemetry } from "../leads/native-phone";
import { telemetry } from "../telemetry";
import { Panel, Skeleton } from "../ui/kit";
import { StateSwitch } from "../ui/state-switch";
import styles from "./sections.module.css";

export type AnalyticsPreferences = {
  notice: { version: string; paragraphs: string[] };
  collecting: boolean;
  sandbox: boolean;
  you: { enabled: boolean; changed_at: string | null };
  workspace: {
    enabled: boolean;
    changed_at: string | null;
    can_change: boolean;
  };
};

const PATH = "/v1/telemetry/preferences";

function parse(body: unknown): AnalyticsPreferences {
  const value = body as Partial<AnalyticsPreferences> | null;
  if (
    !value ||
    typeof value.collecting !== "boolean" ||
    !value.notice ||
    !Array.isArray(value.notice.paragraphs) ||
    !value.you ||
    !value.workspace
  )
    throw new Error("Privacy settings could not be read.");
  return value as AnalyticsPreferences;
}

async function answer(response: Response): Promise<AnalyticsPreferences> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof body?.detail === "string" ? body.detail : "Not saved. Try again.",
    );
  }
  return parse(await response.json());
}

export async function readPreferences(
  signal?: AbortSignal,
): Promise<AnalyticsPreferences> {
  return answer(
    await fetch(PATH, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
  );
}

export async function savePreference(
  scope: "you" | "workspace",
  enabled: boolean,
): Promise<AnalyticsPreferences> {
  const saved = await answer(
    await fetch(`${PATH}/${scope}`, {
      method: "PUT",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ enabled }),
    }),
  );
  // The page's telemetry asks the server again what it may send, and the
  // phone app (its crash reports too) follows the same switch.
  telemetry.refresh();
  await tellPhoneTelemetry(saved.collecting);
  return saved;
}

type Read =
  | { status: "loading" }
  | { status: "ready"; value: AnalyticsPreferences }
  | { status: "failed"; message: string };

export function PrivacySettings() {
  const [read, setRead] = useState<Read>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    readPreferences(controller.signal)
      .then((value) => setRead({ status: "ready", value }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setRead({
            status: "failed",
            message:
              reason instanceof Error ? reason.message : "Couldn't load this.",
          });
      });
    return () => controller.abort();
  }, []);

  const change = (scope: "you" | "workspace") => async (next: boolean) => {
    const value = await savePreference(scope, next);
    setRead({ status: "ready", value });
  };

  if (read.status === "loading")
    return (
      <div className={styles.stack}>
        <Panel title="Usage analytics">
          <Skeleton height={56} />
          <Skeleton height={56} />
        </Panel>
      </div>
    );
  if (read.status === "failed")
    return (
      <div className={styles.stack}>
        <Panel title="Usage analytics">
          <p className={styles.hint}>{read.message}</p>
        </Panel>
      </div>
    );

  const { value } = read;
  return (
    <div className={styles.stack}>
      <Panel title="Usage analytics">
        {value.sandbox ? (
          <div className={styles.note}>
            <span className={styles.noteIcon} aria-hidden="true">
              <FlaskConical size={18} />
            </span>
            <span className={styles.noteText}>
              <strong>Nothing is recorded here</strong>
              <span>This is a sandbox workspace.</span>
            </span>
          </div>
        ) : (
          <>
            <StateSwitch
              icon={<Activity size={18} />}
              label="Help improve Sales X-Ray"
              meaning="Records which screens and report sections you open, your taps and how fast the app responds for you. Never call content, lead names or numbers."
              onText="On: how you use the app helps make it faster"
              offText="Off: nothing about how you use the app is recorded"
              chipOn="Usage analytics on"
              chipOff="Usage analytics off"
              on={value.you.enabled}
              confirmOff={{
                title: "Stop recording how you use the app?",
                points: [
                  "Sales X-Ray stops recording the screens you open, your taps and how fast the app responds for you.",
                  "What was recorded is never used to score you and is deleted after 180 days.",
                ],
                confirm: "Turn off",
                keep: "Keep it on",
              }}
              onChange={change("you")}
            />
            {value.workspace.can_change ? (
              <StateSwitch
                icon={<Building2 size={18} />}
                label="Usage analytics for this workspace"
                meaning="On for everyone in this workspace unless they turn it off for themselves."
                onText="On for everyone here who hasn't turned it off"
                offText="Off: nothing is recorded for anyone in this workspace"
                chipOn="Workspace analytics on"
                chipOff="Workspace analytics off"
                on={value.workspace.enabled}
                confirmOff={{
                  title: "Turn usage analytics off for everyone here?",
                  points: [
                    "Nothing about how anyone in this workspace uses the app is recorded from now on.",
                    "Each person's own switch stays as they set it.",
                  ],
                  confirm: "Turn off for everyone",
                  keep: "Keep it on",
                }}
                onChange={change("workspace")}
              />
            ) : !value.workspace.enabled ? (
              <p className={styles.hint}>
                An owner or admin has turned usage analytics off for this
                workspace, so nothing is recorded here.
              </p>
            ) : null}
          </>
        )}
        <div className={styles.hint}>
          {value.notice.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
          <p>
            <Link href="/privacy">Read the privacy policy</Link>
          </p>
        </div>
      </Panel>
    </div>
  );
}
