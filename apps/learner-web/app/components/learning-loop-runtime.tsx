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
  Settings2,
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
import { useDevelopmentMediaTransport } from "./development-media-bridge";

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

/**
 * A quality option is only renderable when an upstream approved media adapter
 * supplies its already-authorized delivery URL. The learner client never
 * derives a rendition URL from IDs, object keys, or provider metadata.
 */
export interface AuthorizedVideoQuality {
  id: string;
  label: string;
  protocol: "progressive";
  contentType: string;
  src: string;
  width?: number;
  height?: number;
  bitrateKbps?: number;
}

export interface AuthorizedVideoMedia {
  protocol: "progressive";
  contentType: string;
  src: string;
  poster?: string;
  captions?: AuthorizedCaptionTrack[];
  transcript?: AuthorizedTranscriptSegment[];
  /** Playback rates authorized by the server/media policy. */
  playbackRates?: readonly number[];
  /** Renditions with server-issued, already-authorized delivery URLs. */
  qualities?: readonly AuthorizedVideoQuality[];
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
  | "backgrounded"
  | "offline";

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
  /** Reuse the containing activity heading instead of repeating its title. */
  labelledBy?: string;
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

const manifestLikeMediaUrlPattern =
  /(?:^|[/?._-])(?:manifest|master|playlist)(?:[/?._?#-]|$)|\.(?:m3u8|mpd)(?:[?#]|$)|(?:[?&#=_-])(?:m3u8|mpd)(?:[&#/?._-]|$)/i;

const shortcutInteractiveSelector =
  'button, a, input, textarea, select, summary, video, label, [contenteditable="true"], [role="button"], [role="link"], [role="slider"], [role="tab"], [role="menuitem"]';

export function isApprovedProgressiveMediaSource(
  source:
    | Pick<AuthorizedVideoMedia, "protocol" | "contentType" | "src">
    | Pick<AuthorizedVideoQuality, "protocol" | "contentType" | "src">,
): boolean {
  if (
    typeof source.protocol !== "string" ||
    typeof source.contentType !== "string" ||
    typeof source.src !== "string"
  ) {
    return false;
  }
  try {
    const url = new URL(source.src);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return false;
    if (manifestLikeMediaUrlPattern.test(decodeURIComponent(url.pathname)))
      return false;
  } catch {
    return false;
  }
  const contentType = source.contentType.split(";", 1)[0].trim().toLowerCase();
  return (
    source.protocol === "progressive" &&
    (contentType === "video/mp4" || contentType === "video/webm") &&
    Boolean(source.src.trim()) &&
    !manifestLikeMediaUrlPattern.test(source.src)
  );
}

export function isInteractiveShortcutTarget(
  target: EventTarget | null,
): boolean {
  const element = target as
    | (EventTarget & {
        closest?: (selector: string) => Element | null;
        isContentEditable?: boolean;
      })
    | null;
  if (!element || typeof element.closest !== "function") return false;
  return Boolean(
    element.isContentEditable || element.closest(shortcutInteractiveSelector),
  );
}

export function isPlaybackConnectionCurrent(
  expectedEpoch: number,
  currentEpoch: number,
  online: boolean,
  refreshPending: boolean,
): boolean {
  return expectedEpoch === currentEpoch && online && !refreshPending;
}

export function supportsPlayerFullscreen(
  player: Pick<HTMLElement, "requestFullscreen"> | null,
): boolean {
  return Boolean(player && typeof player.requestFullscreen === "function");
}

/**
 * Keep media settings strictly capability-driven. Empty/invalid server data
 * produces no settings control, rather than a guessed browser feature list.
 */
export function normalizePlaybackRates(
  rates?: readonly number[] | null,
): number[] {
  return Array.from(
    new Set(
      (rates ?? []).filter(
        (rate): rate is number => Number.isFinite(rate) && rate > 0,
      ),
    ),
  ).sort((left, right) => left - right);
}

export function normalizeQualityOptions(
  qualities?: readonly AuthorizedVideoQuality[] | null,
): AuthorizedVideoQuality[] {
  const seen = new Set<string>();
  return (qualities ?? []).filter((quality) => {
    if (
      !quality ||
      typeof quality.id !== "string" ||
      !quality.id.trim() ||
      typeof quality.label !== "string" ||
      !quality.label.trim() ||
      !isApprovedProgressiveMediaSource(quality) ||
      typeof quality.src !== "string" ||
      !quality.src.trim() ||
      seen.has(quality.id)
    ) {
      return false;
    }
    seen.add(quality.id);
    return true;
  });
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
  // Local presentation props cannot override a server denial or open a new
  // playback capability. Preserve the existing tracked adapter only when no
  // server descriptor is present and complete_video is already authorized.
  if (!activity.media && canStartPlayback(activity) && explicitMedia) {
    if (!isApprovedProgressiveMediaSource(explicitMedia)) {
      return {
        media: null,
        state: "unavailable",
        reason:
          "Explicit media must use an approved progressive video/mp4 or video/webm source.",
      };
    }
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

  if (
    descriptor.state !== "approved" ||
    descriptor.playback_available !== true
  ) {
    return {
      media: null,
      state: "unavailable",
      reason: descriptor.reason || "Approved lesson media is unavailable.",
    };
  }

  // A separately supplied progressive fallback is usable even when HLS is
  // primary. Never pass a manifest to native video or claim adaptive playback.
  const streamUrl =
    descriptor.delivery?.protocol === "progressive" ||
    descriptor.delivery?.protocol === "hls"
      ? descriptor.delivery.progressive_url
      : null;
  if (!streamUrl) {
    return {
      media: null,
      state: "unavailable",
      reason: "No approved progressive media delivery is available yet.",
    };
  }

  const source = {
    protocol: "progressive" as const,
    contentType: descriptor.content_type || "",
    src: streamUrl,
  };
  if (!isApprovedProgressiveMediaSource(source)) {
    return {
      media: null,
      state: "unavailable",
      reason:
        "Approved media must use a progressive video/mp4 or video/webm source.",
    };
  }

  const captions: AuthorizedCaptionTrack[] = (
    Array.isArray(descriptor.captions) ? descriptor.captions : []
  )
    .filter(
      (c) =>
        c &&
        typeof c.language === "string" &&
        (c.kind === "captions" || c.kind === "subtitles") &&
        c.state === "ready" &&
        typeof c.source_url === "string" &&
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
      protocol: source.protocol,
      contentType: source.contentType,
      src: streamUrl,
      poster: undefined,
      captions: captions.length > 0 ? captions : undefined,
      transcript: undefined,
    },
    state: "approved",
    reason: descriptor.reason || "Media is approved for playback.",
  };
}

type VideoPlaybackMode = "tracked" | "read-only" | "unavailable";

/**
 * Read only the documented application delivery envelope, never verify or
 * manufacture authorization in the browser. These bounds can only withhold
 * playback; the signed URL AND the authenticated byte request remain the
 * authority. No token is logged, stored, or used as learning evidence.
 */
export function approvedDeliveryExpiresAt(
  activity: ActivityResponse,
): number | null {
  const descriptor = activity.media;
  const source = descriptor?.delivery?.progressive_url;
  if (!source || source.length > 8192) return null;
  try {
    const url = new URL(source);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.hash ||
      !url.pathname.startsWith("/v1/media/playback/") ||
      url.searchParams.getAll("token").length !== 1
    )
      return null;
    const token = url.searchParams.get("token")!;
    if (token.length > 4096) return null;
    const match = /^AC-MEDIA\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]{43})$/.exec(
      token,
    );
    if (!match) return null;
    const payload = match[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(
      atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "=")),
    ) as Record<string, unknown>;
    if (
      !claims ||
      typeof claims !== "object" ||
      claims.typ !== "AC-MEDIA" ||
      claims.token_type !== "playback" ||
      !Number.isSafeInteger(claims.iat) ||
      !Number.isSafeInteger(claims.exp) ||
      (claims.iat as number) < 0 ||
      (claims.exp as number) <= (claims.iat as number) ||
      (claims.exp as number) - (claims.iat as number) > 3600 ||
      (claims.iat as number) * 1000 > Date.now() + 30_000 ||
      claims.activity_id !== activity.id ||
      !descriptor?.activity_version ||
      claims.activity_version !== descriptor.activity_version ||
      !descriptor.media_id ||
      claims.asset_id !== descriptor.media_id ||
      !descriptor.media_version_id ||
      claims.version_id !== descriptor.media_version_id ||
      !descriptor.binding_id ||
      claims.binding_id !== descriptor.binding_id ||
      claims.enrollment_id !== activity.enrollment_id ||
      typeof claims.delivery_grant_id !== "string" ||
      !claims.delivery_grant_id ||
      typeof claims.key !== "string" ||
      claims.key.length > 2048 ||
      decodeURIComponent(url.pathname.slice("/v1/media/playback/".length)) !==
        claims.key
    )
      return null;
    return (claims.exp as number) * 1000;
  } catch {
    return null;
  }
}

