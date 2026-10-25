"use client";

/**
 * A voice note for a bug report: say it instead of typing it. Up to a minute,
 * recorded on the device (MediaRecorder), heard back before it goes, removed
 * with one tap. The microphone is asked for only when the person taps Record.
 */

import { Mic, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { inPhoneApp, phoneStatus } from "../leads/native-phone";
import { tick } from "../ui/haptics";
import styles from "./bug-report.module.css";
import { browserFrom } from "./device";

export const VOICE_LIMIT_SECONDS = 60;
const TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

export type VoiceNote = Readonly<{ blob: Blob; seconds: number; url: string }>;

type State =
  | { status: "idle" }
  | { status: "recording"; startedAt: number }
  | { status: "denied" }
  | { status: "no_microphone" }
  | { status: "app_update" }
  | { status: "unsupported" };

/** The Android app's first version that lets a page use the microphone (#11). */
export const VOICE_APP_VERSION = "1.0.35";

/** True when an app version (e.g. "1.0.34") is older than `than`. */
export function olderThan(version: string, than: string): boolean {
  const parts = (value: string) =>
    value.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const [mine, theirs] = [parts(version), parts(than)];
  for (let i = 0; i < Math.max(mine.length, theirs.length); i += 1) {
    const [a, b] = [mine[i] ?? 0, theirs[i] ?? 0];
    if (a !== b) return a < b;
  }
  return false;
}

/** Where to turn the microphone on when nothing asks (#11: this browser's own route). */
export function micRoute(userAgent: string, inApp: boolean): string {
  if (inApp) {
    return "If nothing asks: phone Settings → Apps → Sales X-Ray → Permissions → Microphone.";
  }
  const browser = browserFrom(userAgent) ?? "";
  const phone = /Mobi|Android|iPhone|iPad/.test(userAgent);
  if (browser.startsWith("Firefox")) {
    return "If nothing asks: click the microphone icon in the address bar and allow it.";
  }
  if (browser.startsWith("Safari")) {
    return phone
      ? "If nothing asks: tap aA in the address bar → Website Settings → Microphone → Allow."
      : "If nothing asks: Safari → Settings → Websites → Microphone → allow this site.";
  }
  if (phone) {
    return "If nothing asks: tap the icon left of the address → Permissions → Microphone → Allow.";
  }
  return browser.startsWith("Edge")
    ? "If nothing asks: click the lock left of the address → Permissions for this site → Microphone → Allow."
    : "If nothing asks: click the icon left of the address → Site settings → Microphone → Allow, then reload.";
}

export function voiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

function pickType(): string | undefined {
  return TYPES.find((type) => {
    try {
      return MediaRecorder.isTypeSupported(type);
    } catch {
      return false;
    }
  });
}

export function VoiceNoteRow({
  note,
  onChange,
}: {
  note: VoiceNote | null;
  onChange: (note: VoiceNote | null) => void;
}) {
  const [state, setState] = useState<State>({ status: "idle" });
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);

  const release = () => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  };

  const stop = useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  useEffect(() => {
    if (state.status !== "recording") return;
    const timer = window.setInterval(() => {
      const seconds = (Date.now() - state.startedAt) / 1000;
      setElapsed(seconds);
      if (seconds >= VOICE_LIMIT_SECONDS) stop();
    }, 250);
    return () => window.clearInterval(timer);
  }, [state, stop]);

  // Leaving the sheet stops the microphone.
  useEffect(
    () => () => {
      if (recorder.current?.state === "recording") recorder.current.stop();
      release();
    },
    [],
  );

  const start = async () => {
    // The Android app before 1.0.35 can't give a page the microphone: say an update
    // brings it, not an error (#11, 26 Oct 2026).
    if (inPhoneApp()) {
      const phone = await phoneStatus();
      if (phone?.version && olderThan(phone.version, VOICE_APP_VERSION)) {
        setState({ status: "app_update" });
        return;
      }
    }
    if (!voiceSupported()) {
      setState({ status: "unsupported" });
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
    } catch (error) {
      setState({
        status:
          error instanceof DOMException && error.name === "NotFoundError"
            ? "no_microphone"
            : "denied",
      });
      return;
    }
    const type = pickType();
    const media = new MediaRecorder(
      stream.current,
      type ? { mimeType: type, audioBitsPerSecond: 32_000 } : undefined,
    );
    chunks.current = [];
    const startedAt = Date.now();
    media.ondataavailable = (event) => {
      if (event.data.size) chunks.current.push(event.data);
    };
    media.onstop = () => {
      release();
      const seconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      const blob = new Blob(chunks.current, {
        type: (media.mimeType || type || "audio/webm").split(";")[0],
      });
      setState({ status: "idle" });
      setElapsed(0);
      if (blob.size)
        onChange({ blob, seconds, url: URL.createObjectURL(blob) });
    };
    recorder.current = media;
    media.start(250);
    tick();
    setState({ status: "recording", startedAt });
  };

  if (note) {
    return (
      <div className={styles.voice}>
        {/* A local recording, heard back before it goes. */}
        <audio
          className={styles.voicePlayer}
          src={note.url}
          controls
          preload="metadata"
        >
          <track kind="captions" />
        </audio>
        <span className={styles.voiceLength}>{note.seconds} s</span>
        <button
          type="button"
          className={styles.remove}
          aria-label="Remove the voice note"
          onClick={() => {
            URL.revokeObjectURL(note.url);
            onChange(null);
          }}
        >
          <Trash2 size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }
  if (state.status === "recording") {
    const left = Math.max(0, Math.ceil(VOICE_LIMIT_SECONDS - elapsed));
    return (
      <div className={styles.voice} data-recording="">
        <span className={styles.recordingDot} aria-hidden="true" />
        <span className={styles.voiceWords} role="status">
          Recording · {Math.floor(elapsed)} s<small>{left} s left</small>
        </span>
        <button type="button" className={styles.chip} onClick={stop}>
          <Square size={14} aria-hidden="true" />
          Stop
        </button>
      </div>
    );
  }
  return (
    <>
      <button
        type="button"
        className={styles.chip}
        onClick={() => void start()}
        disabled={
          state.status === "unsupported" || state.status === "app_update"
        }
      >
        <Mic size={15} aria-hidden="true" />
        Add a voice note
      </button>
      {state.status === "denied" ? (
        // Asked for only on a tap; denied, it offers to ask again and says where
        // to turn it on (owner, 26 Oct 2026: not a red paragraph).
        <div className={styles.micAsk} role="status">
          <span>Voice notes need the microphone. You can also type.</span>
          <button
            type="button"
            className={styles.chip}
            onClick={() => void start()}
          >
            <Mic size={15} aria-hidden="true" />
            Allow microphone
          </button>
          <small className={styles.fine}>
            {micRoute(navigator.userAgent, inPhoneApp())}
          </small>
        </div>
      ) : state.status === "app_update" ? (
        <small className={styles.note} role="status">
          Voice notes come in the next app update. You can type for now.
        </small>
      ) : state.status === "no_microphone" ? (
        <small className={styles.note} role="status">
          No microphone found on this device. You can type instead.
        </small>
      ) : state.status === "unsupported" ? (
        <small className={styles.note} role="status">
          Voice notes don&apos;t work in this browser. Type instead.
        </small>
      ) : null}
    </>
  );
}
