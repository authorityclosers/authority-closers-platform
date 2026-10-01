"use client";

import { useState } from "react";
import fixture from "../../../tests/fixtures/call-map-v1.json";
import { parseCallMap } from "../../call-map-contract";
import { OverviewCallVisuals } from "../../overview-call-visuals";
import type { Transcript } from "../../report-contract";
import { formatTranscriptTime } from "../../report-transcript";
import styles from "./synthetic-report-preview.module.css";

const transcript: Transcript = {
  source_sha256: "0".repeat(64),
  revision: "fictional-call-map-v1",
  timebase_id: "fictional-call-map-1ms",
  duration_ms: fixture.duration_ms,
  segments: fixture.segments,
};
const callMap = parseCallMap(
  fixture.call_map,
  fixture.segments,
  fixture.duration_ms,
);

export function CallMapPreview() {
  const [selectedMs, setSelectedMs] = useState<number | null>(null);
  const segment = transcript.segments.find(
    (item) =>
      selectedMs !== null &&
      item.start_ms <= selectedMs &&
      selectedMs < item.end_ms,
  );

  return (
    <div data-call-map-fixture>
      <p>
        Fictional call-map fixture · Qivra Works / LumaBoard. These cards and
        sources use only this fixture's dialogue and timestamps. No audio
        exists.
      </p>
      <OverviewCallVisuals
        transcript={transcript}
        callMap={callMap}
        onSeek={setSelectedMs}
      />
      <aside
        className={styles.source}
        aria-label="Call-map fixture source"
        aria-live="polite"
      >
        <strong>Call-map fixture source preview</strong>
        {segment && selectedMs !== null ? (
          <p>
            Selected {formatTranscriptTime(selectedMs)} · {segment.id} ·{" "}
            {segment.speaker_id} · {formatTranscriptTime(segment.start_ms)}–
            {formatTranscriptTime(segment.end_ms)} · {segment.text}
          </p>
        ) : (
          <p>
            {selectedMs === null
              ? "Select a call-map source to inspect its fictional segment."
              : `No transcript segment at ${formatTranscriptTime(selectedMs)}.`}
          </p>
        )}
        <small>No recording or provider call exists for this fixture.</small>
      </aside>
    </div>
  );
}
