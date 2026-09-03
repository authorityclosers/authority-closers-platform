"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import Link from "next/link";
import {
  Captions,
  CheckCircle2,
  CirclePlay,
  FileText,
  Gauge,
  Maximize2,
  Pause,
  PictureInPicture2,
  Play,
  ShieldCheck,
  VideoOff,
  Volume2,
  VolumeX,
} from "lucide-react";

import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
  type PlaybackEventInput,
} from "../lib/learner-api";

/**
 * A media descriptor must be produced by a trusted, server-authorized media
 * adapter. This component never constructs a provider URL or enables a
 * provider on its own.
 */
export interface AuthorizedCaptionTrack {
  src: string;
  srclang: string;
  label: string;
  default?: boolean;
}

export interface AuthorizedTranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface AuthorizedVideoMedia {
  src: string;
  poster?: string;
  captions?: AuthorizedCaptionTrack[];
  transcript?: AuthorizedTranscriptSegment[];
}

type PlaybackStatus =
  | "idle"
  | "starting"
  | "watching"
  | "saving"
  | "submitted"
  | "error";

type MediaState =
  | "loading"
  | "ready"
  | "playing"
  | "paused"
  | "buffering"
  | "processing"
  | "error"
  | "blocked"
  | "backgrounded";

interface PlaybackSessionState {
  id: string;
  token: string;
  revision: number;
  activityRevision: number;
  expiresAt: number;
  closed: boolean;
}

type PendingPlaybackEvent = {
  input: PlaybackEventInput;
};

export interface VideoViewerProps {
  activity: ActivityResponse;
  api: LearnerApi;
  moduleHref: string;
  media?: AuthorizedVideoMedia | null;
  onPlaybackCommitted?: () => void | Promise<void>;
}

export function formatMediaTime(value: number): string {
  const seconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function canStartPlayback(activity: Pick<ActivityResponse, "state" | "allowed_actions">): boolean {
  return (
    ["available", "in_progress"].includes(activity.state.toLowerCase()) &&
    activity.allowed_actions.includes("complete_video")
  );
}

export function isLearnerOnline(): boolean {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

function clientEventId(sequence: number): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `learner-playback-${Date.now()}-${sequence}`;
}

function playbackErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Your session expired. Sign in again before sending watch evidence.";
    if (error.status === 403)
      return "This account is not currently authorized for this lesson.";
    return error.message;
  }
  if (error instanceof TypeError)
    return "The learning service could not be reached. Reconnect and try again.";
  return "Watch progress could not be saved. Try again while connected.";
}

function isPlaybackSessionInvalid(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return (
    [401, 403, 404, 409, 422].includes(error.status) &&
    (error.code === null ||
      [
        "playback_session_not_found",
        "playback_session_expired",
        "playback_session_token_invalid",
        "playback_session_closed",
        "evidence_version_mismatch",
        "playback_event_replay_rejected",
      ].includes(error.code))
  );
}

function LockedMediaStage({
  activity,
  moduleHref,
}: Pick<VideoViewerProps, "activity" | "moduleHref">) {
  const authorized = canStartPlayback(activity);

  return (
    <div
      className="momentum-video-stage momentum-video-stage--unavailable"
      role="status"
      aria-label="Approved lesson media is unavailable"
    >
      <div className="momentum-video-stage__topline">
        <span className="momentum-video-stage__index">01</span>
        <span>LESSON PLAYBACK</span>
        <span className="momentum-video-stage__badge">
          <VideoOff size={14} aria-hidden="true" />
          Media not connected
        </span>
      </div>
      <div className="momentum-video-stage__copy">
        <div className="momentum-video-stage__icon" aria-hidden="true">
          <VideoOff size={28} />
        </div>
        <p className="momentum-video-stage__eyebrow">
          Server-authorized lesson
        </p>
        <h3>No approved lesson media is connected yet.</h3>
        <p>
          {authorized
            ? "The server exposes a completion action, but this activity cannot start playback until approved lesson media is attached."
            : "Playback and completion remain unavailable for this activity until the server resolves the required capability."}
        </p>
      </div>
      <div className="momentum-video-stage__footer">
        <span>
          <ShieldCheck size={15} aria-hidden="true" />
          Watch evidence cannot be submitted while media is unavailable.
        </span>
        <Link href={moduleHref}>Return to module</Link>
      </div>
    </div>
  );
}

