"use client";

/**
 * Settings → Phone & alerts: the person's own switches on one screen (owner,
 * 24 Oct 2026: "all these settings are terrible for UX we need to make it
 * simpler least steps workflows"). This file holds the phone's two parts:
 * what the phone still needs, each line one tap from its fix, and vibration.
 */
import { CheckCircle2, Circle, Vibrate } from "lucide-react";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import {
  inPhoneApp,
  onPhoneSignal,
  setupStatus,
  type SetupStatus,
} from "../leads/native-phone";
import {
  FIXABLE,
  lineDone,
  lineTodo,
  reportSetup,
  setupLines,
  setupProgress,
} from "../leads/phone-setup";
import { PHONE_SETUP_PANEL_ATTRIBUTE } from "../capture-setup/capture-setup-rules";
import { PhoneSetupFlow, type FlowStep } from "../leads/phone-setup-flow";
import { checkLabel } from "../leads/phone-setup-words";
import { hapticsOn, setHaptics } from "../ui/haptics";
import { Button, Panel } from "../ui/kit";
import { StateSwitch } from "../ui/state-switch";
import styles from "./sections.module.css";

/**
 * Phone setup inside the phone app: "N of M done", one button that walks
 * everything still to do, and a Fix on each line that sets up only that.
 */
export function PhoneSetupPanel() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  // null: closed; "all": everything still to do; a line: just that one.
  const [flow, setFlow] = useState<FlowStep | "all" | null>(null);

  const take = useCallback((next: SetupStatus | null) => {
    if (!next) return;
    setStatus(next);
    void reportSetup(next);
  }, []);

  useEffect(() => {
    if (!inPhoneApp()) return;
    void setupStatus().then(take);
    return onPhoneSignal((event) => {
      if (event === "resume") void setupStatus().then(take);
    });
  }, [take]);

  // While this panel offers "Set up this phone", "Finish setting up" waits:
  // one offer of the same steps on a screen (tester report 217).
  const offering =
    status !== null && setupLines(status).some((key) => !lineDone(key, status));
  useEffect(() => {
    if (!offering) return;
    const html = document.documentElement;
    html.setAttribute(PHONE_SETUP_PANEL_ATTRIBUTE, "");
    return () => html.removeAttribute(PHONE_SETUP_PANEL_ATTRIBUTE);
  }, [offering]);

  if (!status) return null;
  const { done, total } = setupProgress(status);
  const lines = setupLines(status);
  // Lines are done as the count says: a picked recordings folder ticks Call
  // recordings (Redmi QA on production, 14 Nov 2026: "5 of 9 done" over a list
  // that still had Call recordings and its Fix).
  const missing = lines.filter((key) => !lineDone(key, status));
  const finished = lines
    .filter((key) => lineDone(key, status))
    .map((key) => checkLabel(key, status.store));
  return (
    <Panel title="Phone setup">
      <div className={styles.setupHead}>
        <strong>
          {done} of {total} done
        </strong>
        {missing.length ? (
          <Button variant="primary" onClick={() => setFlow("all")}>
            Set up this phone
          </Button>
        ) : null}
      </div>
      {missing.length ? (
        <ul className={styles.setupLines} aria-label="Still to do">
          {missing.map((key) => (
            <li key={key}>
              <Circle size={18} aria-hidden="true" />
              <span>
                <strong>{checkLabel(key, status.store)}</strong>
                <small>{lineTodo(key, status)}</small>
              </span>
              {FIXABLE.has(key) ? (
                <Button onClick={() => setFlow(key as FlowStep)}>Fix</Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {finished.length ? (
        <p className={styles.setupDone}>
          <CheckCircle2 size={16} aria-hidden="true" />
          Done: {finished.join(", ")}
        </p>
      ) : null}
      {flow ? (
        <PhoneSetupFlow
          only={flow === "all" ? undefined : flow}
          onClose={(next) => {
            setFlow(null);
            take(next);
          }}
        />
      ) : null}
    </Panel>
  );
}

const never = () => () => undefined;
/** Only where a buzz can be felt: the phone app, or a touch screen that vibrates. */
const canBuzz = () =>
  inPhoneApp() ||
  (typeof navigator.vibrate === "function" &&
    window.matchMedia?.("(pointer: coarse)").matches === true);

/** Short buzzes on swipes, pull to refresh and finished steps; on unless turned off here. */
export function VibrationPanel() {
  const shown = useSyncExternalStore(never, canBuzz, () => false);
  const [chosen, setChosen] = useState<boolean | null>(null);
  if (!shown) return null;
  return (
    <Panel title="Sounds & vibration">
      <StateSwitch
        icon={<Vibrate size={18} />}
        label="Vibration"
        meaning="A short buzz when you swipe a lead, pull to refresh or finish a step."
        onText="On"
        offText="Off"
        note="Alert sounds follow your phone's notification settings."
        chipOn="Vibration on"
        chipOff="Vibration off"
        // Turning vibration off is never felt; turning it on is, once saved.
        haptics={false}
        on={chosen ?? hapticsOn()}
        onChange={async (next) => {
          setHaptics(next);
          setChosen(next);
        }}
      />
    </Panel>
  );
}