function playbackMode(
  activity: ActivityResponse,
  source: AuthorizedVideoMedia | null,
): VideoPlaybackMode {
  if (
    activity.kind.toLowerCase() !== "video" ||
    !["available", "in_progress"].includes(activity.state.toLowerCase()) ||
    !source
  )
    return "unavailable";
  const expiresAt = approvedDeliveryExpiresAt(activity);
  // A malformed/expired application token is never rescued by complete_video.
  if (
    activity.media?.delivery?.progressive_url?.includes("/v1/media/") &&
    (expiresAt === null || expiresAt <= Date.now())
  )
    return "unavailable";
  if (canStartPlayback(activity)) return "tracked";
  return expiresAt !== null && expiresAt > Date.now()
    ? "read-only"
    : "unavailable";
}

function playbackContext(
  activity: ActivityResponse,
  media: AuthorizedVideoMedia | null,
  mode: VideoPlaybackMode,
): string {
  return JSON.stringify([
    activity.id,
    activity.enrollment_id,
    activity.program_version_id,
    mode,
    activity.media?.binding_id,
    activity.media?.media_version_id,
    activity.media?.activity_version,
    media?.src,
  ]);
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
  moduleHref,
}: Pick<VideoViewerProps, "activity" | "moduleHref"> & { reason?: string }) {
  return (
    <div
      className="lesson-media-notice"
      role="status"
      aria-label="Lesson video unavailable"
    >
      <span className="lesson-media-notice__icon" aria-hidden="true">
        <VideoOff size={26} />
      </span>
      <div className="lesson-media-notice__copy">
        <h3>This video isn’t available yet</h3>
        <p>
          There’s no playable video attached to this lesson. You can return to
          the module and explore your other available steps.
        </p>
      </div>
      <Link className="button button--outline" href={moduleHref}>
        Back to module
      </Link>
      <p className="lesson-media-notice__note">
        This lesson stays incomplete until you can watch it.
      </p>
    </div>
  );
}

export function BlockedMediaStage({
  activity,
  moduleHref,
}: Pick<VideoViewerProps, "activity" | "moduleHref"> & { reason?: string }) {
  return (
    <div
      className="lesson-media-notice"
      role="status"
      aria-label={`Video for ${activity.title} unavailable`}
    >
      <span className="lesson-media-notice__icon" aria-hidden="true">
        <ShieldAlert size={26} />
      </span>
      <div className="lesson-media-notice__copy">
        <h3>This video can’t be played right now</h3>
        <p>
          Playback is restricted for this lesson. Return to the module to see
          which steps are available.
        </p>
      </div>
      <Link className="button button--outline" href={moduleHref}>
        Back to module
      </Link>
      <p className="lesson-media-notice__note">
        Watching and completion are unavailable for this video.
      </p>
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
  const summaryRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(isOpen);

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

  useEffect(() => {
    if (!isOpen && wasOpenRef.current) {
      summaryRef.current?.focus();
    }
    wasOpenRef.current = isOpen;
  }, [isOpen]);

  const hasTranscript = Boolean(transcript?.length);
  const hasCaptions = Boolean(captions?.length);

  return (
    <details
      id="momentum-video-transcript"
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
      <summary ref={summaryRef}>
        <FileText size={17} aria-hidden="true" />
        <span>
          {hasTranscript ? "Open transcript" : "Captions & transcript"}
        </span>
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
            ) : (
              <p className="momentum-video-transcript__hint">
                Captions and transcript are not available for this lesson yet.
              </p>
            )}
          </div>
        )}
      </div>
    </details>
  );
}

export interface PlaybackSettingsPanelProps {
  playbackRates: readonly number[];
  playbackRate: number;
  onChangeRate: (rate: number) => void;
  qualities: readonly AuthorizedVideoQuality[];
  qualityId: string;
  onChangeQuality: (qualityId: string) => void;
  onClose: () => void;
}

/**
 * Presentation-only media settings. The panel is deliberately omitted when
 * the authorized descriptor does not include a supported capability.
 */
