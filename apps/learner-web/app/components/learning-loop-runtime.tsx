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
  HelpCircle,
  Maximize2,
  Pause,
  PictureInPicture2,
  Play,
  RotateCcw,
  RotateCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  VideoOff,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";

import {
  ApiError,
  type ActivityResponse,
  type LearnerApi,
  type PlaybackEventInput,
} from "../lib/learner-api";

/**
 * Non-canonical video telemetry events. These are downstream observation hooks
 * only and never alter canonical progress, evidence, or authorization.
 */
export type VideoTelemetryEventType =
  | "video_loaded"
  | "video_play"
  | "video_pause"
  | "video_seek"
  | "video_rate_change"
  | "video_volume_change"
  | "video_fullscreen_change"
  | "video_pip_change"
  | "video_captions_toggle"
  | "video_transcript_toggle"
  | "video_transcript_seek"
  | "video_error";

export interface VideoTelemetryEvent {
  type: VideoTelemetryEventType;
  activityId: string;
  currentTime: number;
  duration: number;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

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
  onTelemetryEvent?: (event: VideoTelemetryEvent) => void;
}

export function formatMediaTime(value: number): string {
  const seconds = Math.max(0, Math.floor(Number.isFinite(value) ? value : 0));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function canStartPlayback(
  activity: Pick<ActivityResponse, "state" | "allowed_actions">,
): boolean {
  return (
    ["available", "in_progress"].includes(activity.state.toLowerCase()) &&
    activity.allowed_actions.includes("complete_video")
  );
}

export function isLearnerOnline(): boolean {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

/**
 * Safely resolves an authorized media descriptor from explicit props or the
 * activity's bound media descriptor. Preserves fail-closed behavior when media
 * or provider policy is blocked or unavailable.
 */
export function resolveApprovedMedia(
  activity: ActivityResponse,
  explicitMedia?: AuthorizedVideoMedia | null,
): {
  media: AuthorizedVideoMedia | null;
  state: "approved" | "blocked" | "unavailable";
  reason: string;
} {
  if (explicitMedia && explicitMedia.src) {
    return {
      media: explicitMedia,
      state: "approved",
      reason: "Explicit authorized media descriptor provided.",
    };
  }

  const descriptor = activity.media;
  if (!descriptor) {
    return {
      media: null,
      state: "unavailable",
      reason: "No approved lesson media is connected yet.",
    };
  }

  if (descriptor.state === "blocked") {
    return {
      media: null,
      state: "blocked",
      reason: descriptor.reason || "Lesson media is blocked by content policy.",
    };
  }

  if (descriptor.state !== "approved" || !descriptor.playback_available) {
    return {
      media: null,
      state: "unavailable",
      reason: descriptor.reason || "Approved lesson media is unavailable.",
    };
  }

  const streamUrl =
    descriptor.delivery?.progressive_url || descriptor.delivery?.manifest_url;
  if (!streamUrl) {
    return {
      media: null,
      state: "unavailable",
      reason: "No approved media delivery stream is available.",
    };
  }

  const captions: AuthorizedCaptionTrack[] = (descriptor.captions || [])
    .filter(
      (c) =>
        (c.kind === "captions" || c.kind === "subtitles") &&
        c.state === "ready" &&
        Boolean(c.source_url),
    )
    .map((c) => ({
      src: c.source_url!,
      srclang: c.language,
      label: c.language.toUpperCase(),
      default: c.is_default,
    }));

  return {
    media: {
      src: streamUrl,
      poster: undefined,
      captions: captions.length > 0 ? captions : undefined,
      transcript: undefined,
    },
    state: "approved",
    reason: descriptor.reason || "Media is approved for playback.",
  };
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

export function LockedMediaStage({
  activity,
  moduleHref,
  reason,
}: Pick<VideoViewerProps, "activity" | "moduleHref"> & { reason?: string }) {
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
            ? reason && reason !== "No approved lesson media is connected yet."
              ? reason
              : "The server exposes a completion action, but this activity cannot start playback until approved lesson media is attached."
            : reason ||
              "Playback and completion remain unavailable for this activity until the server resolves the required capability."}
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

export function BlockedMediaStage({
  activity,
  moduleHref,
  reason,
}: Pick<VideoViewerProps, "activity" | "moduleHref"> & { reason?: string }) {
  return (
    <div
      className="momentum-video-stage momentum-video-stage--blocked"
      role="status"
      aria-label={`Lesson media for ${activity.title} is blocked by policy`}
    >
      <div className="momentum-video-stage__topline">
        <span className="momentum-video-stage__index">01</span>
        <span>LESSON PLAYBACK</span>
        <span className="momentum-video-stage__badge">
          <ShieldAlert size={14} aria-hidden="true" />
          Media policy blocked
        </span>
      </div>
      <div className="momentum-video-stage__copy">
        <div className="momentum-video-stage__icon" aria-hidden="true">
          <ShieldAlert size={28} />
        </div>
        <p className="momentum-video-stage__eyebrow">
          Server-authorized policy
        </p>
        <h3>Lesson media blocked by policy.</h3>
        <p>
          {reason ||
            "Playback is blocked by content and distribution policy for this activity."}
        </p>
      </div>
      <div className="momentum-video-stage__footer">
        <span>
          <ShieldCheck size={15} aria-hidden="true" />
          Watch evidence cannot be submitted while media is blocked.
        </span>
        <Link href={moduleHref}>Return to module</Link>
      </div>
    </div>
  );
}

export function CompletedMediaStage({
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

export interface CaptionsTranscriptPanelProps {
  captions?: AuthorizedCaptionTrack[];
  transcript?: AuthorizedTranscriptSegment[];
  currentTime: number;
  onSeek: (seconds: number) => void;
  captionsEnabled: boolean;
  onToggleCaptions: () => void;
  isOpen: boolean;
  onToggleOpen: () => void;
  onTelemetry?: (event: VideoTelemetryEvent) => void;
  activityId?: string;
  duration?: number;
}

export function CaptionsTranscriptPanel({
  captions,
  transcript,
  currentTime,
  onSeek,
  captionsEnabled,
  onToggleCaptions,
  isOpen,
  onToggleOpen,
  onTelemetry,
  activityId = "",
  duration = 0,
}: CaptionsTranscriptPanelProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const activeSegmentRef = useRef<HTMLButtonElement | null>(null);

  const filteredSegments = useMemo(() => {
    if (!transcript?.length) return [];
    if (!searchQuery.trim()) return transcript;
    const lower = searchQuery.toLowerCase();
    return transcript.filter((seg) => seg.text.toLowerCase().includes(lower));
  }, [transcript, searchQuery]);

  useEffect(() => {
    if (!isOpen || !activeSegmentRef.current) return;
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!prefersReducedMotion) {
      activeSegmentRef.current.scrollIntoView?.({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [currentTime, isOpen]);

  const hasTranscript = Boolean(transcript?.length);
  const hasCaptions = Boolean(captions?.length);

  return (
    <details
      className="momentum-video-transcript"
      open={isOpen}
      onToggle={(event) => {
        const nextOpen = event.currentTarget.open;
        if (nextOpen !== isOpen) {
          onToggleOpen();
          onTelemetry?.({
            type: "video_transcript_toggle",
            activityId,
            currentTime,
            duration,
            timestamp: new Date().toISOString(),
            metadata: { open: nextOpen },
          });
        }
      }}
    >
      <summary>
        <FileText size={17} aria-hidden="true" />
        <span>Open transcript</span>
        <span>
          {hasTranscript
            ? `${transcript!.length} segments`
            : hasCaptions
              ? "Captions available"
              : "Not available"}
        </span>
      </summary>
      <div className="momentum-video-transcript__body">
        {hasTranscript ? (
          <>
            <div className="momentum-video-transcript__toolbar">
              <div className="momentum-video-transcript__search-wrap">
                <Search size={14} aria-hidden="true" />
                <input
                  type="search"
                  className="momentum-video-transcript__search"
                  placeholder="Search transcript…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  aria-label="Filter transcript by keyword"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    className="momentum-video-transcript__clear-search"
                    onClick={() => setSearchQuery("")}
                    aria-label="Clear transcript search"
                  >
                    <X size={12} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
              {hasCaptions ? (
                <button
                  type="button"
                  className={`momentum-video-transcript__caption-toggle${captionsEnabled ? " is-active" : ""}`}
                  onClick={() => {
                    onToggleCaptions();
                    onTelemetry?.({
                      type: "video_captions_toggle",
                      activityId,
                      currentTime,
                      duration,
                      timestamp: new Date().toISOString(),
                      metadata: { enabled: !captionsEnabled },
                    });
                  }}
                  aria-pressed={captionsEnabled}
                >
                  <Captions size={14} aria-hidden="true" />
                  <span>
                    {captionsEnabled ? "Captions on" : "Captions off"}
                  </span>
                </button>
              ) : null}
            </div>
            <div
              className="momentum-video-transcript__segments"
              role="region"
              aria-label="Transcript text segments"
              tabIndex={0}
            >
              {filteredSegments.length > 0 ? (
                filteredSegments.map((segment) => {
                  const isActive =
                    currentTime >= segment.start && currentTime < segment.end;
                  return (
                    <button
                      type="button"
                      key={`${segment.start}-${segment.end}-${segment.text}`}
                      ref={isActive ? activeSegmentRef : null}
                      className={isActive ? "is-active" : undefined}
                      aria-current={isActive ? "time" : undefined}
                      onClick={() => {
                        onSeek(segment.start);
                        onTelemetry?.({
                          type: "video_transcript_seek",
                          activityId,
                          currentTime: segment.start,
                          duration,
                          timestamp: new Date().toISOString(),
                          metadata: {
                            target_seconds: segment.start,
                            text: segment.text,
                          },
                        });
                      }}
                    >
                      <span>{formatMediaTime(segment.start)}</span>
                      <span>{segment.text}</span>
                    </button>
                  );
                })
              ) : (
                <p className="momentum-video-transcript__empty">
                  No transcript segments match “{searchQuery}”.
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="momentum-video-transcript__empty">
            <p>Transcript is not available for this lesson.</p>
            {hasCaptions ? (
              <p className="momentum-video-transcript__hint">
                Timed captions are connected and can be viewed directly on the
                video player.
              </p>
            ) : null}
          </div>
        )}
      </div>
    </details>
  );
}

export function VideoKeyboardShortcutsDialog({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  if (!isOpen) return null;
  const shortcuts = [
    { key: "Space / K", action: "Play or pause lesson" },
    { key: "← / →", action: "Seek backward / forward 5 seconds" },
    { key: "J / L", action: "Skip backward / forward 10 seconds" },
    { key: "↑ / ↓", action: "Volume up / down 10%" },
    { key: "M", action: "Mute or unmute audio" },
    { key: "C", action: "Toggle closed captions" },
    { key: "T", action: "Toggle transcript panel" },
    { key: "F", action: "Toggle fullscreen" },
    { key: "?", action: "Toggle keyboard shortcuts guide" },
    { key: "Esc", action: "Close shortcut guide or transcript" },
  ];

  return (
    <div
      className="momentum-video-shortcuts"
      role="dialog"
      aria-label="Player keyboard shortcuts"
      aria-modal="false"
    >
      <div className="momentum-video-shortcuts__header">
        <strong>Keyboard shortcuts</strong>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close keyboard shortcuts"
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>
      <ul className="momentum-video-shortcuts__list">
        {shortcuts.map((s) => (
          <li key={s.key}>
            <kbd>{s.key}</kbd>
            <span>{s.action}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VideoViewer({
  activity,
  api,
  moduleHref,
  media = null,
  onPlaybackCommitted,
  onTelemetryEvent,
}: VideoViewerProps) {
  const mediaResolution = useMemo(
    () => resolveApprovedMedia(activity, media),
    [activity, media],
  );
  const activeMedia = mediaResolution.media;
  const isBlocked = mediaResolution.state === "blocked";
  const authorized = Boolean(activeMedia?.src) && canStartPlayback(activity);

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
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [canFullscreen, setCanFullscreen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [canPictureInPicture, setCanPictureInPicture] = useState(false);
  const [hasEnded, setHasEnded] = useState(false);
  const [playbackSessionNeedsRetry, setPlaybackSessionNeedsRetry] =
    useState(false);
  const [mediaState, setMediaState] = useState<MediaState>(
    authorized ? "loading" : isBlocked ? "blocked" : "blocked",
  );
  const [mediaMessage, setMediaMessage] = useState(
    authorized
      ? "Loading approved lesson media…"
      : isBlocked
        ? "Lesson media is blocked by content policy."
        : "Approved lesson media is unavailable.",
  );
  const backgroundedRef = useRef(false);

  const emitTelemetry = useCallback(
    (type: VideoTelemetryEventType, metadata?: Record<string, unknown>) => {
      onTelemetryEvent?.({
        type,
        activityId: activity.id,
        currentTime: videoRef.current?.currentTime ?? currentTime,
        duration: duration || (videoRef.current?.duration ?? 0),
        timestamp: new Date().toISOString(),
        metadata,
      });
    },
    [activity.id, currentTime, duration, onTelemetryEvent],
  );

  const updateStatus = useCallback((next: PlaybackStatus, message: string) => {
    if (!mountedRef.current) return;
    statusRef.current = next;
    setStatus(next);
    setStatusMessage(message);
  }, []);

  const resetPlaybackSession = useCallback((needsRetry = false) => {
    sessionRef.current = null;
    pendingHeartbeatRef.current = null;
    finishReadyRef.current = false;
    sequenceRef.current = 0;
    watchCursorRef.current = 0;
    setPlaybackSessionNeedsRetry(needsRetry);
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
          if (
            statusRef.current !== "saving" &&
            statusRef.current !== "submitted"
          ) {
            updateStatus(
              "watching",
              "Watch progress is being recorded by the server.",
            );
          }
          return true;
        })
        .catch((error: unknown) => {
          if (isPlaybackSessionInvalid(error)) {
            resetPlaybackSession(true);
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
      if (
        !sessionRef.current ||
        sessionRef.current.closed ||
        finishReadyRef.current
      ) {
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
          throw new Error(
            "The server did not return a playback authorization token.",
          );
        }
        const expiresAt = Date.parse(started.expires_at);
        if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
          throw new Error("The server did not return a valid playback expiry.");
        }
        const currentActivity = await api.activity(activity.id);
        sessionRef.current = {
          id: started.session_id,
          token: started.session_token,
          revision: started.revision,
          activityRevision: currentActivity.revision,
          expiresAt,
          closed: false,
        };
        setPlaybackSessionNeedsRetry(false);
        sequenceRef.current = 0;
        pendingHeartbeatRef.current = null;
        watchCursorRef.current = 0;
        finishReadyRef.current = false;
        if (started.duration_seconds > 0) setDuration(started.duration_seconds);
        updateStatus(
          "watching",
          "Watch progress is being recorded by the server.",
        );
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
          const flushed = await flushWatch(
            video.duration || duration || video.currentTime,
          );
          if (!flushed) return;
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
          resetPlaybackSession(true);
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
        setMediaMessage(
          isBlocked
            ? mediaResolution.reason ||
                "Lesson media is blocked by content policy."
            : "Approved lesson media is unavailable.",
        );
        return;
      }
      setMediaState("loading");
      setMediaMessage("Loading approved lesson media…");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [authorized, isBlocked, mediaResolution.reason]);

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

  useEffect(() => {
    function onFullscreenChange() {
      const isFs = Boolean(document.fullscreenElement);
      setIsFullscreen(isFs);
      emitTelemetry("video_fullscreen_change", { fullscreen: isFs });
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [emitTelemetry]);

  useEffect(() => {
    mountedRef.current = true;
    unmountingRef.current = false;
    const video = videoRef.current;
    return () => {
      unmountingRef.current = true;
      mountedRef.current = false;
      video?.pause();
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !activeMedia?.captions?.length) return;
    for (let index = 0; index < video.textTracks.length; index += 1) {
      video.textTracks[index].mode = captionsEnabled ? "showing" : "hidden";
    }
  }, [activeMedia?.captions?.length, captionsEnabled]);

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
    emitTelemetry("video_play");
  }, [emitTelemetry, startPlaybackAndPlay]);

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
    emitTelemetry("video_pause");
    if (!unmountingRef.current) void flushWatch();
  }, [emitTelemetry, flushWatch, hasEnded, mediaState]);

  const handleSeeked = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const nextPosition = Math.max(0, video.currentTime);
    const previousPosition = watchCursorRef.current;
    watchCursorRef.current = nextPosition;
    if (
      sessionRef.current &&
      Math.abs(nextPosition - previousPosition) > 0.25
    ) {
      void sendPlaybackEvent("seek", nextPosition, nextPosition);
    }
    emitTelemetry("video_seek", {
      from: previousPosition,
      to: nextPosition,
    });
  }, [emitTelemetry, sendPlaybackEvent]);

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
    emitTelemetry("video_loaded", {
      duration: videoRef.current?.duration ?? duration,
    });
  }, [duration, emitTelemetry, isPlaying]);

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
    emitTelemetry("video_error", {
      message: "Approved lesson media could not be loaded.",
    });
    videoRef.current?.pause();
  }, [emitTelemetry, updateStatus]);

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
    emitTelemetry("video_volume_change", {
      muted: video.muted,
      volume: video.volume,
    });
  }, [emitTelemetry]);

  const changeVolume = useCallback(
    (next: number) => {
      const video = videoRef.current;
      if (!video) return;
      const normalized = Math.min(1, Math.max(0, next));
      video.volume = normalized;
      video.muted = normalized === 0;
      setVolume(normalized);
      setIsMuted(video.muted);
      emitTelemetry("video_volume_change", {
        volume: normalized,
        muted: video.muted,
      });
    },
    [emitTelemetry],
  );

  const changeRate = useCallback(
    (next: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.playbackRate = next;
      setPlaybackRate(next);
      emitTelemetry("video_rate_change", { rate: next });
    },
    [emitTelemetry],
  );

  const seek = useCallback((next: number) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(next)) return;
    video.currentTime = Math.min(Math.max(0, next), video.duration || next);
    setCurrentTime(video.currentTime);
  }, []);

  const skipTime = useCallback(
    (delta: number) => {
      const video = videoRef.current;
      if (!video) return;
      const target = Math.min(
        Math.max(0, video.currentTime + delta),
        video.duration || duration || video.currentTime + delta,
      );
      seek(target);
      emitTelemetry("video_seek", { delta, target });
    },
    [duration, emitTelemetry, seek],
  );

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
    void video
      .requestPictureInPicture()
      .then(() => {
        emitTelemetry("video_pip_change", { pip: true });
      })
      .catch((error: unknown) => {
        updateStatus("error", playbackErrorMessage(error));
      });
  }, [emitTelemetry, updateStatus]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        if (event.key === "Escape") {
          target.blur();
        }
        return;
      }

      switch (event.key) {
        case " ":
        case "k":
        case "K":
          event.preventDefault();
          togglePlay();
          break;
        case "ArrowLeft":
          event.preventDefault();
          seek(currentTime - 5);
          break;
        case "ArrowRight":
          event.preventDefault();
          seek(currentTime + 5);
          break;
        case "j":
        case "J":
          event.preventDefault();
          skipTime(-10);
          break;
        case "l":
        case "L":
          event.preventDefault();
          skipTime(10);
          break;
        case "ArrowUp":
          event.preventDefault();
          changeVolume(volume + 0.1);
          break;
        case "ArrowDown":
          event.preventDefault();
          changeVolume(volume - 0.1);
          break;
        case "m":
        case "M":
          event.preventDefault();
          toggleMute();
          break;
        case "f":
        case "F":
          event.preventDefault();
          toggleFullscreen();
          break;
        case "c":
        case "C":
          if (activeMedia?.captions?.length) {
            event.preventDefault();
            const next = !captionsEnabled;
            setCaptionsEnabled(next);
            emitTelemetry("video_captions_toggle", { enabled: next });
          }
          break;
        case "t":
        case "T":
          if (
            activeMedia?.transcript?.length ||
            activeMedia?.captions?.length
          ) {
            event.preventDefault();
            const next = !transcriptOpen;
            setTranscriptOpen(next);
            emitTelemetry("video_transcript_toggle", { open: next });
          }
          break;
        case "?":
          event.preventDefault();
          setShortcutsOpen((prev) => !prev);
          break;
        case "Escape":
          if (shortcutsOpen) {
            event.preventDefault();
            setShortcutsOpen(false);
          } else if (transcriptOpen) {
            event.preventDefault();
            setTranscriptOpen(false);
          }
          break;
      }
    },
    [
      activeMedia?.captions?.length,
      activeMedia?.transcript?.length,
      captionsEnabled,
      changeVolume,
      currentTime,
      emitTelemetry,
      seek,
      shortcutsOpen,
      skipTime,
      toggleFullscreen,
      toggleMute,
      togglePlay,
      transcriptOpen,
      volume,
    ],
  );

  const progress = useMemo(
    () =>
      duration > 0
        ? Math.min(100, Math.max(0, (currentTime / duration) * 100))
        : 0,
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

  if (!authorized || !activeMedia) {
    if (activity.state.toLowerCase() === "completed") {
      return (
        <section
          className="momentum-video-viewer"
          aria-labelledby={`video-title-${activity.id}`}
        >
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
          <div
            className="momentum-video-viewer__facts"
            aria-label="Video lesson status"
          >
            <span>
              <CheckCircle2 size={15} aria-hidden="true" />
              Completion is recorded by the server
            </span>
          </div>
        </section>
      );
    }

    if (isBlocked) {
      return (
        <section
          className="momentum-video-viewer"
          aria-labelledby={`video-title-${activity.id}`}
        >
          <div className="momentum-video-viewer__heading">
            <div>
              <p className="momentum-video-viewer__eyebrow">
                <CirclePlay size={16} aria-hidden="true" />
                Video lesson
              </p>
              <h2 id={`video-title-${activity.id}`}>{activity.title}</h2>
            </div>
            <span className="momentum-video-viewer__policy">
              <ShieldAlert size={15} aria-hidden="true" />
              Policy blocked
            </span>
          </div>
          <BlockedMediaStage
            activity={activity}
            moduleHref={moduleHref}
            reason={mediaResolution.reason}
          />
          <div
            className="momentum-video-viewer__facts"
            aria-label="Video lesson status"
          >
            <span>
              <CheckCircle2 size={15} aria-hidden="true" />
              Completion is server-determined
            </span>
            <span>
              <ShieldAlert size={15} aria-hidden="true" />
              Policy blocked: playback restricted
            </span>
          </div>
        </section>
      );
    }

    return (
      <section
        className="momentum-video-viewer"
        aria-labelledby={`video-title-${activity.id}`}
      >
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
        <LockedMediaStage
          activity={activity}
          moduleHref={moduleHref}
          reason={mediaResolution.reason}
        />
        <div
          className="momentum-video-viewer__facts"
          aria-label="Video lesson status"
        >
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
    <section
      className="momentum-video-viewer"
      aria-labelledby={`video-title-${activity.id}`}
    >
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

      <div
        className="momentum-video-player"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        role="region"
        aria-label={`Video player for ${activity.title}`}
      >
        <div
          className="momentum-video-player__stage"
          data-media-state={mediaState}
        >
          <video
            ref={videoRef}
            className="momentum-video-player__video"
            src={activeMedia.src}
            poster={activeMedia.poster}
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
            {activeMedia.captions?.map((track) => (
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
          <div
            className="momentum-video-player__live-state"
            role="status"
            aria-live="polite"
          >
            {visibleStatusMessage || "Playback has not started."}
          </div>
          <VideoKeyboardShortcutsDialog
            isOpen={shortcutsOpen}
            onClose={() => setShortcutsOpen(false)}
          />
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
            aria-keyshortcuts="k Space"
          >
            {isPlaying ? (
              <Pause size={18} aria-hidden="true" />
            ) : (
              <Play size={18} aria-hidden="true" />
            )}
            <span>{isPlaying ? "Pause" : "Play"}</span>
          </button>
          <button
            className="momentum-video-controls__icon momentum-video-controls__skip"
            type="button"
            onClick={() => skipTime(-10)}
            aria-label="Skip back 10 seconds (J)"
            aria-keyshortcuts="j"
          >
            <RotateCcw size={16} aria-hidden="true" />
          </button>
          <button
            className="momentum-video-controls__icon momentum-video-controls__skip"
            type="button"
            onClick={() => skipTime(10)}
            aria-label="Skip forward 10 seconds (L)"
            aria-keyshortcuts="l"
          >
            <RotateCw size={16} aria-hidden="true" />
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
            aria-valuemin={0}
            aria-valuemax={duration || 0}
            aria-valuenow={Math.round(currentTime)}
            aria-valuetext={`${formatMediaTime(currentTime)} of ${formatMediaTime(duration)}`}
          />
          <button
            className="momentum-video-controls__icon"
            type="button"
            onClick={toggleMute}
            aria-label={isMuted ? "Unmute lesson" : "Mute lesson"}
            aria-keyshortcuts="m"
          >
            {isMuted ? (
              <VolumeX size={18} aria-hidden="true" />
            ) : (
              <Volume2 size={18} aria-hidden="true" />
            )}
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
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round((isMuted ? 0 : volume) * 100)}
          />
          <label className="momentum-video-controls__rate">
            <Gauge size={16} aria-hidden="true" />
            <span className="sr-only">Playback speed</span>
            <select
              value={playbackRate}
              onChange={(event) => changeRate(Number(event.target.value))}
              aria-label="Playback speed"
            >
              {[0.75, 1, 1.25, 1.5, 2].map((rate) => (
                <option key={rate} value={rate}>
                  {rate}×
                </option>
              ))}
            </select>
          </label>
          {activeMedia.captions?.length ? (
            <button
              className={`momentum-video-controls__icon${captionsEnabled ? " is-active" : ""}`}
              type="button"
              onClick={() => {
                const next = !captionsEnabled;
                setCaptionsEnabled(next);
                emitTelemetry("video_captions_toggle", { enabled: next });
              }}
              aria-pressed={captionsEnabled}
              aria-label={captionsEnabled ? "Hide captions" : "Show captions"}
              aria-keyshortcuts="c"
            >
              <Captions size={18} aria-hidden="true" />
            </button>
          ) : null}
          {activeMedia.transcript?.length || activeMedia.captions?.length ? (
            <button
              className={`momentum-video-controls__icon${transcriptOpen ? " is-active" : ""}`}
              type="button"
              onClick={() => {
                const next = !transcriptOpen;
                setTranscriptOpen(next);
                emitTelemetry("video_transcript_toggle", { open: next });
              }}
              aria-expanded={transcriptOpen}
              aria-label={
                transcriptOpen ? "Close transcript" : "Open transcript"
              }
              aria-keyshortcuts="t"
            >
              <FileText size={18} aria-hidden="true" />
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
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
              aria-keyshortcuts="f"
            >
              <Maximize2 size={18} aria-hidden="true" />
            </button>
          ) : null}
          <button
            className={`momentum-video-controls__icon${shortcutsOpen ? " is-active" : ""}`}
            type="button"
            onClick={() => setShortcutsOpen((prev) => !prev)}
            aria-label="Show keyboard shortcuts"
            aria-expanded={shortcutsOpen}
          >
            <HelpCircle size={17} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="momentum-video-viewer__status-row">
        <div>
          <span
            className={`momentum-video-viewer__status momentum-video-viewer__status--${status}`}
          >
            <span
              className="momentum-video-viewer__status-dot"
              aria-hidden="true"
            />
            {statusLabel}
          </span>
          <p className="momentum-video-viewer__status-copy">
            {visibleStatusMessage || "Start the lesson when you are ready."}
          </p>
        </div>
        <div className="momentum-video-viewer__status-actions">
          {status === "error" &&
          (hasEnded || mediaState === "error" || playbackSessionNeedsRetry) ? (
            <button
              className="momentum-video-viewer__retry"
              type="button"
              onClick={() =>
                mediaState === "error" &&
                !hasEnded &&
                !playbackSessionNeedsRetry
                  ? retryMedia()
                  : void retryPlaybackSave()
              }
            >
              {mediaState === "error" && !hasEnded && !playbackSessionNeedsRetry
                ? "Retry media"
                : "Retry server save"}
            </button>
          ) : null}
          <Link href={moduleHref}>Return to module</Link>
        </div>
      </div>

      {activeMedia.transcript?.length || activeMedia.captions?.length ? (
        <CaptionsTranscriptPanel
          captions={activeMedia.captions}
          transcript={activeMedia.transcript}
          currentTime={currentTime}
          onSeek={seek}
          captionsEnabled={captionsEnabled}
          onToggleCaptions={() => {
            const next = !captionsEnabled;
            setCaptionsEnabled(next);
            emitTelemetry("video_captions_toggle", { enabled: next });
          }}
          isOpen={transcriptOpen}
          onToggleOpen={() => setTranscriptOpen((prev) => !prev)}
          onTelemetry={onTelemetryEvent}
          activityId={activity.id}
          duration={duration}
        />
      ) : null}
    </section>
  );
}
