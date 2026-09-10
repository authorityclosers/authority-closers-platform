"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Music2, Volume2, VolumeX } from "lucide-react";
import { ActionButton } from "@ac/ui";
import {
  createPracticeMusicPlayer,
  readPracticeMusic,
  savePracticeMusic,
  subscribePracticeMusic,
  type PracticeMusicPlayer,
} from "../lib/practice-music";
import {
  DEFAULT_PRACTICE_VOLUME,
  readPracticeSounds,
  readPracticeVolume,
  savePracticeSounds,
  savePracticeVolume,
  subscribePracticeSounds,
  type PracticeSoundPlayer,
} from "../lib/practice-sounds";
import styles from "./practice-sound-controls.module.css";

const defaultMusicPlayer = (changed: (playing: boolean) => void) =>
  createPracticeMusicPlayer({ onPlayingChange: changed });

/** Direct presentation controls. Neither control changes practice or reward state. */
export function PracticeSoundControls({
  getPlayer,
  createMusicPlayer = defaultMusicPlayer,
}: {
  getPlayer: () => PracticeSoundPlayer | null;
  createMusicPlayer?: (
    changed: (playing: boolean) => void,
  ) => PracticeMusicPlayer;
}) {
  const soundsEnabled = useSyncExternalStore(
    subscribePracticeSounds,
    readPracticeSounds,
    () => false,
  );
  const volume = useSyncExternalStore(
    subscribePracticeSounds,
    readPracticeVolume,
    () => DEFAULT_PRACTICE_VOLUME,
  );
  const soundsAudible = soundsEnabled && volume > 0;
  const [musicPlaying, setMusicPlaying] = useState(false);
  const [musicStarting, setMusicStarting] = useState(false);
  const [status, setStatus] = useState("");
  const music = useRef<PracticeMusicPlayer | null>(null);
  const requestVersion = useRef(0);
  const subscribeToMusic = useCallback((changed: () => void) => {
    return subscribePracticeMusic(() => {
      if (!readPracticeMusic()) {
        requestVersion.current += 1;
        setMusicStarting(false);
        music.current?.stop();
      }
      changed();
    });
  }, []);
  useSyncExternalStore(subscribeToMusic, readPracticeMusic, () => false);

  useEffect(() => {
    let mounted = true;
    const player = createMusicPlayer((playing) => {
      if (mounted) setMusicPlaying(playing);
    });
    music.current = player;
    return () => {
      mounted = false;
      requestVersion.current += 1;
      player.dispose();
      if (music.current === player) music.current = null;
    };
  }, [createMusicPlayer]);

  function toggleSounds() {
    const next = !soundsAudible;
    const player = getPlayer();
    if (next && volume === 0) {
      savePracticeVolume(DEFAULT_PRACTICE_VOLUME);
      player?.setVolume(DEFAULT_PRACTICE_VOLUME);
    }
    savePracticeSounds(next);
    player?.setEnabled(next);
    if (next) void player?.prepare();
    setStatus(next ? "Practice sounds unmuted." : "Practice sounds muted.");
  }

  function toggleMusic() {
    const player = music.current;
    if (!player) return;
    if (musicPlaying || musicStarting) {
      requestVersion.current += 1;
      player.stop();
      savePracticeMusic(false);
      setMusicStarting(false);
      setStatus("Background music stopped.");
      return;
    }
    const version = ++requestVersion.current;
    savePracticeMusic(true);
    setMusicStarting(true);
    setStatus("Starting background music.");
    void player.start().then((started) => {
      if (version !== requestVersion.current) return;
      setMusicStarting(false);
      if (!started) savePracticeMusic(false);
      setStatus(
        started
          ? "Background music playing."
          : "Background music is unavailable right now.",
      );
    });
  }

  return (
    <div className={styles.root} aria-label="Practice audio controls">
      <ActionButton
        variant="icon"
        className={styles.control}
        aria-label={
          soundsAudible ? "Mute practice sounds" : "Unmute practice sounds"
        }
        aria-pressed={soundsAudible}
        title={
          soundsAudible ? "Mute practice sounds" : "Unmute practice sounds"
        }
        data-active={soundsAudible}
        onClick={toggleSounds}
      >
        {soundsAudible ? (
          <Volume2 size={20} aria-hidden="true" />
        ) : (
          <VolumeX size={20} aria-hidden="true" />
        )}
      </ActionButton>
      <ActionButton
        variant="icon"
        className={styles.control}
        aria-label={
          musicPlaying || musicStarting
            ? "Stop background music"
            : "Play background music"
        }
        aria-pressed={musicPlaying}
        title={
          musicPlaying
            ? "Stop background music"
            : musicStarting
              ? "Stop music loading"
              : "Play background music"
        }
        data-active={musicPlaying}
        data-starting={musicStarting}
        onClick={toggleMusic}
      >
        <Music2 size={20} aria-hidden="true" />
      </ActionButton>
      <span className={styles.status} role="status" aria-live="polite">
        {status}
      </span>
    </div>
  );
}
