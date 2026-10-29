"use client";

/** Fictional offline native replies for visual review only; no permission grants or API calls. */
import { useState, useSyncExternalStore } from "react";
import { AutoCapturePanel } from "../../settings/auto-capture-panel";
import { AutoCaptureState } from "../../leads/auto-capture-state";
import { Panel, Skeleton } from "../../ui/kit";
import styles from "./preview.module.css";

const states = ["waiting", "uploading", "analysing", "report_ready"];
// ?state=profile|allowance|network: a call held on the phone and the reason the card leads with.
const holds: Record<string, number> = { profile: 1, allowance: 2, network: 1 };
const noSubscription = () => () => {};
const browser = () => true;

function install() {
  if (typeof window === "undefined") return;
  const state =
    new URLSearchParams(window.location.search).get("state") ?? "off";
  let on = state === "on" || state in holds;
  let wifiOnly = true;
  const listeners = new Set<(event: { data: string }) => void>();
  Object.assign(window, {
    SXPhone: {
      addEventListener: (
        _type: string,
        listener: (event: { data: string }) => void,
      ) => listeners.add(listener),
      postMessage: (data: string) => {
        const request = JSON.parse(data) as {
          id: string;
          method: string;
          args: { on?: boolean; wifiOnly?: boolean };
        };
        if (request.method === "autoCaptureSetup") {
          on = request.args.on === true;
          wifiOnly = request.args.wifiOnly !== false;
        }
        const held = holds[state];
        const result =
          request.method === "autoCaptureStates"
            ? {
                items: [
                  ...states.map((state) => ({
                    eventId: `fictional-${state}`,
                    state,
                  })),
                  ...(held
                    ? [
                        {
                          eventId: "fictional-held",
                          state: "held",
                          hold: state,
                        },
                      ]
                    : []),
                ],
              }
            : {
                supported: true,
                on,
                wifiOnly,
                health: held ? state : on ? "ok" : "off",
                healthCalls: held ?? 0,
                pending: on ? 1 : 0,
                held: held ? { [state]: held } : {},
              };
        setTimeout(() => {
          for (const listener of listeners)
            listener({
              data: JSON.stringify({ id: request.id, ok: true, result }),
            });
        }, 0);
      },
    },
  });
}

export function AutoCapturePreview() {
  useState(install);
  const mounted = useSyncExternalStore(noSubscription, browser, () => false);
  if (!mounted) return null;
  const state = new URLSearchParams(window.location.search).get("state");
  return (
    <main className={styles.page}>
      <h1>Privacy</h1>
      <Panel title="Calls">
        {state === "loading" ? (
          <Skeleton height={300} />
        ) : (
          <AutoCapturePanel consentOn={state !== "no-consent"} />
        )}
      </Panel>
      {state === "on" || (state !== null && state in holds) ? (
        <Panel title="Alex Example’s calls">
          <ul className={styles.calls}>
            {[...states, ...(state === "on" ? [] : ["held"])].map(
              (state, index) => (
                <li key={state}>
                  <span>Sales call {index + 1}</span>
                  <AutoCaptureState eventId={`fictional-${state}`} />
                </li>
              ),
            )}
          </ul>
        </Panel>
      ) : null}
    </main>
  );
}
