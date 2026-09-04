"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type ActivityResponse,
  type EvidenceResponse,
  type LearnerApi,
  type PlaybackEventInput,
  type PlaybackFinishResponse,
  type PlaybackStartResponse,
  type PlaybackEventResponse,
} from "../lib/learner-api";
import {
  VideoViewer,
  type AuthorizedVideoMedia,
} from "./learning-loop-runtime";

type FixtureName =
  | "official-bbb"
  | "tiny-16x9-320x180-4s"
  | "tiny-4x3-320x240-6s"
  | "tiny-235x-640x272-3s";

type HarnessScenario =
  | "normal"
  | "abort-heartbeat"
  | "session-expired"
  | "expired-grant"
  | "finish-network";

type TraceEntry = {
  id: number;
  type: "activity" | "start" | "heartbeat" | "finish" | "evidence" | "failure";
  detail: string;
  sequence?: number;
};

type SimulationState = {
  activityReads: number;
  startCalls: number;
  heartbeatCalls: number;
  finishCalls: number;
  evidenceCalls: number;
  heartbeatAborted: boolean;
  heartbeatExpired: boolean;
  finishFailed: boolean;
};

const HARNESS_ACTIVITY_ID = "00000000-0000-4000-8000-000000000001";
const HARNESS_MODULE_ID = "00000000-0000-4000-8000-000000000002";
const HARNESS_VERSION_ID = "00000000-0000-4000-8000-000000000003";

const FIXTURES: ReadonlyArray<{
  value: FixtureName;
  label: string;
  width: number;
  height: number;
  duration: number;
}> = [
  {
    value: "official-bbb",
    label: "Official Big Buck Bunny · 320×180 · 9:56",
    width: 320,
    height: 180,
    duration: 596,
  },
  {
    value: "tiny-16x9-320x180-4s",
    label: "Generated · 16:9 · 320×180 · 4s",
    width: 320,
    height: 180,
    duration: 4,
  },
  {
    value: "tiny-4x3-320x240-6s",
    label: "Generated · 4:3 · 320×240 · 6s",
    width: 320,
    height: 240,
    duration: 6,
  },
  {
    value: "tiny-235x-640x272-3s",
    label: "Generated · 2.35:1 · 640×272 · 3s",
    width: 640,
    height: 272,
    duration: 3,
  },
];

const SCENARIOS: ReadonlyArray<{ value: HarnessScenario; label: string }> = [
  { value: "normal", label: "Normal server responses" },
  { value: "abort-heartbeat", label: "Abort first heartbeat, then retry" },
  { value: "session-expired", label: "Expire session on first heartbeat" },
  { value: "expired-grant", label: "Return expired grant, then reacquire" },
  { value: "finish-network", label: "Fail first finish, then retry" },
];

