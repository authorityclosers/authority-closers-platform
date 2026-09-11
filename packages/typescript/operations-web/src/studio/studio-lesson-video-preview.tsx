"use client";

import { useEffect, useState } from "react";
import {
  loadStudioActivityVideo,
  type StudioActivityVideo,
} from "./studio-video-api";
import { StudioVideoPreview } from "./studio-video-preview";

type Props = {
  programId: string;
  activityId: string;
  recoveryContext: string;
  versionStatus: string;
  canWrite: boolean;
};

export function StudioLessonVideoPreview(props: Props) {
  return (
    <LessonPreview
      key={`${props.recoveryContext}:${props.programId}:${props.activityId}:${props.versionStatus}:${props.canWrite}`}
      {...props}
    />
  );
}
function LessonPreview({
  programId,
  activityId,
  recoveryContext,
  versionStatus,
  canWrite,
}: Props) {
  const [current, setCurrent] = useState<StudioActivityVideo | null>(null);
  const [error, setError] = useState(false);
  const eligible =
    canWrite &&
    !!recoveryContext &&
    ["published", "superseded"].includes(versionStatus);
  useEffect(() => {
    if (!eligible) return;
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => {
      if (active) setError(true);
      controller.abort();
    }, 12_000);
    void loadStudioActivityVideo({
      programId,
      activityId,
      signal: controller.signal,
    })
      .then((result) => {
        if (!active || controller.signal.aborted) return;
        if (!["published", "superseded"].includes(result.version_status)) {
          setError(true);
          return;
        }
        setCurrent(result);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => clearTimeout(timer));
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [programId, activityId, eligible]);
  if (!eligible)
    return (
      <p>
        Preview a ready upload in the course video library. Connecting it to
        this lesson follows course review.
      </p>
    );
  if (error)
    return (
      <p role="alert">
        The lesson video couldn’t be checked. Return to content and refresh its
        video details.
      </p>
    );
  if (!current) return <p role="status">Checking the lesson video…</p>;
  if (!current.binding)
    return (
      <p>
        No video connected yet. Return to content to choose and preview a ready
        upload.
      </p>
    );
  return (
    <StudioVideoPreview
      programId={programId}
      assetId={current.binding.asset_id}
      versionId={current.binding.version_id}
      label={current.binding.label}
      recoveryContext={recoveryContext}
    />
  );
}
