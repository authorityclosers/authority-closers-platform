"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Music2, Play, Volume2, VolumeX, X } from "lucide-react";
import { ActionButton } from "@ac/ui";
import {
  DEFAULT_PRACTICE_VOLUME,
  readPracticeSounds,
  readPracticeVolume,
  savePracticeSounds,
  savePracticeVolume,
  subscribePracticeSounds,
  type PracticeSound,
  type PracticeSoundPlayer,
} from "../lib/practice-sounds";
import styles from "./practice-sound-controls.module.css";

/** Presentation preferences only. Previewing never submits a response or earns a reward. */
export function PracticeSoundControls({
  getPlayer,
}: {
  getPlayer: () => PracticeSoundPlayer | null;
}) {
  const enabled = useSyncExternalStore(
    subscribePracticeSounds,
    readPracticeSounds,
    () => false,
  );
  const volume = useSyncExternalStore(
    subscribePracticeSounds,
    readPracticeVolume,
    () => DEFAULT_PRACTICE_VOLUME,
  );
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [previewing, setPreviewing] = useState<PracticeSound | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const soundSwitch = useRef<HTMLButtonElement>(null);
  const previewVersion = useRef(0);
  const playerRef = useRef(getPlayer);
  useEffect(() => {
    playerRef.current = getPlayer;
  }, [getPlayer]);
  const title = useId();
  const panel = useId();

  useEffect(() => {
    if (!open) return;
    soundSwitch.current?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", escape);
    return () => {
      previewVersion.current += 1;
      playerRef.current()?.stop();
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function preview(kind: PracticeSound) {
    const player = getPlayer();
    if (!player || !enabled || volume === 0) return;
    const version = ++previewVersion.current;
    setPreviewing(kind);
    setMessage("");
    const played = await player.preview(kind);
    if (version !== previewVersion.current) return;
    setPreviewing(null);
    setMessage(
      played
        ? "Sound preview. No practice progress changes."
        : "Sound isn’t ready yet. Try the preview again.",
    );
  }

  return (
    <div className={styles.root} ref={root}>
      <ActionButton
        ref={trigger}
        variant="icon"
        aria-label="Practice sound settings"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panel : undefined}
        title={enabled ? "Sound settings" : "Sound settings · muted"}
        onClick={() => {
          setMessage("");
          setPreviewing(null);
          setOpen(!open);
        }}
      >
        {enabled && volume > 0 ? (
          <Volume2 size={20} aria-hidden="true" />
        ) : (
          <VolumeX size={20} aria-hidden="true" />
        )}
      </ActionButton>
      {open && (
        <section
          id={panel}
          role="dialog"
          aria-labelledby={title}
          className={styles.panel}
        >
          <header className={styles.heading}>
            <Music2 size={19} aria-hidden="true" />
            <h2 id={title}>Practice sounds</h2>
            <button
              className={styles.icon}
              aria-label="Close sound settings"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          <div className={styles.row}>
            <span>
              Sound effects<small>Just the little moments.</small>
            </span>
            <button
              ref={soundSwitch}
              className={styles.switch}
              role="switch"
              aria-label="Practice sound effects"
              aria-checked={enabled}
              onClick={() => {
                const next = !readPracticeSounds();
                savePracticeSounds(next);
                getPlayer()?.setEnabled(next);
                if (next) void getPlayer()?.prepare();
                else {
                  previewVersion.current += 1;
                  setPreviewing(null);
                }
                setMessage("");
              }}
            >
              <span />
            </button>
          </div>
          <label className={styles.volume}>
            <span>
              Volume<output>{Math.round(volume * 100)}%</output>
            </span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={Math.round(volume * 100)}
              aria-label="Practice sound volume"
              onChange={(event) => {
                const next = Number(event.currentTarget.value) / 100;
                savePracticeVolume(next);
                getPlayer()?.setVolume(next);
              }}
            />
          </label>
          <div className={styles.previews} aria-label="Preview sound effects">
            {(
              [
                ["select", "Tap"],
                ["confirm", "Saved"],
                ["reward", "Celebrate"],
              ] as const
            ).map(([kind, label]) => (
              <button
                key={kind}
                disabled={!enabled || volume === 0 || previewing !== null}
                onClick={() => void preview(kind)}
              >
                <Play size={13} aria-hidden="true" />
                {previewing === kind ? "Loading…" : label}
              </button>
            ))}
          </div>
          <p className={styles.note} role="status">
            {message ||
              (enabled
                ? "Your choice is saved on this browser."
                : "Sound is off. Visual feedback always stays on.")}
          </p>
        </section>
      )}
    </div>
  );
}
