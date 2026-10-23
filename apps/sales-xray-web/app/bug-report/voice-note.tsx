"use client";

/**
 * A voice note for a bug report: say it instead of typing it. Up to a minute,
 * recorded on the device (MediaRecorder), heard back before it goes, removed
 * with one tap. The microphone is asked for only when the person taps Record.
 */

import { Mic, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { tick } from "../ui/haptics";
import styles from "./bug-report.module.css";

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
  | { status: "unsupported" };

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
    if (!voiceSupported()) {
      setState({ status: "unsupported" });
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
    } catch {
      setState({ status: "denied" });
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
        disabled={state.status === "unsupported"}
      >
        <Mic size={15} aria-hidden="true" />
        Add a voice note
      </button>
      {state.status === "denied" ? (
        <small className={styles.note} role="alert">
          The microphone is off for Sales X-Ray. Allow it in your phone or
          browser settings, or type instead.
        </small>
      ) : state.status === "unsupported" ? (
        <small className={styles.note} role="status">
          Voice notes don&apos;t work in this browser. Type instead.
        </small>
      ) : null}
    </>
  );
}