function CompletedMediaStage({
  activity,
  moduleHref,
}: Pick<VideoViewerProps, "activity" | "moduleHref">) {
  return (
    <div
      className="momentum-video-stage momentum-video-stage--complete"
      role="status"
      aria-label="Lesson completion is recorded"
    >
      <div className="momentum-video-stage__topline">
        <span className="momentum-video-stage__index">01</span>
        <span>LESSON PLAYBACK</span>
        <span className="momentum-video-stage__badge">
          <CheckCircle2 size={14} aria-hidden="true" />
          Complete
        </span>
      </div>
      <div className="momentum-video-stage__copy">
        <div className="momentum-video-stage__icon" aria-hidden="true">
          <CheckCircle2 size={28} />
        </div>
        <p className="momentum-video-stage__eyebrow">Server-resolved state</p>
        <h3>Lesson complete.</h3>
        <p>
          The server has accepted the completion evidence for this activity.
          Media playback is no longer available from this completed state.
        </p>
      </div>
      <div className="momentum-video-stage__footer">
        <span>
          <ShieldCheck size={15} aria-hidden="true" />
          Current activity state: {activity.state}
        </span>
        <Link href={moduleHref}>Return to module</Link>
      </div>
    </div>
  );
}

export function VideoViewer({
  activity,
  api,
  moduleHref,
  media = null,
  onPlaybackCommitted,
}: VideoViewerProps) {
  const authorized = Boolean(media?.src) && canStartPlayback(activity);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const sessionRef = useRef<PlaybackSessionState | null>(null);
  const startRequestRef = useRef<Promise<boolean> | null>(null);
  const heartbeatRequestRef = useRef<Promise<boolean> | null>(null);
  const pendingHeartbeatRef = useRef<PendingPlaybackEvent | null>(null);
  const completionRequestRef = useRef<Promise<void> | null>(null);
  const mountedRef = useRef(true);
  const unmountingRef = useRef(false);
  const finishReadyRef = useRef(false);
  const sequenceRef = useRef(0);
  const watchCursorRef = useRef(0);
  const statusRef = useRef<PlaybackStatus>("idle");
  const [status, setStatus] = useState<PlaybackStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [canFullscreen, setCanFullscreen] = useState(false);
  const [canPictureInPicture, setCanPictureInPicture] = useState(false);
  const [hasEnded, setHasEnded] = useState(false);
  const [mediaState, setMediaState] = useState<MediaState>(
    authorized ? "loading" : "blocked",
  );
  const [mediaMessage, setMediaMessage] = useState(
    authorized
      ? "Loading approved lesson media…"
      : "Approved lesson media is unavailable.",
  );
  const backgroundedRef = useRef(false);

  const updateStatus = useCallback(
    (next: PlaybackStatus, message: string) => {
      if (!mountedRef.current) return;
      statusRef.current = next;
      setStatus(next);
      setStatusMessage(message);
    },
    [],
  );

  const resetPlaybackSession = useCallback(() => {
    sessionRef.current = null;
    pendingHeartbeatRef.current = null;
    finishReadyRef.current = false;
    sequenceRef.current = 0;
    watchCursorRef.current = 0;
    setIsPlaying(false);
    videoRef.current?.pause();
  }, []);

  const sendPlaybackEvent = useCallback(
    async (
      kind: PlaybackEventInput["kind"],
      startSeconds: number,
      endSeconds: number,
    ): Promise<boolean> => {
      const session = sessionRef.current;
      if (!session) {
        updateStatus(
          "error",
          "Offline — watch progress was not submitted. Reconnect to continue.",
        );
        return false;
      }
      if (session.closed) return true;
      if (!isLearnerOnline()) {
        updateStatus(
          "error",
          "Offline — watch progress was not submitted. Reconnect to continue.",
        );
        return false;
      }
      if (kind === "watch" && endSeconds <= startSeconds + 0.05) return true;

      if (heartbeatRequestRef.current) {
        const previousHeartbeatSucceeded = await heartbeatRequestRef.current;
        if (!previousHeartbeatSucceeded) return false;
      }
      const activeSession = sessionRef.current;
      if (!activeSession || !isLearnerOnline()) return false;

      const pending = pendingHeartbeatRef.current;
      const input =
        pending?.input.session_id === activeSession.id
          ? pending.input
          : {
              session_id: activeSession.id,
              event_id: clientEventId(sequenceRef.current + 1),
              sequence: sequenceRef.current + 1,
              start_seconds: Math.max(0, startSeconds),
              end_seconds: Math.max(0, endSeconds),
              kind,
            };
      pendingHeartbeatRef.current = { input };
      const request = api
        .heartbeatPlayback(activity.id, input, activeSession.token)
        .then((result) => {
          const currentSession = sessionRef.current;
          if (currentSession?.id === result.session_id) {
            sessionRef.current = {
              ...currentSession,
              revision: result.revision,
            };
          }
          sequenceRef.current = Math.max(sequenceRef.current, result.sequence);
          if (pendingHeartbeatRef.current?.input.event_id === input.event_id) {
            pendingHeartbeatRef.current = null;
          }
          watchCursorRef.current = Math.max(0, input.end_seconds);
          if (statusRef.current !== "saving" && statusRef.current !== "submitted") {
            updateStatus("watching", "Watch progress is being recorded by the server.");
          }
          return true;
        })
        .catch((error: unknown) => {
          if (isPlaybackSessionInvalid(error)) {
            resetPlaybackSession();
          }
          updateStatus("error", playbackErrorMessage(error));
          videoRef.current?.pause();
          return false;
        });
      heartbeatRequestRef.current = request;
      try {
        return await request;
      } finally {
        if (heartbeatRequestRef.current === request) {
          heartbeatRequestRef.current = null;
        }
      }
    },
    [activity.id, api, resetPlaybackSession, updateStatus],
  );

  const flushWatch = useCallback(
    async (position?: number): Promise<boolean> => {
      if (!sessionRef.current || sessionRef.current.closed || finishReadyRef.current) {
        return true;
      }
      if (heartbeatRequestRef.current) {
        const previousHeartbeatSucceeded = await heartbeatRequestRef.current;
        if (!previousHeartbeatSucceeded) return false;
      }
      const target = position ?? videoRef.current?.currentTime ?? 0;
      const start = watchCursorRef.current;
      if (target <= start + 0.05) return true;
      return sendPlaybackEvent("watch", start, target);
    },
    [sendPlaybackEvent],
  );

  const ensurePlaybackSession = useCallback(async (): Promise<boolean> => {
    if (sessionRef.current?.closed) {
      updateStatus("submitted", "Watch progress has already been submitted.");
      return false;
    }
    if (sessionRef.current) {
      if (
        sessionRef.current.expiresAt > 0 &&
        sessionRef.current.expiresAt <= Date.now()
      ) {
        resetPlaybackSession();
      } else {
        return true;
      }
    }
    if (!authorized || !isLearnerOnline()) {
      updateStatus(
        "error",
        !isLearnerOnline()
          ? "Offline — watch progress was not submitted. Reconnect to continue."
          : "Playback is not currently authorized for this activity.",
      );
      return false;
    }
    if (startRequestRef.current) return startRequestRef.current;

    const request = (async () => {
      updateStatus("starting", "Requesting a server playback session…");
      try {
        const started = await api.startPlayback(activity.id, activity.revision);
        if (!started.session_token) {
          throw new Error("The server did not return a playback authorization token.");
        }
        const expiresAt = Date.parse(started.expires_at);
        if (!Number.isFinite(expiresAt)) {
          throw new Error("The server did not return a valid playback expiry.");
        }
        // Starting playback can move the activity to in_progress. Refresh the
        // activity before any evidence submission so its revision is current.
        const currentActivity = await api.activity(activity.id);
        sessionRef.current = {
          id: started.session_id,
          token: started.session_token,
          revision: started.revision,
          activityRevision: currentActivity.revision,
          expiresAt,
          closed: false,
        };
        sequenceRef.current = 0;
        pendingHeartbeatRef.current = null;
        watchCursorRef.current = 0;
        finishReadyRef.current = false;
        if (started.duration_seconds > 0) setDuration(started.duration_seconds);
        updateStatus("watching", "Watch progress is being recorded by the server.");
        return true;
      } catch (error) {
        updateStatus("error", playbackErrorMessage(error));
        return false;
      } finally {
        startRequestRef.current = null;
      }
    })();
    startRequestRef.current = request;
    return request;
  }, [
    activity.id,
    activity.revision,
    api,
    authorized,
    resetPlaybackSession,
    updateStatus,
  ]);

  const startPlaybackAndPlay = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    const ok = await ensurePlaybackSession();
    if (!ok) {
      video.pause();
      return;
    }
    try {
      await video.play();
    } catch (error) {
      updateStatus("error", playbackErrorMessage(error));
    }
  }, [ensurePlaybackSession, updateStatus]);

  const completePlayback = useCallback(async () => {
    if (completionRequestRef.current) return completionRequestRef.current;
    const session = sessionRef.current;
    const video = videoRef.current;
    if (!session || !video) return;
    if (!isLearnerOnline()) {
      updateStatus(
        "error",
        "Offline — watch progress was not submitted. Reconnect to continue.",
      );
      return;
    }

    const request = (async () => {
      updateStatus("saving", "Saving the final watch interval…");
      try {
        if (!session.closed && !finishReadyRef.current) {
          const flushed = await flushWatch(video.duration || duration || video.currentTime);
          if (!flushed) return;
          // Once final watch evidence is accepted, a retry must not append a
          // heartbeat after a successful or unknown-outcome close command.
          finishReadyRef.current = true;
        }
        const activeSession = sessionRef.current;
        if (!activeSession) return;
        if (!activeSession.closed) {
          const finished = await api.finishPlayback(
            activity.id,
            activeSession.id,
            activeSession.revision,
            activeSession.token,
          );
          const latestSession = sessionRef.current;
          if (latestSession?.id === finished.session_id) {
            sessionRef.current = {
              ...latestSession,
              revision: finished.revision,
              closed: true,
            };
          }
        }
        const finishedSession = sessionRef.current;
        if (!finishedSession) return;
        const currentActivity = await api.activity(activity.id);
        await api.submitEvidence(
          activity.id,
          "video_watch",
          {},
          currentActivity.revision,
          finishedSession.id,
          finishedSession.token,
        );
        updateStatus(
          "submitted",
          "Watch progress submitted. The server will determine completion.",
        );
        await onPlaybackCommitted?.();
      } catch (error) {
        if (isPlaybackSessionInvalid(error)) {
          resetPlaybackSession();
        }
        updateStatus("error", playbackErrorMessage(error));
      } finally {
        completionRequestRef.current = null;
      }
    })();
    completionRequestRef.current = request;
    return request;
  }, [
    activity.id,
    api,
    duration,
    flushWatch,
    onPlaybackCommitted,
    resetPlaybackSession,
    updateStatus,
  ]);

  const retryPlaybackSave = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (sessionRef.current) {
      await completePlayback();
      return;
    }
    setHasEnded(false);
    video.currentTime = 0;
    setCurrentTime(0);
    setMediaState("loading");
    setMediaMessage("Starting a fresh approved playback session…");
    const started = await ensurePlaybackSession();
    if (!started) return;
    try {
      await video.play();
    } catch (error) {
      updateStatus("error", playbackErrorMessage(error));
      setMediaState("error");
      setMediaMessage("Approved lesson media could not be started. Try again.");
    }
  }, [completePlayback, ensurePlaybackSession, updateStatus]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (!authorized) {
        setMediaState("blocked");
        setMediaMessage("Approved lesson media is unavailable.");
        return;
      }
      setMediaState("loading");
      setMediaMessage("Loading approved lesson media…");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [authorized, media?.src]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !authorized) return;
    const safariVideo = video as HTMLVideoElement & {
      webkitEnterFullscreen?: () => void;
      webkitSupportsFullscreen?: boolean;
    };
    setCanFullscreen(
      typeof document !== "undefined" &&
        (Boolean(document.fullscreenEnabled) ||
          Boolean(
            safariVideo.webkitSupportsFullscreen ||
              safariVideo.webkitEnterFullscreen,
          )),
    );
    setCanPictureInPicture(
      typeof document !== "undefined" &&
        Boolean(document.pictureInPictureEnabled) &&
        typeof video.requestPictureInPicture === "function",
    );
  }, [authorized]);

  useEffect(
    () => () => {
      unmountingRef.current = true;
      mountedRef.current = false;
      videoRef.current?.pause();
    },
    [],
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !media?.captions?.length) return;
    for (let index = 0; index < video.textTracks.length; index += 1) {
      video.textTracks[index].mode = captionsEnabled ? "showing" : "hidden";
    }
  }, [authorized, captionsEnabled, media?.captions?.length]);

  const handlePlay = useCallback(() => {
    if (!sessionRef.current) {
      videoRef.current?.pause();
      setIsPlaying(false);
      void startPlaybackAndPlay();
      return;
    }
    setIsPlaying(true);
    setMediaState("playing");
    setMediaMessage("Playing approved lesson media.");
  }, [startPlaybackAndPlay]);

  const handlePause = useCallback(() => {
    if (!mountedRef.current) return;
    setIsPlaying(false);
    if (backgroundedRef.current) {
      setMediaState("backgrounded");
      setMediaMessage("Playback paused while this tab is in the background.");
    } else if (videoRef.current?.ended || hasEnded) {
      setMediaState("processing");
      setMediaMessage("Processing watch evidence with the server…");
    } else if (mediaState !== "processing") {
      setMediaState("paused");
      setMediaMessage("Playback paused. Press Play to resume.");
    }
    if (!unmountingRef.current) void flushWatch();
  }, [flushWatch, hasEnded, mediaState]);

  const handleSeeked = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const nextPosition = Math.max(0, video.currentTime);
    const previousPosition = watchCursorRef.current;
    // A seek is explicitly zero-length evidence. Reset the local cursor so a
    // later watch interval cannot claim the skipped section.
    watchCursorRef.current = nextPosition;
    if (sessionRef.current && Math.abs(nextPosition - previousPosition) > 0.25) {
      void sendPlaybackEvent("seek", nextPosition, nextPosition);
    }
  }, [sendPlaybackEvent]);

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime);
    const start = watchCursorRef.current;
    if (
      sessionRef.current &&
      video.currentTime - start >= 5 &&
      !heartbeatRequestRef.current
    ) {
      void sendPlaybackEvent("watch", start, video.currentTime);
    }
  }, [sendPlaybackEvent]);

  const handleLoadedMetadata = useCallback(() => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(video.duration)) return;
    setDuration(video.duration);
    if (!backgroundedRef.current && !isPlaying) {
      setMediaState("ready");
      setMediaMessage("Approved lesson media is ready to play.");
    }
  }, [isPlaying]);

  const handleLoadStart = useCallback(() => {
    setMediaState("loading");
    setMediaMessage("Loading approved lesson media…");
  }, []);

  const handleCanPlay = useCallback(() => {
    if (!backgroundedRef.current && !isPlaying) {
      setMediaState("ready");
      setMediaMessage("Approved lesson media is ready to play.");
    }
  }, [isPlaying]);

  const handleWaiting = useCallback(() => {
    setMediaState("buffering");
    setMediaMessage("Playback is buffering. Watch evidence remains paused.");
  }, []);

  const handleMediaError = useCallback(() => {
    setIsPlaying(false);
    setMediaState("error");
    setMediaMessage(
      "Approved lesson media could not be loaded. Retry when connected.",
    );
    updateStatus(
      "error",
      "Approved lesson media could not be loaded. Retry when connected.",
    );
    videoRef.current?.pause();
  }, [updateStatus]);

  const retryMedia = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    updateStatus("idle", "Loading approved lesson media…");
    setMediaState("loading");
    setMediaMessage("Retrying approved lesson media…");
    video.load();
  }, [updateStatus]);

  useEffect(() => {
    function handleVisibilityChange() {
      const video = videoRef.current;
      if (!video) return;
      if (document.hidden) {
        backgroundedRef.current = true;
        if (!video.paused) video.pause();
        setMediaState("backgrounded");
        setMediaMessage("Playback paused while this tab is in the background.");
        return;
      }
      if (backgroundedRef.current) {
        backgroundedRef.current = false;
        setMediaState("paused");
        setMediaMessage("Playback paused. Press Play to resume.");
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void startPlaybackAndPlay();
    } else {
      video.pause();
    }
  }, [startPlaybackAndPlay]);

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setIsMuted(video.muted);
  }, []);

  const changeVolume = useCallback((next: number) => {
    const video = videoRef.current;
    if (!video) return;
    const normalized = Math.min(1, Math.max(0, next));
    video.volume = normalized;
    video.muted = normalized === 0;
    setVolume(normalized);
    setIsMuted(video.muted);
  }, []);

  const changeRate = useCallback((next: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = next;
    setPlaybackRate(next);
  }, []);

  const seek = useCallback((next: number) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(next)) return;
    video.currentTime = Math.min(Math.max(0, next), video.duration || next);
    setCurrentTime(video.currentTime);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const video = videoRef.current;
    if (!video || typeof document === "undefined") return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {
        updateStatus("error", "Fullscreen could not be closed. Try again.");
        setMediaMessage("Fullscreen could not be closed. Try again.");
      });
      return;
    }
    const safariVideo = video as HTMLVideoElement & {
      webkitEnterFullscreen?: () => void;
    };
    if (typeof video.requestFullscreen === "function") {
      void video.requestFullscreen().catch(() => {
        updateStatus("error", "Fullscreen could not be opened. Try again.");
        setMediaMessage("Fullscreen could not be opened. Try again.");
      });
      return;
    }
    if (typeof safariVideo.webkitEnterFullscreen === "function") {
      try {
        safariVideo.webkitEnterFullscreen();
      } catch {
        updateStatus("error", "Fullscreen could not be opened. Try again.");
        setMediaMessage("Fullscreen could not be opened. Try again.");
      }
      return;
    }
    updateStatus("error", "Fullscreen is not available in this browser.");
    setMediaMessage("Fullscreen is not available in this browser.");
  }, [updateStatus]);

  const togglePictureInPicture = useCallback(() => {
    const video = videoRef.current;
    if (!video || typeof video.requestPictureInPicture !== "function") return;
    void video.requestPictureInPicture().catch((error: unknown) => {
      updateStatus("error", playbackErrorMessage(error));
    });
  }, [updateStatus]);

  const progress = useMemo(
    () => (duration > 0 ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0),
    [currentTime, duration],
  );

  const visibleStatusMessage = [
    "loading",
    "buffering",
    "backgrounded",
    "error",
  ].includes(mediaState)
    ? mediaMessage
    : statusMessage || mediaMessage;

  if (!authorized || !media) {
    if (activity.state.toLowerCase() === "completed") {
      return (
        <section className="momentum-video-viewer" aria-labelledby={`video-title-${activity.id}`}>
          <div className="momentum-video-viewer__heading">
            <div>
              <p className="momentum-video-viewer__eyebrow">
                <CirclePlay size={16} aria-hidden="true" />
                Video lesson
              </p>
              <h2 id={`video-title-${activity.id}`}>{activity.title}</h2>
            </div>
            <span className="momentum-video-viewer__policy">
              <ShieldCheck size={15} aria-hidden="true" />
              Server-resolved
            </span>
          </div>
          <CompletedMediaStage activity={activity} moduleHref={moduleHref} />
          <div className="momentum-video-viewer__facts" aria-label="Video lesson status">
            <span>
              <CheckCircle2 size={15} aria-hidden="true" />
              Completion is recorded by the server
            </span>
          </div>
        </section>
      );
    }
    return (
      <section className="momentum-video-viewer" aria-labelledby={`video-title-${activity.id}`}>
        <div className="momentum-video-viewer__heading">
          <div>
            <p className="momentum-video-viewer__eyebrow">
              <CirclePlay size={16} aria-hidden="true" />
              Video lesson
            </p>
            <h2 id={`video-title-${activity.id}`}>{activity.title}</h2>
          </div>
          <span className="momentum-video-viewer__policy">
            <ShieldCheck size={15} aria-hidden="true" />
            Server-resolved
          </span>
        </div>
        <LockedMediaStage activity={activity} moduleHref={moduleHref} />
        <div className="momentum-video-viewer__facts" aria-label="Video lesson status">
          <span>
            <CheckCircle2 size={15} aria-hidden="true" />
            Completion is server-determined
          </span>
          <span>
            <FileText size={15} aria-hidden="true" />
            Captions and transcript unavailable
          </span>
        </div>
      </section>
    );
  }

  const statusLabel =
    status === "starting"
      ? "Starting"
      : status === "saving"
        ? "Saving"
        : status === "submitted"
          ? "Submitted"
          : status === "error"
            ? "Needs attention"
            : mediaState === "loading"
              ? "Loading"
              : mediaState === "buffering"
                ? "Buffering"
                : mediaState === "backgrounded"
                  ? "Paused in background"
                  : mediaState === "processing"
                    ? "Processing"
                    : mediaState === "playing"
                      ? "Playing"
                      : mediaState === "paused"
                        ? "Paused"
                        : "Ready";

  return (
    <section className="momentum-video-viewer" aria-labelledby={`video-title-${activity.id}`}>
      <div className="momentum-video-viewer__heading">
        <div>
          <p className="momentum-video-viewer__eyebrow">
            <CirclePlay size={16} aria-hidden="true" />
            Video lesson
          </p>
          <h2 id={`video-title-${activity.id}`}>{activity.title}</h2>
        </div>
        <span className="momentum-video-viewer__policy">
          <ShieldCheck size={15} aria-hidden="true" />
          Server-resolved
        </span>
      </div>

      <div className="momentum-video-player">
        <div
          className="momentum-video-player__stage"
          data-media-state={mediaState}
        >
          <video
            ref={videoRef}
            className="momentum-video-player__video"
            src={media.src}
            poster={media.poster}
            playsInline
            preload="metadata"
            onLoadStart={handleLoadStart}
            onPlay={() => {
              setIsPlaying(true);
              setMediaState("playing");
              handlePlay();
            }}
            onPause={handlePause}
            onEnded={() => {
              setHasEnded(true);
              setMediaState("processing");
              setMediaMessage("Processing watch evidence with the server…");
              void completePlayback();
            }}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onCanPlay={handleCanPlay}
            onWaiting={handleWaiting}
            onStalled={handleWaiting}
            onSuspend={handleWaiting}
            onError={handleMediaError}
            onSeeked={handleSeeked}
            aria-label={activity.title}
            aria-busy={mediaState === "loading" || mediaState === "buffering"}
          >
            {media.captions?.map((track) => (
              <track
                key={`${track.srclang}-${track.label}`}
                kind="captions"
                src={track.src}
                srcLang={track.srclang}
                label={track.label}
                default={track.default}
              />
            ))}
          </video>
          <div className="momentum-video-player__live-state" role="status" aria-live="polite">
            {visibleStatusMessage || "Playback has not started."}
          </div>
        </div>
        <div
          className="momentum-video-controls"
          role="group"
          aria-label="Video controls"
        >
          <button
            className="momentum-video-controls__play"
            type="button"
            onClick={togglePlay}
            aria-label={isPlaying ? "Pause lesson" : "Play lesson"}
          >
            {isPlaying ? <Pause size={18} aria-hidden="true" /> : <Play size={18} aria-hidden="true" />}
            <span>{isPlaying ? "Pause" : "Play"}</span>
          </button>
          <span className="momentum-video-controls__time" aria-live="off">
            {formatMediaTime(currentTime)} / {formatMediaTime(duration)}
          </span>
          <input
            className="momentum-video-controls__timeline"
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(currentTime, duration || currentTime)}
            style={{ "--video-progress": `${progress}%` } as CSSProperties}
            onChange={(event) => seek(Number(event.target.value))}
            aria-label="Lesson position"
          />
          <button
            className="momentum-video-controls__icon"
            type="button"
            onClick={toggleMute}
            aria-label={isMuted ? "Unmute lesson" : "Mute lesson"}
          >
            {isMuted ? <VolumeX size={18} aria-hidden="true" /> : <Volume2 size={18} aria-hidden="true" />}
          </button>
          <input
            className="momentum-video-controls__volume"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={isMuted ? 0 : volume}
            onChange={(event) => changeVolume(Number(event.target.value))}
            aria-label="Lesson volume"
          />
          <label className="momentum-video-controls__rate">
            <Gauge size={16} aria-hidden="true" />
            <span className="sr-only">Playback speed</span>
            <select value={playbackRate} onChange={(event) => changeRate(Number(event.target.value))}>
              {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
                <option key={rate} value={rate}>{rate}×</option>
              ))}
            </select>
          </label>
          {media.captions?.length ? (
            <button
              className={`momentum-video-controls__icon${captionsEnabled ? " is-active" : ""}`}
              type="button"
              onClick={() => setCaptionsEnabled((current) => !current)}
              aria-pressed={captionsEnabled}
              aria-label={captionsEnabled ? "Hide captions" : "Show captions"}
            >
              <Captions size={18} aria-hidden="true" />
            </button>
          ) : null}
          {canPictureInPicture ? (
            <button
              className="momentum-video-controls__icon"
              type="button"
              onClick={togglePictureInPicture}
              aria-label="Open picture in picture"
            >
              <PictureInPicture2 size={18} aria-hidden="true" />
            </button>
          ) : null}
          {canFullscreen ? (
            <button
              className="momentum-video-controls__icon"
              type="button"
              onClick={toggleFullscreen}
              aria-label="Enter fullscreen"
            >
              <Maximize2 size={18} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="momentum-video-viewer__status-row">
        <div>
          <span className={`momentum-video-viewer__status momentum-video-viewer__status--${status}`}>
            <span className="momentum-video-viewer__status-dot" aria-hidden="true" />
            {statusLabel}
          </span>
          <p className="momentum-video-viewer__status-copy">
            {visibleStatusMessage || "Start the lesson when you are ready."}
          </p>
        </div>
        <div className="momentum-video-viewer__status-actions">
          {status === "error" && (hasEnded || mediaState === "error") ? (
            <button
              className="momentum-video-viewer__retry"
              type="button"
              onClick={() =>
                mediaState === "error" && !hasEnded
                  ? retryMedia()
                  : void retryPlaybackSave()
              }
            >
              {mediaState === "error" && !hasEnded
                ? "Retry media"
                : "Retry server save"}
            </button>
          ) : null}
          <Link href={moduleHref}>Return to module</Link>
        </div>
      </div>

      {media.transcript?.length ? (
        <details
          className="momentum-video-transcript"
          open={transcriptOpen}
          onToggle={(event) => setTranscriptOpen(event.currentTarget.open)}
        >
          <summary>
            <FileText size={17} aria-hidden="true" />
            <span>Open transcript</span>
            <span>{media.transcript.length} segments</span>
          </summary>
          <div className="momentum-video-transcript__body">
            {media.transcript.map((segment) => (
              <button
                type="button"
                key={`${segment.start}-${segment.end}-${segment.text}`}
                onClick={() => seek(segment.start)}
              >
                <span>{formatMediaTime(segment.start)}</span>
                <span>{segment.text}</span>
              </button>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