export function PlaybackSettingsPanel({
  playbackRates,
  playbackRate,
  onChangeRate,
  qualities,
  qualityId,
  onChangeQuality,
  onClose,
}: PlaybackSettingsPanelProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const hasRates = playbackRates.length > 0;
  const hasQualities = qualities.length > 0;

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  if (!hasRates && !hasQualities) return null;

  return (
    <section
      id="momentum-video-settings"
      className="momentum-video-settings"
      aria-labelledby="momentum-video-settings-title"
    >
      <div className="momentum-video-settings__header">
        <div>
          <p className="momentum-video-settings__eyebrow">Player settings</p>
          <h3 id="momentum-video-settings-title">Playback settings</h3>
        </div>
        <button
          ref={closeRef}
          className="momentum-video-settings__close"
          type="button"
          onClick={onClose}
          aria-label="Close playback settings"
        >
          <X size={17} aria-hidden="true" />
        </button>
      </div>
      <div className="momentum-video-settings__fields">
        {hasRates ? (
          <label className="momentum-video-settings__field">
            <span>Playback speed</span>
            <select
              value={
                playbackRates.includes(playbackRate)
                  ? playbackRate
                  : (playbackRates[0] ?? 1)
              }
              onChange={(event) => onChangeRate(Number(event.target.value))}
              aria-label="Playback speed"
            >
              {playbackRates.map((rate) => (
                <option key={rate} value={rate}>
                  {rate}×
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {hasQualities ? (
          <label className="momentum-video-settings__field">
            <span>Quality</span>
            <select
              value={qualityId}
              onChange={(event) => onChangeQuality(event.target.value)}
              aria-label="Video quality"
            >
              <option value="auto">Auto</option>
              {qualities.map((quality) => (
                <option key={quality.id} value={quality.id}>
                  {quality.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <p className="momentum-video-settings__note">
        These settings change presentation only. Watch coverage and completion
        remain server-determined.
      </p>
    </section>
  );
}

export function VideoKeyboardShortcutsDialog({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (isOpen) closeRef.current?.focus();
  }, [isOpen]);

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
    { key: "Esc", action: "Close an open player panel" },
  ];

  return (
    <div
      id="momentum-video-shortcuts"
      className="momentum-video-shortcuts"
      role="dialog"
      aria-label="Player keyboard shortcuts"
      aria-modal="false"
    >
      <div className="momentum-video-shortcuts__header">
        <strong>Keyboard shortcuts</strong>
        <button
          ref={closeRef}
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

function VideoViewerHeading({
  activity,
  labelledBy,
}: Pick<VideoViewerProps, "activity" | "labelledBy">) {
  if (labelledBy) return null;
  return (
    <div className="momentum-video-viewer__heading">
      <div>
        <p className="momentum-video-viewer__eyebrow">
          <CirclePlay size={16} aria-hidden="true" /> Video lesson
        </p>
        <h2 id={`video-title-${activity.id}`}>{activity.title}</h2>
      </div>
    </div>
  );
}

export function VideoViewer(props: VideoViewerProps) {
  const resolution = resolveApprovedMedia(props.activity, props.media);
  const mode = playbackMode(props.activity, resolution.media);
  const transport = useDevelopmentMediaTransport(
    mode !== "unavailable" && resolution.media
      ? [
          resolution.media.src,
          ...(resolution.media.captions ?? []).map((track) => track.src),
          ...(resolution.media.qualities ?? []).map((quality) => quality.src),
        ]
      : [],
  );
  const transportSource = resolution.media
    ? transport.resolveUrl(resolution.media.src)
    : null;
  return (
    <VideoViewerSession
      key={JSON.stringify([
        playbackContext(props.activity, resolution.media, mode),
        transportSource,
      ])}
      {...props}
      mode={mode}
      transport={transport}
    />
  );
}

function VideoViewerSession({
  activity,
  api,
  moduleHref,
  labelledBy,
  media = null,
  onPlaybackCommitted,
  onTelemetryEvent,
  mode,
  transport,
}: VideoViewerProps & {
  mode: VideoPlaybackMode;
  transport: ReturnType<typeof useDevelopmentMediaTransport>;
}) {
  const mediaResolution = useMemo(
    () => resolveApprovedMedia(activity, media),
    [activity, media],
  );
  const approvedMedia = mediaResolution.media;
  // Preserve the original approved HTTPS descriptor for every authorization
  // comparison. Only the final native-media transport is adapted for local QA.
  const activeMedia = useMemo(() => {
    if (!approvedMedia) return null;
    const src = transport.resolveUrl(approvedMedia.src);
    if (!src) return null;
    return {
      ...approvedMedia,
      src,
      captions: approvedMedia.captions?.flatMap((track) => {
        const source = transport.resolveUrl(track.src);
        return source ? [{ ...track, src: source }] : [];
      }),
      qualities: approvedMedia.qualities?.flatMap((quality) => {
        const source = transport.resolveUrl(quality.src);
        return source ? [{ ...quality, src: source }] : [];
      }),
    };
  }, [approvedMedia, transport]);
  const isBlocked = mediaResolution.state === "blocked";
  const authorized = mode !== "unavailable" && activeMedia !== null;
  const tracked = mode === "tracked";
  const deliveryExpiresAt = approvedDeliveryExpiresAt(activity);
  const playbackRates = useMemo(
    () => normalizePlaybackRates(activeMedia?.playbackRates),
    [activeMedia?.playbackRates],
  );
  const qualityOptions = useMemo(
    () => normalizeQualityOptions(activeMedia?.qualities),
    [activeMedia?.qualities],
  );
  const hasPlaybackSettings =
    playbackRates.length > 0 || qualityOptions.length > 0;

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
  const [selectedQualityId, setSelectedQualityId] = useState("auto");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [canFullscreen, setCanFullscreen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [canPictureInPicture, setCanPictureInPicture] = useState(false);
  const [hasEnded, setHasEnded] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [authorizationStopped, setAuthorizationStopped] = useState(false);
  const authorizationStoppedRef = useRef(false);
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
  const offlineRef = useRef(false);
  const connectionEpochRef = useRef(0);
  const reconnectRefreshRequiredRef = useRef(false);
  const reconnectRefreshRequestRef = useRef<Promise<boolean> | null>(null);
  const activityRevisionRef = useRef(activity.revision);
  const playerRef = useRef<HTMLDivElement | null>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const shortcutsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const fullscreenTriggerRef = useRef<HTMLButtonElement | null>(null);
  const pictureInPictureTriggerRef = useRef<HTMLButtonElement | null>(null);
  const qualitySwitchRef = useRef(0);
  const settingsWasOpenRef = useRef(false);
  const shortcutsWasOpenRef = useRef(false);
  const effectivePlaybackRate = playbackRates.includes(playbackRate)
    ? playbackRate
    : (playbackRates[0] ?? 1);
  const effectiveQualityId = qualityOptions.some(
    (quality) => quality.id === selectedQualityId,
  )
    ? selectedQualityId
    : "auto";

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

  const isConnectionEpochCurrent = useCallback((epoch: number) => {
    return (
      mountedRef.current &&
      !authorizationStoppedRef.current &&
      isPlaybackConnectionCurrent(
        epoch,
        connectionEpochRef.current,
        isLearnerOnline(),
        false,
      )
    );
  }, []);

  const isPlaybackAllowed = useCallback(
    (epoch: number) => {
      return (
        authorized &&
        mountedRef.current &&
        !authorizationStoppedRef.current &&
        (deliveryExpiresAt === null || deliveryExpiresAt > Date.now()) &&
        isPlaybackConnectionCurrent(
          epoch,
          connectionEpochRef.current,
          isLearnerOnline(),
          reconnectRefreshRequiredRef.current,
        )
      );
    },
    [authorized, deliveryExpiresAt],
  );

  const isCanonicalWriteAllowed = useCallback(
    (epoch: number) => {
      return tracked && isPlaybackAllowed(epoch);
    },
    [isPlaybackAllowed, tracked],
  );

  const stopAuthorization = useCallback(() => {
    authorizationStoppedRef.current = true;
    connectionEpochRef.current += 1;
    sessionRef.current = null;
    setAuthorizationStopped(true);
    setIsPlaying(false);
    const video = videoRef.current;
    video?.pause();
    // Drop buffered delivery as well: an expired grant cannot keep playing a
    // fully buffered object while the next authenticated request is pending.
    video?.removeAttribute("src");
    video?.load();
    setMediaState("blocked");
    updateStatus(
      "error",
      "Playback authorization changed or expired. Reopen the lesson to continue.",
    );
  }, [updateStatus]);

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
      const writeEpoch = connectionEpochRef.current;
      if (!isCanonicalWriteAllowed(writeEpoch)) {
        updateStatus(
          "error",
          "Offline or reconnecting — watch progress was not submitted.",
        );
        return false;
      }
      const session = sessionRef.current;
      if (!session) {
        updateStatus(
          "error",
          "Offline — watch progress was not submitted. Reconnect to continue.",
        );
        return false;
      }
      if (session.closed) return true;
      if (kind === "watch" && endSeconds <= startSeconds + 0.05) return true;

      if (heartbeatRequestRef.current) {
        const previousHeartbeatSucceeded = await heartbeatRequestRef.current;
        if (!previousHeartbeatSucceeded) return false;
        if (!isCanonicalWriteAllowed(writeEpoch)) return false;
      }
      const activeSession = sessionRef.current;
      if (!activeSession || !isCanonicalWriteAllowed(writeEpoch)) return false;

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
      if (!isCanonicalWriteAllowed(writeEpoch)) return false;
      const request = api
        .heartbeatPlayback(activity.id, input, activeSession.token)
        .then((result) => {
          if (!isCanonicalWriteAllowed(writeEpoch)) return false;
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
          if (!isConnectionEpochCurrent(writeEpoch)) return false;
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
    [
      activity.id,
      api,
      isCanonicalWriteAllowed,
      isConnectionEpochCurrent,
      resetPlaybackSession,
      updateStatus,
    ],
  );

  const flushWatch = useCallback(
    async (position?: number): Promise<boolean> => {
      const writeEpoch = connectionEpochRef.current;
      if (!isCanonicalWriteAllowed(writeEpoch)) return false;
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
        if (!isCanonicalWriteAllowed(writeEpoch)) return false;
      }
      const target = position ?? videoRef.current?.currentTime ?? 0;
      const start = watchCursorRef.current;
      if (target <= start + 0.05) return true;
      if (!isCanonicalWriteAllowed(writeEpoch)) return false;
      return sendPlaybackEvent("watch", start, target);
    },
    [isCanonicalWriteAllowed, sendPlaybackEvent],
  );

  const refreshPlaybackAuthorization =
    useCallback(async (): Promise<boolean> => {
      if (!reconnectRefreshRequiredRef.current) return true;
      const refreshEpoch = connectionEpochRef.current;
      if (!isConnectionEpochCurrent(refreshEpoch)) return false;
      if (reconnectRefreshRequestRef.current) {
        return reconnectRefreshRequestRef.current;
      }

      const requestHolder: { promise: Promise<boolean> | null } = {
        promise: null,
      };
      const request = (async () => {
        updateStatus("starting", "Refreshing playback authorization…");
        setMediaState("loading");
        setMediaMessage("Refreshing playback authorization…");
        try {
          const refreshedActivity = await api.activity(activity.id);
          if (!isConnectionEpochCurrent(refreshEpoch)) return false;
          activityRevisionRef.current = refreshedActivity.revision;

          const refreshedResolution = resolveApprovedMedia(
            refreshedActivity,
            media,
          );
          const mediaStillAuthorized =
            refreshedResolution.state === "approved" &&
            playbackContext(
              refreshedActivity,
              refreshedResolution.media,
              playbackMode(refreshedActivity, refreshedResolution.media),
            ) === playbackContext(activity, approvedMedia, mode);
          if (!mediaStillAuthorized) {
            stopAuthorization();
            return false;
          }

          if (transport.enabled) {
            // Reconnect invalidates the local byte mapping only after the
            // unchanged descriptor has been rechecked by the normal API.
            // The new async registration withholds native src until ready.
            transport.refresh();
            return false;
          }

          reconnectRefreshRequiredRef.current = false;
          setPlaybackSessionNeedsRetry(false);
          const video = videoRef.current;
          const canResume = Boolean(video && video.readyState >= 3);
          setMediaState(canResume ? "paused" : "loading");
          setMediaMessage(
            canResume
              ? "Playback authorization refreshed. Press Play to resume."
              : "Playback authorization refreshed. Loading approved lesson media…",
          );
          updateStatus(
            "idle",
            "Playback authorization refreshed. Press Play to resume.",
          );
          return true;
        } catch (error) {
          if (!isConnectionEpochCurrent(refreshEpoch)) return false;
          if (
            error instanceof ApiError &&
            [401, 403, 404].includes(error.status)
          ) {
            stopAuthorization();
            return false;
          }
          setPlaybackSessionNeedsRetry(true);
          setMediaState("error");
          setMediaMessage(
            "Playback authorization could not be refreshed. Reconnect and try again.",
          );
          updateStatus("error", playbackErrorMessage(error));
          return false;
        } finally {
          if (reconnectRefreshRequestRef.current === requestHolder.promise) {
            reconnectRefreshRequestRef.current = null;
          }
        }
      })();
      requestHolder.promise = request;
      reconnectRefreshRequestRef.current = request;
      return request;
    }, [
      approvedMedia,
      activity,
      api,
      isConnectionEpochCurrent,
      media,
      mode,
      transport,
      stopAuthorization,
      updateStatus,
    ]);

  const ensurePlaybackSession = useCallback(async (): Promise<boolean> => {
    if (reconnectRefreshRequiredRef.current) {
      const refreshed = await refreshPlaybackAuthorization();
      if (!refreshed) return false;
    }
    if (!tracked) return isPlaybackAllowed(connectionEpochRef.current);
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
    const startEpoch = connectionEpochRef.current;
    if (!authorized || !isCanonicalWriteAllowed(startEpoch)) {
      updateStatus(
        "error",
        !isLearnerOnline() || offlineRef.current
          ? "Offline — watch progress was not submitted. Reconnect to continue."
          : "Playback is not currently authorized for this activity.",
      );
      return false;
    }
    if (startRequestRef.current) return startRequestRef.current;

    const request = (async () => {
      updateStatus("starting", "Requesting a server playback session…");
      try {
        if (!isCanonicalWriteAllowed(startEpoch)) return false;
        const started = await api.startPlayback(
          activity.id,
          activityRevisionRef.current,
        );
        if (!isConnectionEpochCurrent(startEpoch)) return false;
        if (!started.session_token) {
          throw new Error(
            "The server did not return a playback authorization token.",
          );
        }
        const expiresAt = Date.parse(started.expires_at);
        if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
          throw new Error("The server did not return a valid playback expiry.");
        }
        if (!isConnectionEpochCurrent(startEpoch)) return false;
        const currentActivity = await api.activity(activity.id);
        if (!isCanonicalWriteAllowed(startEpoch)) return false;
        const currentMedia = resolveApprovedMedia(currentActivity, media).media;
        if (
          playbackContext(
            currentActivity,
            currentMedia,
            playbackMode(currentActivity, currentMedia),
          ) !== playbackContext(activity, approvedMedia, mode)
        ) {
          stopAuthorization();
          return false;
        }
        activityRevisionRef.current = currentActivity.revision;
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
        if (!isConnectionEpochCurrent(startEpoch)) return false;
        updateStatus("error", playbackErrorMessage(error));
        return false;
      } finally {
        startRequestRef.current = null;
      }
    })();
    startRequestRef.current = request;
    return request;
  }, [
    activity,
    approvedMedia,
    api,
    authorized,
    isCanonicalWriteAllowed,
    isConnectionEpochCurrent,
    isPlaybackAllowed,
    media,
    mode,
    refreshPlaybackAuthorization,
    resetPlaybackSession,
    stopAuthorization,
    tracked,
    updateStatus,
  ]);

  const startPlaybackAndPlay = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    const playEpoch = connectionEpochRef.current;
    const ok = await ensurePlaybackSession();
    if (!ok || !isPlaybackAllowed(playEpoch)) {
      video.pause();
      return;
    }
    try {
      await video.play();
    } catch (error) {
      updateStatus("error", playbackErrorMessage(error));
    }
  }, [ensurePlaybackSession, isPlaybackAllowed, updateStatus]);

  const completePlayback = useCallback(async () => {
    if (completionRequestRef.current) return completionRequestRef.current;
    const completionEpoch = connectionEpochRef.current;
    const session = sessionRef.current;
    const video = videoRef.current;
    if (!session || !video) return;
    if (!isCanonicalWriteAllowed(completionEpoch)) {
      updateStatus(
        "error",
        "Offline or reconnecting — watch progress was not submitted.",
      );
      return;
    }

    const request = (async () => {
      if (!isCanonicalWriteAllowed(completionEpoch)) return;
      updateStatus("saving", "Saving the final watch interval…");
      try {
        if (!session.closed && !finishReadyRef.current) {
          const flushed = await flushWatch(
            video.duration || duration || video.currentTime,
          );
          if (!flushed) return;
          if (!isCanonicalWriteAllowed(completionEpoch)) return;
          finishReadyRef.current = true;
        }
        if (!isCanonicalWriteAllowed(completionEpoch)) return;
        const activeSession = sessionRef.current;
        if (!activeSession) return;
        if (!activeSession.closed) {
          if (!isCanonicalWriteAllowed(completionEpoch)) return;
          const finished = await api.finishPlayback(
            activity.id,
            activeSession.id,
            activeSession.revision,
            activeSession.token,
          );
          if (!isCanonicalWriteAllowed(completionEpoch)) return;
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
        if (!isConnectionEpochCurrent(completionEpoch)) return;
        const currentActivity = await api.activity(activity.id);
        if (!isCanonicalWriteAllowed(completionEpoch)) return;
        const currentMedia = resolveApprovedMedia(currentActivity, media).media;
        if (
          playbackContext(
            currentActivity,
            currentMedia,
            playbackMode(currentActivity, currentMedia),
          ) !== playbackContext(activity, approvedMedia, mode)
        ) {
          stopAuthorization();
          return;
        }
        activityRevisionRef.current = currentActivity.revision;
        if (!isCanonicalWriteAllowed(completionEpoch)) return;
        await api.submitEvidence(
          activity.id,
          "video_watch",
          {},
          currentActivity.revision,
          finishedSession.id,
          finishedSession.token,
        );
        if (!isCanonicalWriteAllowed(completionEpoch)) return;
        updateStatus(
          "submitted",
          "Watch progress submitted. The server will determine completion.",
        );
        if (!isCanonicalWriteAllowed(completionEpoch)) return;
        await onPlaybackCommitted?.();
      } catch (error) {
        if (!isConnectionEpochCurrent(completionEpoch)) return;
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
    activity,
    approvedMedia,
    api,
    duration,
    flushWatch,
    isCanonicalWriteAllowed,
    isConnectionEpochCurrent,
    media,
    mode,
    onPlaybackCommitted,
    resetPlaybackSession,
    stopAuthorization,
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
    const player = playerRef.current;
    if (!video || !player || !authorized) return;
    const safariVideo = video as HTMLVideoElement & {
      webkitEnterFullscreen?: () => void;
      webkitSupportsFullscreen?: boolean;
    };
    setCanFullscreen(
      typeof document !== "undefined" &&
        ((Boolean(document.fullscreenEnabled) &&
          supportsPlayerFullscreen(player)) ||
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
      const isFs = document.fullscreenElement === playerRef.current;
      setIsFullscreen(isFs);
      emitTelemetry("video_fullscreen_change", { fullscreen: isFs });
      if (!isFs) {
        window.requestAnimationFrame(() =>
          fullscreenTriggerRef.current?.focus(),
        );
      }
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [emitTelemetry]);

  useEffect(() => {
    if (!settingsOpen && settingsWasOpenRef.current) {
      settingsTriggerRef.current?.focus();
    }
    settingsWasOpenRef.current = settingsOpen;
  }, [settingsOpen]);

  useEffect(() => {
    if (!shortcutsOpen && shortcutsWasOpenRef.current) {
      shortcutsTriggerRef.current?.focus();
    }
    shortcutsWasOpenRef.current = shortcutsOpen;
  }, [shortcutsOpen]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onPictureInPictureChange = (event: Event) => {
      const inPictureInPicture = event.type === "enterpictureinpicture";
      emitTelemetry("video_pip_change", { pip: inPictureInPicture });
      if (!inPictureInPicture) {
        window.requestAnimationFrame(() =>
          pictureInPictureTriggerRef.current?.focus(),
        );
      }
    };
    const onWebkitEndFullscreen = () => {
      video.controls = false;
      emitTelemetry("video_fullscreen_change", { fullscreen: false });
      window.requestAnimationFrame(() => fullscreenTriggerRef.current?.focus());
    };
    video.addEventListener("enterpictureinpicture", onPictureInPictureChange);
    video.addEventListener("leavepictureinpicture", onPictureInPictureChange);
    video.addEventListener("webkitendfullscreen", onWebkitEndFullscreen);
    return () => {
      video.removeEventListener(
        "enterpictureinpicture",
        onPictureInPictureChange,
      );
      video.removeEventListener(
        "leavepictureinpicture",
        onPictureInPictureChange,
      );
      video.removeEventListener("webkitendfullscreen", onWebkitEndFullscreen);
    };
  }, [emitTelemetry]);

  useEffect(() => {
    mountedRef.current = true;
    unmountingRef.current = false;
    const video = videoRef.current;
    return () => {
      unmountingRef.current = true;
      mountedRef.current = false;
      connectionEpochRef.current += 1;
      qualitySwitchRef.current += 1;
      video?.pause();
    };
  }, []);

  useEffect(() => {
    if (!authorized || deliveryExpiresAt === null) return;
    const timer = window.setTimeout(
      stopAuthorization,
      Math.max(0, deliveryExpiresAt - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [authorized, deliveryExpiresAt, stopAuthorization]);

  useEffect(() => {
    activityRevisionRef.current = activity.revision;
  }, [activity.revision]);

  useEffect(() => {
    function updateConnectionState() {
      if (!authorized) {
        offlineRef.current = false;
        setIsOffline(false);
        return;
      }

      const nextOffline = !isLearnerOnline();
      if (nextOffline) {
        if (!offlineRef.current) connectionEpochRef.current += 1;
        offlineRef.current = true;
        reconnectRefreshRequiredRef.current = true;
        reconnectRefreshRequestRef.current = null;
        resetPlaybackSession(false);
        setIsOffline(true);
        const video = videoRef.current;
        if (video && !video.paused) video.pause();
        setMediaState("offline");
        setMediaMessage(
          "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
        );
        updateStatus(
          "error",
          "Offline — watch progress was not submitted. Reconnect to continue.",
        );
        return;
      }

      if (!offlineRef.current) return;
      connectionEpochRef.current += 1;
      offlineRef.current = false;
      setIsOffline(false);
      reconnectRefreshRequiredRef.current = true;
      const video = videoRef.current;
      video?.pause();
      setMediaState("loading");
      setMediaMessage("Back online. Refreshing playback authorization…");
      updateStatus("starting", "Refreshing playback authorization…");
      void refreshPlaybackAuthorization();
    }

    updateConnectionState();
    window.addEventListener("online", updateConnectionState);
    window.addEventListener("offline", updateConnectionState);
    return () => {
      window.removeEventListener("online", updateConnectionState);
      window.removeEventListener("offline", updateConnectionState);
    };
  }, [
    authorized,
    refreshPlaybackAuthorization,
    resetPlaybackSession,
    updateStatus,
  ]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !activeMedia?.captions?.length) return;
    for (let index = 0; index < video.textTracks.length; index += 1) {
      video.textTracks[index].mode = captionsEnabled ? "showing" : "hidden";
    }
  }, [activeMedia?.captions?.length, captionsEnabled]);

  useEffect(() => {
    if (videoRef.current && playbackRates.length > 0) {
      videoRef.current.playbackRate = effectivePlaybackRate;
    }
  }, [effectivePlaybackRate, playbackRates]);

  const handlePlay = useCallback(() => {
    if (offlineRef.current || !isLearnerOnline()) {
      videoRef.current?.pause();
      setIsPlaying(false);
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      updateStatus(
        "error",
        "Offline — watch progress was not submitted. Reconnect to continue.",
      );
      return;
    }
    if (reconnectRefreshRequiredRef.current) {
      videoRef.current?.pause();
      setIsPlaying(false);
      void startPlaybackAndPlay();
      return;
    }
    if (tracked && !sessionRef.current) {
      videoRef.current?.pause();
      setIsPlaying(false);
      void startPlaybackAndPlay();
      return;
    }
    if (!isPlaybackAllowed(connectionEpochRef.current)) {
      videoRef.current?.pause();
      setIsPlaying(false);
      if (deliveryExpiresAt !== null && deliveryExpiresAt <= Date.now())
        stopAuthorization();
      return;
    }
    setIsPlaying(true);
    if (!tracked) updateStatus("idle", "");
    setMediaState("playing");
    setMediaMessage("Playing approved lesson media.");
    emitTelemetry("video_play");
  }, [
    deliveryExpiresAt,
    emitTelemetry,
    isPlaybackAllowed,
    startPlaybackAndPlay,
    stopAuthorization,
    tracked,
    updateStatus,
  ]);

  const handlePause = useCallback(() => {
    if (!mountedRef.current) return;
    setIsPlaying(false);
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
    } else if (backgroundedRef.current) {
      setMediaState("backgrounded");
      setMediaMessage("Playback paused while this tab is in the background.");
    } else if (videoRef.current?.ended || hasEnded) {
      setMediaState(tracked ? "processing" : "paused");
      setMediaMessage(
        tracked
          ? "Processing watch evidence with the server…"
          : "Playback ended. Progress has not been recorded.",
      );
    } else if (mediaState !== "processing") {
      setMediaState("paused");
      setMediaMessage("Playback paused. Press Play to resume.");
    }
    emitTelemetry("video_pause");
    if (!unmountingRef.current) void flushWatch();
  }, [emitTelemetry, flushWatch, hasEnded, mediaState, tracked]);

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
    if (offlineRef.current || !isLearnerOnline()) return;
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
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      return;
    }
    if (!backgroundedRef.current && !isPlaying) {
      setMediaState("ready");
      setMediaMessage("Approved lesson media is ready to play.");
    }
  }, [isPlaying]);

  const handleLoadStart = useCallback(() => {
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to retry approved lesson media.",
      );
      return;
    }
    setMediaState("loading");
    setMediaMessage("Loading approved lesson media…");
  }, []);

  const handleCanPlay = useCallback(() => {
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      return;
    }
    if (!backgroundedRef.current && !isPlaying) {
      setMediaState("ready");
      setMediaMessage("Approved lesson media is ready to play.");
    }
    emitTelemetry("video_loaded", {
      duration: videoRef.current?.duration ?? duration,
    });
  }, [duration, emitTelemetry, isPlaying]);

  const handleWaiting = useCallback(() => {
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      return;
    }
    setMediaState("buffering");
    setMediaMessage("Playback is buffering.");
  }, []);

  const handleMediaError = useCallback(() => {
    // Media elements do not expose HTTP status. Revalidate the descriptor
    // before retrying any failed delivery, including an expired/denied URL.
    reconnectRefreshRequiredRef.current = true;
    videoRef.current?.pause();
    setIsPlaying(false);
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      updateStatus(
        "error",
        "Offline — watch progress was not submitted. Reconnect to continue.",
      );
      videoRef.current?.pause();
      return;
    }
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
  }, [emitTelemetry, updateStatus]);

  const retryMedia = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to retry approved lesson media.",
      );
      updateStatus(
        "error",
        "Offline — watch progress was not submitted. Reconnect to continue.",
      );
      return;
    }
    if (
      reconnectRefreshRequiredRef.current &&
      !(await refreshPlaybackAuthorization())
    )
      return;
    if (!isPlaybackAllowed(connectionEpochRef.current)) return;
    updateStatus("idle", "Loading approved lesson media…");
    setMediaState("loading");
    setMediaMessage("Retrying approved lesson media…");
    video.load();
  }, [isPlaybackAllowed, refreshPlaybackAuthorization, updateStatus]);

  useEffect(() => {
    function handleVisibilityChange() {
      const video = videoRef.current;
      if (!video) return;
      if (document.hidden) {
        backgroundedRef.current = true;
        if (!video.paused) video.pause();
        if (offlineRef.current || !isLearnerOnline()) {
          setMediaState("offline");
          setMediaMessage(
            "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
          );
          updateStatus(
            "error",
            "Offline — watch progress was not submitted. Reconnect to continue.",
          );
          return;
        }
        setMediaState("backgrounded");
        setMediaMessage("Playback paused while this tab is in the background.");
        return;
      }
      if (backgroundedRef.current) {
        backgroundedRef.current = false;
        if (offlineRef.current || !isLearnerOnline()) {
          setMediaState("offline");
          setMediaMessage(
            "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
          );
          updateStatus(
            "error",
            "Offline — watch progress was not submitted. Reconnect to continue.",
          );
          return;
        }
        setMediaState("paused");
        setMediaMessage("Playback paused. Press Play to resume.");
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [updateStatus]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (offlineRef.current || !isLearnerOnline()) {
      setMediaState("offline");
      setMediaMessage(
        "Offline — playback is paused. Reconnect to resume; no watch progress was submitted.",
      );
      updateStatus(
        "error",
        "Offline — watch progress was not submitted. Reconnect to continue.",
      );
      return;
    }
    if (video.paused) {
      void startPlaybackAndPlay();
    } else {
      video.pause();
    }
  }, [startPlaybackAndPlay, updateStatus]);

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
      if (!video || !playbackRates.includes(next)) return;
      video.playbackRate = next;
      setPlaybackRate(next);
      emitTelemetry("video_rate_change", { rate: next });
    },
    [emitTelemetry, playbackRates],
  );

  const changeQuality = useCallback(
    (nextQualityId: string) => {
      const video = videoRef.current;
      const isAuthorizedQuality =
        nextQualityId === "auto" ||
        qualityOptions.some((quality) => quality.id === nextQualityId);
      if (!isAuthorizedQuality) return;
      if (!video || !isLearnerOnline()) {
        if (!isLearnerOnline()) {
          setMediaState("offline");
          setMediaMessage(
            "Offline — playback is paused. Reconnect to change presentation settings.",
          );
          updateStatus(
            "error",
            "Offline — watch progress was not submitted. Reconnect to continue.",
          );
        }
        return;
      }
      const targetSrc =
        nextQualityId === "auto"
          ? activeMedia?.src
          : qualityOptions.find((quality) => quality.id === nextQualityId)?.src;
      if (!targetSrc || targetSrc === video.currentSrc) {
        setSelectedQualityId(nextQualityId);
        return;
      }

      const restorePosition = Math.max(0, video.currentTime);
      const resumeAfterLoad = !video.paused;
      const switchId = ++qualitySwitchRef.current;
      const restorePlayback = () => {
        if (
          qualitySwitchRef.current !== switchId ||
          !mountedRef.current ||
          authorizationStoppedRef.current
        )
          return;
        if (Number.isFinite(video.duration) && video.duration > 0) {
          video.currentTime = Math.min(restorePosition, video.duration);
          setCurrentTime(video.currentTime);
        } else {
          video.currentTime = restorePosition;
          setCurrentTime(restorePosition);
        }
        if (resumeAfterLoad) {
          void video.play().catch((error: unknown) => {
            updateStatus("error", playbackErrorMessage(error));
          });
        }
      };

      video.addEventListener("loadedmetadata", restorePlayback, { once: true });
      video.src = targetSrc;
      setSelectedQualityId(nextQualityId);
      setMediaState("loading");
      setMediaMessage("Loading the selected approved quality…");
      video.load();
    },
    [activeMedia?.src, qualityOptions, updateStatus],
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
    const player = playerRef.current;
    if (!video || !player || typeof document === "undefined") return;
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
    fullscreenTriggerRef.current?.focus();
    if (document.fullscreenEnabled && supportsPlayerFullscreen(player)) {
      void player.requestFullscreen().catch(() => {
        updateStatus("error", "Fullscreen could not be opened. Try again.");
        setMediaMessage("Fullscreen could not be opened. Try again.");
      });
      return;
    }
    if (typeof safariVideo.webkitEnterFullscreen === "function") {
      video.controls = true;
      try {
        safariVideo.webkitEnterFullscreen();
      } catch {
        video.controls = false;
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
    pictureInPictureTriggerRef.current?.focus();
    void video
      .requestPictureInPicture()
      .then(() => {
        // The enter/leave events are the source of truth for this
        // presentation-only observation.
      })
      .catch((error: unknown) => {
        updateStatus("error", playbackErrorMessage(error));
      });
  }, [updateStatus]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (isInteractiveShortcutTarget(event.target)) {
        if (event.key === "Escape" && typeof target?.blur === "function") {
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
          } else if (settingsOpen) {
            event.preventDefault();
            setSettingsOpen(false);
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
      settingsOpen,
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
    "offline",
  ].includes(mediaState)
    ? mediaMessage
    : statusMessage || mediaMessage;

  if (authorizationStopped) {
    return (
      <section
        className="momentum-video-viewer"
        aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
      >
        <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
        <div className="lesson-media-notice" role="status">
          <div className="lesson-media-notice__copy">
            <h3>Reopen this lesson to continue</h3>
            <p>
              Playback authorization changed or expired. Playback has stopped;
              no further watch progress is submitted.
            </p>
          </div>
          <Link className="button button--outline" href={moduleHref}>
            Return to module
          </Link>
        </div>
      </section>
    );
  }

  if (
    transport.enabled &&
    approvedMedia &&
    !activeMedia &&
    mode !== "unavailable"
  ) {
    return (
      <section
        className="momentum-video-viewer"
        aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
      >
        <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
        <div className="lesson-media-notice" role="status">
          <div className="lesson-media-notice__copy">
            <h3>
              {transport.pending
                ? "Preparing video preview"
                : "Video preview unavailable"}
            </h3>
            <p>
              {transport.pending
                ? "Connecting this lesson to your local session…"
                : "This local preview can’t open the video. You can try the lesson on staging."}
            </p>
          </div>
          <a
            className="button button--outline"
            href={`https://staging.authorityclosers.com/activity/${encodeURIComponent(activity.id)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open lesson on staging
          </a>
        </div>
      </section>
    );
  }

  if (!authorized || !activeMedia) {
    if (activity.state.toLowerCase() === "completed") {
      return (
        <section
          className="momentum-video-viewer"
          aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
        >
          <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
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
          aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
        >
          <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
          <BlockedMediaStage
            activity={activity}
            moduleHref={moduleHref}
            reason={mediaResolution.reason}
          />
        </section>
      );
    }

    return (
      <section
        className="momentum-video-viewer"
        aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
      >
        <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
        <LockedMediaStage
          activity={activity}
          moduleHref={moduleHref}
          reason={mediaResolution.reason}
        />
      </section>
    );
  }

  const statusLabel =
    mediaState === "offline"
      ? "Offline"
      : status === "starting"
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
      aria-labelledby={labelledBy ?? `video-title-${activity.id}`}
    >
      <VideoViewerHeading activity={activity} labelledBy={labelledBy} />
      {!tracked ? (
        <p role="note">
          Playback only — progress is not recorded for this lesson.
        </p>
      ) : null}

      <div
        ref={playerRef}
        className="momentum-video-player"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        role="region"
        aria-label={`Video player for ${activity.title}`}
        data-fullscreen-target="player"
        data-playback-mode={mode}
      >
        <div
          className="momentum-video-player__stage"
          data-media-state={mediaState}
          data-connection-state={
            isOffline || mediaState === "offline" ? "offline" : "online"
          }
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
            onPlaying={handlePlay}
            onEnded={() => {
              setHasEnded(true);
              setIsPlaying(false);
              setMediaState(tracked ? "processing" : "paused");
              setMediaMessage(
                tracked
                  ? "Processing watch evidence with the server…"
                  : "Playback ended. Progress has not been recorded.",
              );
              if (tracked) void completePlayback();
            }}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onCanPlay={handleCanPlay}
            onWaiting={handleWaiting}
            onStalled={handleWaiting}
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
          {playbackRates.length > 0 ? (
            <label className="momentum-video-controls__rate">
              <Gauge size={16} aria-hidden="true" />
              <span className="sr-only">Playback speed</span>
              <select
                value={effectivePlaybackRate}
                onChange={(event) => changeRate(Number(event.target.value))}
                aria-label="Playback speed"
              >
                {playbackRates.map((rate) => (
                  <option key={rate} value={rate}>
                    {rate}×
                  </option>
                ))}
              </select>
            </label>
          ) : null}
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
              <span className="sr-only">
                {captionsEnabled ? "Captions on" : "Captions off"}
              </span>
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
              aria-controls="momentum-video-transcript"
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
              ref={pictureInPictureTriggerRef}
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
              ref={fullscreenTriggerRef}
              className="momentum-video-controls__icon"
              type="button"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
              aria-keyshortcuts="f"
            >
              <Maximize2 size={18} aria-hidden="true" />
            </button>
          ) : null}
          {hasPlaybackSettings ? (
            <button
              ref={settingsTriggerRef}
              className={`momentum-video-controls__settings${settingsOpen ? " is-active" : ""}`}
              type="button"
              onClick={() => setSettingsOpen((prev) => !prev)}
              aria-expanded={settingsOpen}
              aria-controls="momentum-video-settings"
              aria-label={
                settingsOpen
                  ? "Close playback settings"
                  : "Open playback settings"
              }
            >
              <Settings2 size={17} aria-hidden="true" />
              <span>Settings</span>
            </button>
          ) : null}
          <button
            ref={shortcutsTriggerRef}
            className={`momentum-video-controls__icon${shortcutsOpen ? " is-active" : ""}`}
            type="button"
            onClick={() => setShortcutsOpen((prev) => !prev)}
            aria-label="Show keyboard shortcuts"
            aria-expanded={shortcutsOpen}
            aria-controls="momentum-video-shortcuts"
          >
            <HelpCircle size={17} aria-hidden="true" />
          </button>
        </div>

        {settingsOpen && hasPlaybackSettings ? (
          <PlaybackSettingsPanel
            playbackRates={playbackRates}
            playbackRate={effectivePlaybackRate}
            onChangeRate={changeRate}
            qualities={qualityOptions}
            qualityId={effectiveQualityId}
            onChangeQuality={changeQuality}
            onClose={() => setSettingsOpen(false)}
          />
        ) : null}
      </div>

      <div className="momentum-video-viewer__status-row">
        <div>
          <span
            className={`momentum-video-viewer__status momentum-video-viewer__status--${mediaState === "offline" ? "offline" : status}`}
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
                !tracked ||
                (mediaState === "error" &&
                  !hasEnded &&
                  !playbackSessionNeedsRetry)
                  ? void retryMedia()
                  : void retryPlaybackSave()
              }
            >
              {!tracked ||
              (mediaState === "error" &&
                !hasEnded &&
                !playbackSessionNeedsRetry)
                ? "Retry media"
                : "Retry server save"}
            </button>
          ) : null}
          <Link href={moduleHref}>Return to module</Link>
        </div>
      </div>

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
    </section>
  );
}
