"use client";

import { useRef } from "react";
import { Play, RotateCcw } from "lucide-react";

type Props = {
  isPlaying: boolean;
  hasEnded: boolean;
  blocked: boolean;
  onActivate: () => void;
};

/** Presentation only. The mounted player still owns media and authorization. */
export function VideoPlaybackSurface({
  isPlaying,
  hasEnded,
  blocked,
  onActivate,
}: Props) {
  const suppressClick = useRef(false);
  const action = hasEnded
    ? "Replay video"
    : isPlaying
      ? "Pause video"
      : "Start video";

  return (
    <button
      type="button"
      className="momentum-video-player__surface"
      aria-label={action}
      aria-disabled={blocked}
      title={action}
      onPointerDown={(event) => {
        // Dismissing a menu by touching the picture must not also start/pause
        // it after the menu's outside-pointer handler changes the props.
        suppressClick.current = blocked || event.isPrimary === false;
      }}
      onPointerCancel={() => {
        suppressClick.current = true;
      }}
      onClick={(event) => {
        if (blocked || (event.detail !== 0 && suppressClick.current)) return;
        // Preserve the actual user activation for every input type. Fullscreen
        // has its own control/F shortcut; playback never waits for a timer.
        onActivate();
      }}
    >
      {!isPlaying && !blocked ? (
        <span className="momentum-video-player__center-play" aria-hidden="true">
          {hasEnded ? (
            <RotateCcw size={28} />
          ) : (
            <Play size={28} fill="currentColor" />
          )}
        </span>
      ) : null}
    </button>
  );
}
