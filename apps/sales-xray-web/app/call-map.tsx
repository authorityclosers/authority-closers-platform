"use client";

import {
  MessagesSquare,
  Play,
  MessageCircleQuestion,
  Sparkles,
  Target,
  Timer,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import {
  interestSeries,
  questionsAsked,
  quietPoint,
  talkAfter,
} from "./call-data";
import { formatClock } from "./lightbox/time";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import { getShellState } from "./shell/shell-store";
import { useSourceWaveform, waveformBins } from "./source-waveform";
import { SpeakerAvatar } from "./speaker-avatar";
import { SpeakerEditor } from "./speaker-editor";
import { suggestProspectIcon } from "./speaker-icons";
import {
  detectSpokenNames,
  firstName,
  isAccountName,
  suggestYou,
  useSpeakerProfiles,
  voiceStyle,
  type SpeakerProfile,
} from "./speaker-profiles";
import styles from "./call-map.module.css";

const ROLE_LABELS = {
  you: "You",
  salesperson: "Salesperson",
  prospect: "Prospect",
  other: "Other",
};

const BIN_COUNT = 180;
// A switch within this gap still counts as the same person holding the floor.
const SAME_TURN_GAP_MS = 1500;
// Turns closer than this draw as one stroke in a speaker lane.
const LANE_JOIN_MS = 400;
const MAX_LANES = 4;
const STEP_MS = 5000;
const PAGE_MS = 30000;

const KINDS = [
  { key: "strengths", label: "Done well", tone: "strength" },
  { key: "objection_analysis", label: "Pushback", tone: "objection" },
  { key: "missed_opportunities", label: "Missed chance", tone: "missed" },
  { key: "closing_analysis", label: "Closing", tone: "closing" },
  { key: "improvements", label: "To improve", tone: "improve" },
] as const;

type Tone = (typeof KINDS)[number]["tone"];

/** What the band under the waveform shows: one view at a time. */
type Lens = "who" | "stages" | "interest";
const LENSES: Array<{ key: Lens; label: string }> = [
  { key: "who", label: "Who talked" },
  { key: "stages", label: "Call stages" },
  { key: "interest", label: "Prospect's interest" },
];
const LENS_KEY = "ac.xray.map-lens";

function readLens(): Lens {
  try {
    const saved =
      typeof window === "undefined" ? null : localStorage.getItem(LENS_KEY);
    return saved === "stages" || saved === "interest" ? saved : "who";
  } catch {
    return "who";
  }
}
type Marker = {
  key: string;
  tone: Tone;
  kind: string;
  title: string;
  evidence: ReportEvidence;
  x: number;
};
type Lane = {
  lane: number;
  /** The provider speaker label; null for the shared "Others" lane. */
  speakerId: string | null;
  label: string;
  share: number;
  spans: Array<[number, number]>;
};

function callFacts(transcript: Transcript, total: number) {
  const voices: string[] = [];
  const talk = new Map<string, number>();
  let longest = { ms: 0, voice: -1 };
  let run: { voice: string; start: number; end: number } | null = null;
  let switches = 0;
  let previous: string | null = null;
  for (const segment of transcript.segments) {
    const voice = segment.speaker_id ?? "unknown";
    if (!voices.includes(voice)) voices.push(voice);
    talk.set(
      voice,
      (talk.get(voice) ?? 0) + Math.max(0, segment.end_ms - segment.start_ms),
    );
    if (previous !== null && previous !== voice) switches += 1;
    previous = voice;
    if (
      run &&
      run.voice === voice &&
      segment.start_ms - run.end <= SAME_TURN_GAP_MS
    ) {
      run.end = Math.max(run.end, segment.end_ms);
    } else {
      run = { voice, start: segment.start_ms, end: segment.end_ms };
    }
    if (run.end - run.start > longest.ms)
      longest = { ms: run.end - run.start, voice: voices.indexOf(voice) };
  }
  const talkTotal = [...talk.values()].reduce((sum, value) => sum + value, 0);
  return {
    voices,
    shares: voices.map((voice) =>
      talkTotal > 0 ? (talk.get(voice) ?? 0) / talkTotal : 0,
    ),
    longest,
    switchesPerMinute: switches / Math.max(1 / 60, total / 60000),
  };
}

/**
 * One lane per voice, numbered in order of first speaking. Beyond four, the
 * later voices share an "Others" lane so the map stays calm.
 */
function speakerLanes(
  segments: TranscriptSegment[],
  voices: string[],
  shares: number[],
) {
  const grouped = voices.length > MAX_LANES;
  const laneOf = voices.map((_, index) =>
    grouped && index >= MAX_LANES - 1 ? MAX_LANES - 1 : index,
  );
  const lanes: Lane[] = Array.from(
    { length: Math.min(voices.length, MAX_LANES) },
    (_, lane) => ({
      lane,
      speakerId: grouped && lane === MAX_LANES - 1 ? null : voices[lane],
      label:
        grouped && lane === MAX_LANES - 1 ? "Others" : `Speaker ${lane + 1}`,
      share: shares.reduce(
        (sum, share, index) => (laneOf[index] === lane ? sum + share : sum),
        0,
      ),
      spans: [],
    }),
  );
  for (const segment of segments) {
    const lane =
      lanes[laneOf[voices.indexOf(segment.speaker_id ?? "unknown")] ?? -1];
    if (!lane || segment.end_ms <= segment.start_ms) continue;
    const last = lane.spans[lane.spans.length - 1];
    if (last && segment.start_ms - last[1] <= LANE_JOIN_MS)
      last[1] = Math.max(last[1], segment.end_ms);
    else lane.spans.push([segment.start_ms, segment.end_ms]);
  }
  return { laneOf, lanes };
}

/** The lane that talks most inside each waveform bin, or -1 for silence. */
function binOwners(lanes: Lane[], total: number) {
  const binMs = total / BIN_COUNT;
  const heard = Array.from({ length: BIN_COUNT }, () =>
    new Array<number>(lanes.length).fill(0),
  );
  for (const lane of lanes) {
    for (const [start, end] of lane.spans) {
      const first = Math.max(0, Math.floor(start / binMs));
      const last = Math.min(BIN_COUNT - 1, Math.floor((end - 1) / binMs));
      for (let bin = first; bin <= last; bin += 1) {
        const overlap =
          Math.min(end, (bin + 1) * binMs) - Math.max(start, bin * binMs);
        if (overlap > 0) heard[bin][lane.lane] += overlap;
      }
    }
  }
  return heard.map((row) => {
    let owner = -1;
    let most = 0;
    row.forEach((ms, lane) => {
      if (ms > most) {
        most = ms;
        owner = lane;
      }
    });
    return owner;
  });
}

function reportMarkers(report: SalesReport, total: number): Marker[] {
  return KINDS.flatMap((kind) =>
    ((report[kind.key] as Finding[] | undefined) ?? []).flatMap(
      (finding, index) => {
        const evidence = finding.evidence[0];
        if (!evidence) return [];
        return [
          {
            key: `${kind.key}-${index}`,
            tone: kind.tone,
            kind: kind.label,
            title: finding.title,
            evidence,
            x: Math.min(100, Math.max(0, (evidence.start_ms / total) * 100)),
          },
        ];
      },
    ),
  );
}

/** Where a key press on a call slider moves playback, or null. */
function keyTarget(key: string, currentMs: number, total: number) {
  const at = (ms: number) => Math.min(total - 1, Math.max(0, ms));
  switch (key) {
    case "ArrowRight":
    case "ArrowUp":
      return at(currentMs + STEP_MS);
    case "ArrowLeft":
    case "ArrowDown":
      return at(currentMs - STEP_MS);
    case "PageUp":
      return at(currentMs + PAGE_MS);
    case "PageDown":
      return at(currentMs - PAGE_MS);
    case "Home":
      return 0;
    case "End":
      return at(total - STEP_MS);
    case "Enter":
    case " ":
      return at(currentMs);
    default:
      return null;
  }
}

/** The transcript segment being spoken at `ms`, if any. */
function segmentAt(
  segments: TranscriptSegment[],
  ms: number,
): TranscriptSegment | null {
  for (const segment of segments)
    if (segment.start_ms <= ms && ms < segment.end_ms) return segment;
  return null;
}

/**
 * The whole call at a glance, and a way to move through it: hover the
 * waveform to see who is speaking and what they say at that time; click or
 * drag to play from there. One thin lane per speaker shows when each voice
 * talks, and report findings sit on the waveform as dots. Provider speaker
 * labels are unverified: voices stay numbered until the person names them,
 * and "you" is only ever suggested from what was said, then confirmed.
 */
export function CallMap({
  callId,
  transcript,
  report,
  durationMs,
  onSelectEvidence,
  onSeek,
}: {
  /** The saved call, whose speaker names this map reads and edits. */
  callId: string | null;
  transcript: Transcript;
  report: SalesReport;
  durationMs: number;
  onSelectEvidence: (evidence: ReportEvidence) => void;
  /** Plays the recording from this time. */
  onSeek: (ms: number) => void;
}) {
  const { envelope, currentTimeMs, playing } = useSourceWaveform();
  const [hover, setHover] = useState<number | null>(null);
  const [scrubbing, setScrubbing] = useState(false);
  const [focusTone, setFocusTone] = useState<Tone | null>(null);
  const [hoverVoice, setHoverVoice] = useState<number | null>(null);
  // The speaker being named, and the chip its editor is pinned to.
  const [editing, setEditing] = useState<{
    voice: number;
    anchor: HTMLElement;
  } | null>(null);
  const [declined, setDeclined] = useState<string[]>([]);
  const [lens, setLens] = useState<Lens>(readLens);
  const { profiles, save, canSave } = useSpeakerProfiles(callId);
  const accountName = getShellState().profileName;
  const total = Math.max(1, durationMs);
  const { facts, laneOf, lanes, owners, samples } = useMemo(() => {
    const facts = callFacts(transcript, total);
    const { laneOf, lanes } = speakerLanes(
      transcript.segments,
      facts.voices,
      facts.shares,
    );
    // Something each voice said early on, to help tell them apart.
    const samples = new Map<string, string>();
    for (const segment of transcript.segments) {
      const voice = segment.speaker_id ?? "unknown";
      const words = segment.text.trim().split(/\s+/).length;
      if (!samples.has(voice) && words >= 4) samples.set(voice, segment.text);
    }
    return { facts, laneOf, lanes, owners: binOwners(lanes, total), samples };
  }, [transcript, total]);
  const suggestion = useMemo(
    () => suggestYou(transcript, report, accountName),
    [transcript, report, accountName],
  );
  const spoken = useMemo(() => detectSpokenNames(transcript), [transcript]);
  const prospectIcon = useMemo(
    () => suggestProspectIcon(`${report.summary} ${report.verdict}`),
    [report],
  );
  const closeEditor = useCallback(() => setEditing(null), []);
  // Scrolling clears the hover peek, so the waveform folds away clean.
  useEffect(() => {
    if (hover === null) return;
    const clear = () => setHover(null);
    document.addEventListener("scroll", clear, {
      capture: true,
      passive: true,
    });
    return () =>
      document.removeEventListener("scroll", clear, { capture: true });
  }, [hover]);
  const levels = envelope
    ? waveformBins(envelope, 0, envelope.duration_ms, BIN_COUNT)
    : null;
  const progress = Math.min(1, Math.max(0, currentTimeMs / total));
  const editingVoice = editing?.voice ?? null;
  const focusVoice = hoverVoice ?? editingVoice;

  const profileOf = (voice: number): SpeakerProfile | undefined => {
    const id = facts.voices[voice];
    return id === undefined ? undefined : profiles[id];
  };
  const nameOf = (voice: number) => {
    const profile = profileOf(voice);
    if (profile?.name) return profile.name;
    if (profile?.role === "you") return firstName(accountName) ?? "You";
    return `Speaker ${voice + 1}`;
  };
  const laneName = (lane: Lane) =>
    lane.speakerId === null ? lane.label : nameOf(lane.lane);
  const named = lanes.some(
    (lane) => lane.speakerId !== null && profiles[lane.speakerId],
  );

  function chooseLens(next: Lens) {
    setLens(next);
    try {
      localStorage.setItem(LENS_KEY, next);
    } catch {
      // A remembered view is a convenience only.
    }
  }

  // The prospect: named as such, else the voice that is not the seller on a
  // two-person call, else the quieter of the first two voices.
  const prospectVoice = (() => {
    const named = facts.voices.find((id) => profiles[id]?.role === "prospect");
    if (named) return named;
    const seller = facts.voices.find(
      (id) =>
        profiles[id]?.role === "you" || profiles[id]?.role === "salesperson",
    );
    if (seller && facts.voices.length === 2)
      return facts.voices.find((id) => id !== seller) ?? null;
    if (facts.voices.length < 2) return null;
    return (facts.shares[1] ?? 0) <= (facts.shares[0] ?? 0)
      ? facts.voices[1]
      : facts.voices[0];
  })();
  const interest = useMemo(
    () => (prospectVoice ? interestSeries(transcript, prospectVoice) : []),
    [transcript, prospectVoice],
  );
  const quiet = useMemo(() => quietPoint(interest), [interest]);
  const quietMs = quiet === null ? null : quiet * 60_000;
  const quietTalkMs =
    quietMs === null || !prospectVoice
      ? 0
      : talkAfter(transcript, prospectVoice, quietMs);
  const interestPath = (() => {
    if (!interest.length) return null;
    const points = interest.map((share, bin) => [
      Math.min(total, (bin + 0.5) * 60_000),
      1 - (share ?? 0) * 0.92,
    ]);
    const line = points
      .map(
        ([x, y], index) =>
          `${index ? "L" : "M"}${x.toFixed(0)} ${y.toFixed(3)}`,
      )
      .join(" ");
    return {
      line,
      area: `${line} L${points[points.length - 1][0].toFixed(0)} 1 L${points[0][0].toFixed(0)} 1 Z`,
    };
  })();
  const questionsPerLane = useMemo(() => {
    const counts = new Array<number>(Math.max(1, lanes.length)).fill(0);
    for (const row of questionsAsked(transcript)) {
      const lane = laneOf[facts.voices.indexOf(row.voice)];
      if (lane !== undefined) counts[lane] += 1;
    }
    return counts;
  }, [transcript, laneOf, lanes.length, facts.voices]);

  // One tap confirms who sold on this call, suggested from what was said:
  // "you" only when the seller says (or is greeted with) your own name,
  // otherwise the salesperson, named as they introduced themselves.
  const hasSeller = Object.values(profiles).some(
    (profile) => profile.role === "you" || profile.role === "salesperson",
  );
  const seller =
    suggestion?.speakerId ??
    (spoken.introducers.length === 1 &&
    isAccountName(spoken.names[spoken.introducers[0]], accountName)
      ? spoken.introducers[0]
      : null);
  // "No" on a two-person call asks about the other voice instead.
  const askId: string | null =
    canSave && !hasSeller && seller && lanes.length > 1
      ? !declined.includes(seller)
        ? seller
        : facts.voices.length === 2
          ? (facts.voices.find(
              (id) => id !== seller && !declined.includes(id),
            ) ?? null)
          : null
      : null;
  const askVoice = askId === null ? -1 : facts.voices.indexOf(askId);
  const askIsYou =
    askId !== null &&
    ((suggestion?.reason === "introduction" &&
      suggestion.speakerId === askId) ||
      isAccountName(spoken.names[askId], accountName));

  function confirmSeller(speakerId: string, asYou: boolean) {
    const changes: Record<string, SpeakerProfile> = {
      [speakerId]: {
        name:
          profiles[speakerId]?.name ||
          (asYou ? accountName : spoken.names[speakerId]) ||
          "",
        role: asYou ? "you" : "salesperson",
        icon: null,
      },
    };
    // On a two-person call the other voice is the prospect.
    if (facts.voices.length === 2) {
      const other = facts.voices.find((id) => id !== speakerId);
      const current = other ? profiles[other] : undefined;
      if (other && !current?.role)
        changes[other] = {
          name: current?.name || spoken.names[other] || "",
          role: "prospect",
          icon: current?.icon ?? prospectIcon,
        };
    }
    save(changes);
  }

  const editingLane = editingVoice === null ? null : lanes[editingVoice];
  const editingId = editingLane?.speakerId ?? null;

  const markers = reportMarkers(report, total);
  const present = KINDS.filter((kind) =>
    markers.some((marker) => marker.tone === kind.tone),
  );
  const wins = report.strengths.length;
  const toWorkOn =
    report.missed_opportunities.length + report.improvements.length;
  const ratio = lanes.map((lane) => Math.round(lane.share * 100));

  const hoverMs = hover === null ? null : hover * total;
  const turn =
    hoverMs === null ? null : segmentAt(transcript.segments, hoverMs);
  const voice = turn ? facts.voices.indexOf(turn.speaker_id ?? "unknown") : -1;
  const hoverBin =
    hover === null
      ? -1
      : Math.min(BIN_COUNT - 1, Math.floor(hover * BIN_COUNT));

  function ratioAt(event: PointerEvent<HTMLElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return 0;
    return Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
  }

  function seekBy(event: KeyboardEvent<HTMLElement>) {
    const target = keyTarget(event.key, currentTimeMs, total);
    if (target === null) return;
    event.preventDefault();
    onSeek(target);
  }

  return (
    <figure
      className={styles.map}
      aria-label="Call map"
      data-focus={focusTone ?? undefined}
      style={
        {
          "--lanes":
            lens === "who"
              ? lanes.length > 1
                ? lanes.length
                : 0
              : lens === "interest"
                ? 4
                : 2,
        } as CSSProperties
      }
    >
      <div className={styles.card}>
        <div className={styles.head}>
          <div
            className={styles.lenses}
            role="group"
            aria-label="What the map shows"
          >
            {LENSES.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-pressed={lens === option.key}
                onClick={() => chooseLens(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <span className={styles.legend}>
            {present.map((kind) => (
              <span
                key={kind.tone}
                data-tone={kind.tone}
                onPointerEnter={() => setFocusTone(kind.tone)}
                onPointerLeave={() => setFocusTone(null)}
              >
                <i aria-hidden="true" />
                {kind.label}
              </span>
            ))}
          </span>
        </div>
        <div className={styles.subhead}>
          {lens === "who" ? (
            lanes.length > 1 ? (
              <div className={styles.who}>
                <div
                  className={styles.speakers}
                  role="group"
                  aria-label="Speakers"
                  data-speaker-chips
                >
                  {lanes.map((lane) => {
                    const profile = lane.speakerId
                      ? profiles[lane.speakerId]
                      : undefined;
                    const editable = canSave && lane.speakerId !== null;
                    const name = laneName(lane);
                    return (
                      <button
                        key={lane.lane}
                        type="button"
                        className={styles.speaker}
                        data-voice={lane.lane}
                        style={voiceStyle(lane.lane)}
                        aria-expanded={
                          editable ? editingVoice === lane.lane : undefined
                        }
                        aria-label={editable ? `Edit ${name}` : name}
                        onPointerEnter={() => setHoverVoice(lane.lane)}
                        onPointerLeave={() => setHoverVoice(null)}
                        onClick={(event) => {
                          if (!editable) return;
                          const anchor = event.currentTarget;
                          setEditing((current) =>
                            current?.voice === lane.lane
                              ? null
                              : { voice: lane.lane, anchor },
                          );
                        }}
                      >
                        {lane.speakerId !== null ? (
                          <SpeakerAvatar
                            voice={lane.lane}
                            profile={profile}
                            youName={accountName}
                          />
                        ) : (
                          <i aria-hidden="true" />
                        )}
                        <span className={styles.speakerName}>{name}</span>
                        {profile?.role ? (
                          <small>{ROLE_LABELS[profile.role]}</small>
                        ) : null}
                      </button>
                    );
                  })}
                  {editing !== null && editingId !== null ? (
                    <SpeakerEditor
                      key={editingId}
                      voice={editing.voice}
                      anchor={editing.anchor}
                      label={`Speaker ${editing.voice + 1}`}
                      share={ratio[editing.voice] ?? 0}
                      sample={samples.get(editingId) ?? null}
                      profile={profiles[editingId]}
                      youName={accountName}
                      suggestedIcon={prospectIcon}
                      onSave={(profile) => {
                        if (!save({ [editingId]: profile })) return false;
                        setEditing(null);
                        return true;
                      }}
                      onClose={closeEditor}
                    />
                  ) : null}
                </div>
                {askId !== null && askVoice >= 0 ? (
                  <span className={styles.ask} role="status">
                    <Sparkles size={13} aria-hidden="true" />
                    <span>
                      <b>{nameOf(askVoice)}</b>
                      {spoken.names[askId] && !askIsYou
                        ? ` · ${spoken.names[askId]}`
                        : ""}{" "}
                      {askIsYou ? "looks like you" : "is the salesperson"}
                    </span>
                    <button
                      type="button"
                      onClick={() => confirmSeller(askId, askIsYou)}
                    >
                      Yes
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setDeclined((current) => [...current, askId])
                      }
                    >
                      No
                    </button>
                  </span>
                ) : null}
              </div>
            ) : (
              <span className={styles.note}>One voice on this call.</span>
            )
          ) : lens === "stages" ? (
            <span className={styles.note}>
              Stages (hello, questions, pitch, wrap-up) show here once the
              analysis marks them.
            </span>
          ) : prospectVoice ? (
            <span className={styles.note}>
              How much <b>{nameOf(facts.voices.indexOf(prospectVoice))}</b>{" "}
              talked each minute
              {quietMs !== null ? (
                <>
                  {" "}
                  · went quiet at <b>{formatClock(quietMs)}</b> and talked{" "}
                  {Math.round(quietTalkMs / 1000)} s after that
                </>
              ) : null}
            </span>
          ) : (
            <span className={styles.note}>
              Needs two voices to show interest.
            </span>
          )}
        </div>

        <div className={styles.timeline}>
          {turn ? (
            <span
              className={styles.turn}
              aria-hidden="true"
              style={{
                left: `${(turn.start_ms / total) * 100}%`,
                width: `${((turn.end_ms - turn.start_ms) / total) * 100}%`,
              }}
            />
          ) : null}
          <div className={styles.track} data-morph-source>
            {levels ? (
              <svg
                className={styles.wave}
                data-morph-wave
                data-voice={
                  lens === "who" ? (focusVoice ?? undefined) : undefined
                }
                style={
                  lens === "who" && focusVoice !== null
                    ? voiceStyle(focusVoice)
                    : undefined
                }
                viewBox={`0 0 ${BIN_COUNT * 4} 56`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                {levels.map((level, index) => {
                  const height = Math.max(1.5, Math.pow(level ?? 0, 0.55) * 25);
                  const center = (index + 0.5) / BIN_COUNT;
                  const tone =
                    progress > 0 && center <= progress
                      ? styles.played
                      : hover !== null && center > progress && center <= hover
                        ? styles.ahead
                        : styles.pending;
                  const hot = hoverBin >= 0 && Math.abs(index - hoverBin) <= 1;
                  const dim =
                    lens === "who" &&
                    focusVoice !== null &&
                    owners[index] !== focusVoice;
                  return (
                    <line
                      key={index}
                      x1={index * 4 + 2}
                      x2={index * 4 + 2}
                      y1={28 - height}
                      y2={28 + height}
                      className={[
                        tone,
                        hot ? styles.hot : "",
                        dim ? styles.dim : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      style={{ "--i": index } as CSSProperties}
                    />
                  );
                })}
              </svg>
            ) : (
              <div
                className={styles.noWave}
                data-morph-wave
                aria-hidden="true"
              />
            )}
            {markers.map((marker) => (
              <button
                key={marker.key}
                type="button"
                className={styles.pin}
                data-tone={marker.tone}
                data-active={
                  currentTimeMs >= marker.evidence.start_ms &&
                  currentTimeMs < marker.evidence.end_ms
                    ? "true"
                    : undefined
                }
                data-edge={
                  marker.x < 16 ? "start" : marker.x > 84 ? "end" : undefined
                }
                style={{ left: `${marker.x}%` }}
                aria-label={`${marker.kind}: ${marker.title}, at ${formatClock(marker.evidence.start_ms)}. Play this moment.`}
                onClick={() => onSelectEvidence(marker.evidence)}
              >
                <span className={styles.tip} aria-hidden="true">
                  <em>
                    {marker.kind} · {formatClock(marker.evidence.start_ms)}
                  </em>
                  {marker.title}
                </span>
              </button>
            ))}
          </div>
          {lens === "who" && lanes.length > 1 ? (
            <div className={styles.lanes} aria-hidden="true">
              {lanes.map((lane) => (
                <svg
                  key={lane.lane}
                  className={styles.lane}
                  data-voice={lane.lane}
                  style={voiceStyle(lane.lane)}
                  data-dim={
                    focusVoice !== null && focusVoice !== lane.lane
                      ? "true"
                      : undefined
                  }
                  viewBox={`0 0 ${total} 1`}
                  preserveAspectRatio="none"
                >
                  {lane.spans.map(([start, end]) => (
                    <rect
                      key={start}
                      x={start}
                      width={Math.max(end - start, total / 800)}
                      y={0}
                      height={1}
                    />
                  ))}
                </svg>
              ))}
            </div>
          ) : null}
          {lens === "interest" && interestPath ? (
            <div className={styles.interest} aria-hidden="true">
              <svg viewBox={`0 0 ${total} 1`} preserveAspectRatio="none">
                <path className={styles.interestArea} d={interestPath.area} />
                <path
                  className={styles.interestLine}
                  d={interestPath.line}
                  vectorEffect="non-scaling-stroke"
                />
              </svg>
              {quietMs !== null ? (
                <span
                  className={styles.quiet}
                  style={{ left: `${(quietMs / total) * 100}%` }}
                />
              ) : null}
            </div>
          ) : null}
          {lens === "stages" ? (
            <div className={styles.stagesEmpty} aria-hidden="true" />
          ) : null}
          {progress > 0 ? (
            <span
              className={styles.playhead}
              data-playing={playing ? "true" : undefined}
              style={{ left: `${progress * 100}%` }}
              aria-hidden="true"
            />
          ) : null}
          <div
            className={styles.scrub}
            role="slider"
            tabIndex={0}
            aria-label="Play the call from a point in time"
            aria-valuemin={0}
            aria-valuemax={Math.round(total / 1000)}
            aria-valuenow={Math.round(currentTimeMs / 1000)}
            aria-valuetext={`${formatClock(currentTimeMs)} of ${formatClock(total)}`}
            onPointerMove={(event) => setHover(ratioAt(event))}
            onPointerLeave={() => {
              if (!scrubbing) setHover(null);
            }}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.currentTarget.setPointerCapture?.(event.pointerId);
              setScrubbing(true);
              setHover(ratioAt(event));
            }}
            onPointerUp={(event) => {
              if (!scrubbing) return;
              setScrubbing(false);
              event.currentTarget.releasePointerCapture?.(event.pointerId);
              onSeek(ratioAt(event) * total);
              if (event.pointerType !== "mouse") setHover(null);
            }}
            onPointerCancel={() => {
              setScrubbing(false);
              setHover(null);
            }}
            onKeyDown={seekBy}
          />
          {hover !== null && hoverMs !== null ? (
            <span
              className={styles.cursor}
              style={{ left: `${hover * 100}%` }}
              aria-hidden="true"
            >
              <span
                className={styles.peek}
                data-edge={
                  hover < 0.14 ? "start" : hover > 0.86 ? "end" : undefined
                }
              >
                <span className={styles.peekHead}>
                  <b>{formatClock(hoverMs)}</b>
                  {turn && voice >= 0 ? (
                    <span
                      data-voice={laneOf[voice]}
                      style={voiceStyle(laneOf[voice] ?? voice)}
                    >
                      <SpeakerAvatar
                        voice={laneOf[voice] ?? voice}
                        profile={profileOf(voice)}
                        youName={accountName}
                        size={16}
                      />
                      {nameOf(voice)}
                    </span>
                  ) : (
                    <span>Pause</span>
                  )}
                </span>
                {turn ? <q>{turn.text}</q> : null}
                <small>
                  <Play size={10} aria-hidden="true" />
                  {scrubbing ? "Release to play" : "Click to play from here"}
                </small>
              </span>
            </span>
          ) : null}
        </div>

        <div className={styles.foot}>
          <span
            className={styles.time}
            data-live={progress > 0 ? "true" : undefined}
          >
            {formatClock(progress > 0 ? currentTimeMs : 0)}
          </span>
          <span className={styles.time}>{formatClock(total)}</span>
        </div>
      </div>

      <figcaption className={styles.stats}>
        <div className={styles.stat} data-tone="teal">
          <span className={styles.icon} aria-hidden="true">
            <MessagesSquare size={15} />
          </span>
          <span className={styles.body}>
            <small>
              Who talked more
              {named ? ` · ${lanes.map(laneName).join(" : ")}` : ""}
            </small>
            <b>{lanes.length > 1 ? ratio.join(" : ") : "One voice"}</b>
            {lanes.length > 1 ? (
              <span className={styles.ratio} aria-hidden="true">
                {lanes.map((lane) => (
                  <span
                    key={lane.lane}
                    data-voice={lane.lane}
                    style={{
                      ...voiceStyle(lane.lane),
                      flexGrow: Math.max(lane.share, 0.01),
                    }}
                  />
                ))}
              </span>
            ) : null}
          </span>
        </div>
        <div className={styles.stat} data-tone="amber">
          <span className={styles.icon} aria-hidden="true">
            <Timer size={15} />
          </span>
          <span className={styles.body}>
            <small>
              Longest non-stop talk
              {facts.longest.voice >= 0
                ? ` · ${nameOf(facts.longest.voice)}`
                : ""}
            </small>
            <b>{formatClock(facts.longest.ms)}</b>
          </span>
        </div>
        <div className={styles.stat} data-tone="blue">
          <span className={styles.icon} aria-hidden="true">
            <MessageCircleQuestion size={15} />
          </span>
          <span className={styles.body}>
            <small>
              Questions asked
              {lanes.length > 1 ? ` · ${lanes.map(laneName).join(" : ")}` : ""}
            </small>
            <b>
              {questionsPerLane.slice(0, Math.max(1, lanes.length)).join(" : ")}
            </b>
          </span>
        </div>
        <div className={styles.stat} data-tone="violet">
          <span className={styles.icon} aria-hidden="true">
            <Target size={15} />
          </span>
          <span className={styles.body}>
            <small>What the report found</small>
            <b>
              {wins}
              <small> done well · </small>
              {toWorkOn}
              <small> to work on</small>
            </b>
            {wins + toWorkOn > 0 ? (
              <span className={styles.balance} aria-hidden="true">
                <span
                  style={{ width: `${(wins / (wins + toWorkOn)) * 100}%` }}
                />
              </span>
            ) : null}
          </span>
        </div>
      </figcaption>
    </figure>
  );
}

/**
 * The call map folded into the pinned report row. Its waveform is drawn with
 * exactly the same bars and proportions as the full one, so the report header
 * can fold one into the other pixel for pixel. Hover shows a time, click or
 * drag plays from there, arrow keys step through the call.
 */
export function CallMapMini({
  report,
  durationMs,
  onSeek,
}: {
  report: SalesReport;
  durationMs: number;
  onSeek: (ms: number) => void;
}) {
  const { envelope, currentTimeMs, playing } = useSourceWaveform();
  const [hover, setHover] = useState<number | null>(null);
  const [scrubbing, setScrubbing] = useState(false);
  const total = Math.max(1, durationMs);
  const levels = envelope
    ? waveformBins(envelope, 0, envelope.duration_ms, BIN_COUNT)
    : null;
  const progress = Math.min(1, Math.max(0, currentTimeMs / total));
  const markers = reportMarkers(report, total);

  function ratioAt(event: PointerEvent<HTMLElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return 0;
    return Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
  }

  return (
    <div className={styles.mini} data-call-map-mini>
      <span
        className={styles.miniChrome}
        data-morph-chrome
        aria-hidden="true"
      />
      <span
        className={styles.miniTime}
        data-morph-chrome
        data-live={hover !== null || progress > 0 ? "true" : undefined}
      >
        {formatClock(hover !== null ? hover * total : currentTimeMs)}
      </span>
      <div className={styles.miniTrack} data-morph-slot>
        <div className={styles.miniLayer} data-morph-layer>
          {levels ? (
            <svg
              className={styles.miniWave}
              viewBox={`0 0 ${BIN_COUNT * 4} 56`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {levels.map((level, index) => {
                // Same geometry as the full waveform, bar for bar.
                const height = Math.max(1.5, Math.pow(level ?? 0, 0.55) * 25);
                const center = (index + 0.5) / BIN_COUNT;
                const tone =
                  progress > 0 && center <= progress
                    ? styles.played
                    : hover !== null && center <= hover
                      ? styles.ahead
                      : styles.pending;
                return (
                  <line
                    key={index}
                    x1={index * 4 + 2}
                    x2={index * 4 + 2}
                    y1={28 - height}
                    y2={28 + height}
                    className={tone}
                  />
                );
              })}
            </svg>
          ) : (
            <div className={styles.noWave} aria-hidden="true" />
          )}
          {markers.map((marker) => (
            <span
              key={marker.key}
              className={styles.miniDot}
              data-morph-chrome
              data-tone={marker.tone}
              style={{ left: `${marker.x}%` }}
              aria-hidden="true"
            />
          ))}
          {progress > 0 ? (
            <span
              className={styles.miniHead}
              data-morph-chrome
              data-playing={playing ? "true" : undefined}
              style={{ left: `${progress * 100}%` }}
              aria-hidden="true"
            />
          ) : null}
          {hover !== null ? (
            <span
              className={styles.miniCursor}
              style={{ left: `${hover * 100}%` }}
              aria-hidden="true"
            />
          ) : null}
          <div
            className={styles.scrub}
            role="slider"
            tabIndex={0}
            aria-label="Play the call from a point in time"
            aria-valuemin={0}
            aria-valuemax={Math.round(total / 1000)}
            aria-valuenow={Math.round(currentTimeMs / 1000)}
            aria-valuetext={`${formatClock(currentTimeMs)} of ${formatClock(total)}`}
            onPointerMove={(event) => setHover(ratioAt(event))}
            onPointerLeave={() => {
              if (!scrubbing) setHover(null);
            }}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.currentTarget.setPointerCapture?.(event.pointerId);
              setScrubbing(true);
              setHover(ratioAt(event));
            }}
            onPointerUp={(event) => {
              if (!scrubbing) return;
              setScrubbing(false);
              event.currentTarget.releasePointerCapture?.(event.pointerId);
              onSeek(ratioAt(event) * total);
              if (event.pointerType !== "mouse") setHover(null);
            }}
            onPointerCancel={() => {
              setScrubbing(false);
              setHover(null);
            }}
            onKeyDown={(event) => {
              const target = keyTarget(event.key, currentTimeMs, total);
              if (target === null) return;
              event.preventDefault();
              onSeek(target);
            }}
          />
        </div>
      </div>
      <span className={styles.miniTotal} data-morph-chrome>
        {formatClock(total)}
      </span>
    </div>
  );
}
