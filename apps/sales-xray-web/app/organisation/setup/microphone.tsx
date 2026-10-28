"use client";
import { Mic } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { inPhoneApp } from "../../leads/native-phone";
import { PhoneSetupPanel } from "../../settings/phone-panel";
import styles from "./setup.module.css";

type State =
  | "check"
  | "prompt"
  | "granted"
  | "denied"
  | "missing"
  | "busy"
  | "insecure"
  | "unavailable";
export function MicrophoneAccess() {
  const [state, setState] = useState<State>("check");
  const [native] = useState(() => inPhoneApp());
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    if (!window.isSecureContext)
      queueMicrotask(() => {
        if (alive.current) setState("insecure");
      });
    else if (!navigator.mediaDevices?.getUserMedia)
      queueMicrotask(() => {
        if (alive.current) setState("unavailable");
      });
    else if (navigator.permissions?.query) {
      let permission: PermissionStatus | undefined;
      const update = () => {
        if (alive.current && permission) setState(permission.state);
      };
      navigator.permissions
        .query({ name: "microphone" as PermissionName })
        .then((next) => {
          if (!alive.current) return;
          permission = next;
          update();
          permission.addEventListener("change", update);
        })
        .catch(() => {
          if (alive.current) setState("prompt");
        });
      return () => {
        alive.current = false;
        permission?.removeEventListener("change", update);
      };
    } else
      queueMicrotask(() => {
        if (alive.current) setState("prompt");
      });
    return () => {
      alive.current = false;
    };
  }, []);
  const request = async () => {
    setState("busy");
    try {
      const permission = navigator.permissions?.query
        ? await navigator.permissions
            .query({ name: "microphone" as PermissionName })
            .catch(() => null)
        : null;
      if (!alive.current) return;
      if (permission?.state === "denied") {
        setState("denied");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      if (alive.current) setState("granted");
    } catch (reason) {
      const name = reason instanceof DOMException ? reason.name : "";
      if (alive.current)
        setState(
          name === "NotAllowedError"
            ? "denied"
            : name === "NotFoundError"
              ? "missing"
              : "unavailable",
        );
    }
  };
  const words: Record<State, string> = {
    check: "Check microphone access before recording in this browser.",
    prompt: "Allow microphone access when your browser asks.",
    busy: "Choose Allow in your browser’s microphone question.",
    granted: "Microphone allowed. The check has stopped listening.",
    denied:
      "Open this site’s permissions beside the address, allow Microphone, then check again. On Windows, also allow microphone access for desktop apps in Settings → Privacy & security.",
    missing: "No microphone found. Connect one, then check again.",
    insecure: "Open Sales X-Ray over HTTPS to allow microphone access.",
    unavailable:
      "Close any app using your microphone and check browser and computer permissions, then try again.",
  };
  return (
    <details className={styles.details}>
      <summary>
        <Mic size={18} aria-hidden="true" />
        Microphone access
      </summary>
      <div className={styles.card}>
        <p className={styles.help} role="status">
          {words[state]}
        </p>
        <button
          className={styles.button}
          disabled={state === "busy" || state === "insecure"}
          onClick={() => void request()}
        >
          Check microphone
        </button>
        <p className={styles.help}>
          This allows browser recording. Android call logging and recording need
          the phone app’s setup and Android permissions; Meta approval does not
          control microphone access.
        </p>
        {native ? <PhoneSetupPanel /> : null}
      </div>
    </details>
  );
}