const HARNESS_ACTIVITY: ActivityResponse = {
  id: HARNESS_ACTIVITY_ID,
  module_id: HARNESS_MODULE_ID,
  program_version_id: HARNESS_VERSION_ID,
  program_id: "00000000-0000-4000-8000-000000000004",
  enrollment_id: "00000000-0000-4000-8000-000000000005",
  position: 1,
  kind: "VIDEO",
  title: "Media player stress fixture",
  prompt: "Test-only player fixture; no canonical learning state is written.",
  state: "in_progress",
  revision: 1,
  required: true,
  explanation: {
    activity_id: HARNESS_ACTIVITY_ID,
    state: "in_progress",
    required: true,
    reason: "development_harness",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
  allowed_actions: ["complete_video"],
  draft_revision: 0,
  draft_payload: null,
};

function normalizeFixture(value: string | undefined): FixtureName {
  return FIXTURES.some((entry) => entry.value === value)
    ? (value as FixtureName)
    : "tiny-16x9-320x180-4s";
}

function normalizeScenario(value: string | undefined): HarnessScenario {
  return SCENARIOS.some((entry) => entry.value === value)
    ? (value as HarnessScenario)
    : "normal";
}

type MediaPlayerStressHarnessProps = {
  initialFixture?: string;
  initialScenario?: string;
};

export function MediaPlayerStressHarness({
  initialFixture,
  initialScenario,
}: MediaPlayerStressHarnessProps) {
  const [fixture, setFixture] = useState<FixtureName>(() =>
    normalizeFixture(initialFixture),
  );
  const [scenario, setScenario] = useState<HarnessScenario>(() =>
    normalizeScenario(initialScenario),
  );
  const [playerKey, setPlayerKey] = useState(0);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const traceIdRef = useRef(0);
  const scenarioRef = useRef(scenario);
  const simulationRef = useRef<SimulationState>({
    activityReads: 0,
    startCalls: 0,
    heartbeatCalls: 0,
    finishCalls: 0,
    evidenceCalls: 0,
    heartbeatAborted: false,
    heartbeatExpired: false,
    finishFailed: false,
  });

  useEffect(() => {
    scenarioRef.current = scenario;
  }, [scenario]);

  const appendTrace = useCallback((entry: Omit<TraceEntry, "id">) => {
    const next = { ...entry, id: ++traceIdRef.current };
    setTrace((current) => [...current.slice(-49), next]);
  }, []);

  const api = useMemo(() => {
    const simulation = simulationRef.current;
    const trace = appendTrace;
    const fakeActivity = async (): Promise<ActivityResponse> => {
      simulation.activityReads += 1;
      trace({
        type: "activity",
        detail: `activity read #${simulation.activityReads}`,
      });
      return HARNESS_ACTIVITY;
    };

    const fakeApi = {
      activity: fakeActivity,
      startPlayback: async (): Promise<PlaybackStartResponse> => {
        simulation.startCalls += 1;
        const expired =
          scenarioRef.current === "expired-grant" &&
          simulation.startCalls === 1;
        const sessionId = `harness-session-${simulation.startCalls}`;
        trace({
          type: "start",
          detail: `${sessionId} ${expired ? "expired" : "valid"}`,
        });
        return {
          session_id: sessionId,
          activity_id: HARNESS_ACTIVITY_ID,
          session_token: `harness-token-${simulation.startCalls}`,
          revision: 0,
          expires_at: new Date(
            Date.now() + (expired ? -1000 : 120_000),
          ).toISOString(),
          duration_seconds:
            FIXTURES.find((entry) => entry.value === fixture)?.duration ?? 4,
        };
      },
      heartbeatPlayback: async (
        _activityId: string,
        input: PlaybackEventInput,
      ): Promise<PlaybackEventResponse> => {
        simulation.heartbeatCalls += 1;
        trace({
          type: "heartbeat",
          sequence: input.sequence,
          detail: `${input.kind} ${input.start_seconds.toFixed(2)}→${input.end_seconds.toFixed(2)}`,
        });
        if (
          scenarioRef.current === "abort-heartbeat" &&
          !simulation.heartbeatAborted
        ) {
          simulation.heartbeatAborted = true;
          trace({ type: "failure", detail: "heartbeat network abort" });
          throw new TypeError("harness heartbeat aborted");
        }
        if (
          scenarioRef.current === "session-expired" &&
          !simulation.heartbeatExpired
        ) {
          simulation.heartbeatExpired = true;
          trace({ type: "failure", detail: "playback session expired" });
          throw new ApiError(401, "Playback session expired", {
            code: "playback_session_expired",
          });
        }
        return {
          session_id: input.session_id,
          interval_id: `harness-interval-${input.sequence}`,
          sequence: input.sequence,
          revision: input.sequence,
          observed_at: new Date().toISOString(),
        };
      },
      finishPlayback: async (
        _activityId: string,
        sessionId: string,
      ): Promise<PlaybackFinishResponse> => {
        simulation.finishCalls += 1;
        trace({
          type: "finish",
          detail: `${sessionId} attempt #${simulation.finishCalls}`,
        });
        if (
          scenarioRef.current === "finish-network" &&
          !simulation.finishFailed
        ) {
          simulation.finishFailed = true;
          trace({ type: "failure", detail: "finish network failure" });
          throw new TypeError("harness finish failed");
        }
        return {
          session_id: sessionId,
          activity_id: HARNESS_ACTIVITY_ID,
          revision: simulation.finishCalls,
          status: "closed",
          closed_at: new Date().toISOString(),
        };
      },
      submitEvidence: async (
        _activityId: string,
        _evidenceType: string,
        _payload: Record<string, unknown>,
        _revision: number,
        sessionId?: string,
      ): Promise<EvidenceResponse> => {
        simulation.evidenceCalls += 1;
        trace({
          type: "evidence",
          detail: `video_watch for ${sessionId ?? "no session"}`,
        });
        return {
          evidence_id: `harness-evidence-${simulation.evidenceCalls}`,
          submission_id: `harness-submission-${simulation.evidenceCalls}`,
          activity_id: HARNESS_ACTIVITY_ID,
          activity_revision: HARNESS_ACTIVITY.revision,
          evidence_type: "video_watch",
          submission_status: "accepted-in-harness-only",
        };
      },
    } as unknown as LearnerApi;

    return fakeApi;
  }, [appendTrace, fixture]);

  const selectedFixture =
    FIXTURES.find((entry) => entry.value === fixture) ?? FIXTURES[1];
  const media = useMemo<AuthorizedVideoMedia>(
    () => ({
      protocol: "progressive",
      contentType: "video/mp4",
      src: `/dev-harness/media-player/fixtures/${fixture}.mp4`,
      poster: "/icon.svg",
      captions: [
        {
          src: "/dev-harness/media-player/captions.vtt",
          srclang: "en",
          label: "English",
          default: true,
        },
      ],
      transcript: [
        { start: 0.25, end: 1.2, text: "Opening frame" },
        { start: 1.2, end: 2.2, text: "Playback control checkpoint" },
        { start: 2.2, end: 3.4, text: "Completion and retry checkpoint" },
      ],
    }),
    [fixture],
  );

  function resetHarness() {
    simulationRef.current = {
      activityReads: 0,
      startCalls: 0,
      heartbeatCalls: 0,
      finishCalls: 0,
      evidenceCalls: 0,
      heartbeatAborted: false,
      heartbeatExpired: false,
      finishFailed: false,
    };
    traceIdRef.current = 0;
    setTrace([]);
    setPlayerKey((current) => current + 1);
  }

  function changeScenario(next: HarnessScenario) {
    scenarioRef.current = next;
    setScenario(next);
    resetHarness();
  }

  function changeFixture(next: FixtureName) {
    setFixture(next);
    resetHarness();
  }

  return (
    <div className="site-frame--learner" data-testid="media-player-harness">
      <main
        className="learner-main"
        style={{ minHeight: "100vh", padding: "24px 16px" }}
      >
        <div
          style={{
            width: "min(100%, 980px)",
            maxWidth: "100%",
            minWidth: 0,
            margin: "0 auto",
          }}
        >
          <header
            style={{
              display: "grid",
              gap: "10px",
              gridTemplateColumns: "minmax(0, 1fr)",
              minWidth: 0,
              marginBottom: "20px",
            }}
          >
            <p className="momentum-video-viewer__eyebrow">
              Development-only browser harness
            </p>
            <h1 style={{ margin: 0, overflowWrap: "anywhere" }}>
              LearningLoopRuntime media stress test
            </h1>
            <p style={{ margin: 0, maxWidth: "760px" }}>
              Uses the production VideoViewer with a local fake API. Trace rows
              are synthetic observations only; no learner progress or evidence
              is written to a canonical service.
            </p>
          </header>

          <section
            aria-label="Media stress harness controls"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "12px",
              marginBottom: "24px",
              padding: "14px",
              border: "1px solid var(--theme-border)",
              borderRadius: "10px",
              background: "var(--theme-surface)",
            }}
          >
            <label style={{ display: "grid", gap: "5px" }}>
              <span>Fixture</span>
              <select
                aria-label="Fixture"
                value={fixture}
                onChange={(event) =>
                  changeFixture(event.target.value as FixtureName)
                }
              >
                {FIXTURES.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: "5px" }}>
              <span>Scenario</span>
              <select
                aria-label="Scenario"
                value={scenario}
                onChange={(event) =>
                  changeScenario(event.target.value as HarnessScenario)
                }
              >
                {SCENARIOS.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button
                className="button button--outline"
                type="button"
                data-testid="reset-harness"
                onClick={resetHarness}
              >
                Reset player and trace
              </button>
            </div>
          </section>

          <section
            aria-label="Selected fixture facts"
            data-testid="fixture-facts"
            style={{ marginBottom: "16px" }}
          >
            <strong>{selectedFixture.label}</strong>
            <span style={{ marginLeft: "10px", overflowWrap: "anywhere" }}>
              Expected media metadata: {selectedFixture.width}×
              {selectedFixture.height}, {selectedFixture.duration}s
            </span>
          </section>

          <VideoViewer
            key={`${fixture}-${playerKey}`}
            activity={HARNESS_ACTIVITY}
            api={api}
            moduleHref="/dev-harness/media-player"
            media={media}
          />

          <section
            aria-label="Synthetic API trace"
            style={{ marginTop: "24px" }}
          >
            <h2 style={{ fontSize: "1rem" }}>Synthetic API trace</h2>
            <ol
              data-testid="harness-trace"
              style={{
                display: "grid",
                gap: "4px",
                margin: 0,
                paddingLeft: "24px",
                fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
                fontSize: "0.75rem",
              }}
            >
              {trace.length ? (
                trace.map((entry) => (
                  <li
                    key={entry.id}
                    data-testid="harness-trace-entry"
                    data-event-type={entry.type}
                    data-sequence={entry.sequence ?? ""}
                  >
                    [{entry.type}] {entry.detail}
                    {entry.sequence ? ` · sequence ${entry.sequence}` : ""}
                  </li>
                ))
              ) : (
                <li data-testid="harness-trace-empty">
                  No synthetic calls yet.
                </li>
              )}
            </ol>
          </section>
        </div>
      </main>
    </div>
  );
}
