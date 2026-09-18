"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  Check,
  ChevronRight,
  FileJson,
  Fingerprint,
  FolderOpen,
  Layers3,
  LockKeyhole,
  MessageSquareText,
  Moon,
  Play,
  Search,
  ShieldCheck,
  Sun,
  Upload,
} from "lucide-react";
import { BrandMark } from "@ac/ui";
import {
  assertCheckpointRevision,
  createMeasurementProposal,
  createReviewProposal,
  loadCapabilities,
  loadExample,
  validateCheckpoint,
  type ChannelMeasurement,
  type ConversationCapabilities,
  type ConversationExample,
  type LocalCheckpoint,
  type TranscriptSegment,
} from "@ac/sales-xray-client";

type Tab = "workbench" | "evidence" | "review" | "library";
type Run = {
  id: string;
  title: string;
  duration: number;
  revision: string;
  transcriptRevision: string;
  segments: TranscriptSegment[];
  provenance: string;
  local: LocalCheckpoint | null;
};
const nav = [
  { id: "workbench", label: "Workbench", icon: AudioLines },
  { id: "evidence", label: "Source & evidence", icon: Fingerprint },
  { id: "review", label: "Review notes", icon: MessageSquareText },
  { id: "library", label: "Session library", icon: FolderOpen },
] as const;
export const time = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}`;
function exampleRun(v: ConversationExample): Run {
  return {
    id: v.id,
    title: v.title,
    duration: v.duration_ms,
    revision: "synthetic-example-v1",
    transcriptRevision: v.transcript.revision ?? "synthetic-example-v1",
    segments: v.transcript.segments,
    provenance:
      v.transcript.provenance ??
      "Synthetic script. Known segment boundaries; not a speech-recognition result.",
    local: null,
  };
}
function checkpointRun(v: LocalCheckpoint): Run {
  return {
    id: v.run_id,
    title: v.source.name ?? "Local conversation",
    duration: v.source.duration_ms,
    revision: v.revision,
    transcriptRevision: v.transcript.revision,
    segments: v.transcript.segments,
    provenance: v.transcript.provenance,
    local: v,
  };
}

const subscribeLocation = (listener: () => void) => {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
};
const currentRunLink = () =>
  new URLSearchParams(window.location.search).has("run");
const serverRunLink = () => false;

export function Workbench({ hasRunLink = false }: { hasRunLink?: boolean }) {
  const browserRunLink = useSyncExternalStore(
    subscribeLocation,
    currentRunLink,
    serverRunLink,
  );
  const [tab, setTab] = useState<Tab>("workbench");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [capabilities, setCapabilities] =
    useState<ConversationCapabilities | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [library, setLibrary] = useState<Run[]>([]);
  const [error, setError] = useState("");
  const [importError, setImportError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [importing, setImporting] = useState(false);
  const entryNotice =
    hasRunLink || browserRunLink
      ? "This link refers to a saved run. Saved-run access needs an authorized AC session; the example below is a separate synthetic conversation."
      : "";
  const importInput = useRef<HTMLInputElement>(null);
  const importAttempt = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const abort = new AbortController();
    Promise.all([loadCapabilities(abort.signal), loadExample(abort.signal)])
      .then(([caps, example]) => {
        const next = exampleRun(example);
        setCapabilities(caps);
        setRun((current) => (current?.local ? current : next));
        setLibrary((current) => [next, ...current.filter((v) => v.local)]);
        setError("");
      })
      .catch((e) => {
        if (!abort.signal.aborted)
          setError(
            e instanceof Error
              ? e.message
              : "The service could not be reached.",
          );
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [retry]);
  function navigate(next: Tab) {
    setTab(next);
    requestAnimationFrame(() => heading.current?.focus());
  }
  async function importCheckpoint(file: File | undefined) {
    if (!file) return;
    const attempt = ++importAttempt.current;
    setImporting(true);
    setImportError("");
    try {
      if (file.size > 5 * 1024 * 1024)
        throw new Error("Choose a checkpoint smaller than 5 MB.");
      const checkpoint = validateCheckpoint(JSON.parse(await file.text()));
      if (attempt !== importAttempt.current) return;
      assertCheckpointRevision(
        library.flatMap((v) => (v.local ? [v.local] : [])),
        checkpoint,
      );
      const next = checkpointRun(checkpoint);
      setRun(next);
      setLibrary((current) =>
        [
          ...current.filter(
            (v) => v.id !== next.id || v.revision !== next.revision,
          ),
          next,
        ].slice(-10),
      );
      navigate("workbench");
    } catch (e) {
      if (attempt !== importAttempt.current) return;
      setImportError(
        e instanceof SyntaxError
          ? "This file is not valid JSON. Choose an exported Sales Xray checkpoint."
          : e instanceof Error
            ? e.message
            : "The checkpoint could not be opened.",
      );
    } finally {
      if (attempt === importAttempt.current) {
        setImporting(false);
        if (importInput.current) importInput.current.value = "";
      }
    }
  }
  return (
    <div className="xray-app" data-theme={theme}>
      <a href="#main" className="skip-link">
        Skip to conversation
      </a>
      <aside className="sidebar" aria-label="Sales Xray navigation">
        <Link
          className="brand"
          href="/"
          prefetch={false}
          aria-label="Dipak’s Sales Xray home"
        >
          <span className="brand-symbol">
            <BrandMark />
          </span>
          <span>
            Sales Xray<small>BY AUTHORITY CLOSERS</small>
          </span>
        </Link>
        <div className="workspace-label">YOUR CONVERSATION STUDIO</div>
        <nav>
          {nav.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-label={label}
              className={tab === id ? "nav-item active" : "nav-item"}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => navigate(id)}
            >
              <Icon size={19} />
              <span>{label}</span>
              {id === "library" && (
                <span className="nav-count">{library.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="note-icon">
            <Layers3 size={21} />
          </span>
          <strong>
            Better calls start
            <br />
            with a closer look.
          </strong>
          <p>
            Evidence first.
            <br />A thoughtful second opinion.
          </p>
          <span className="tiny-rule" />
        </div>
        <div className="sidebar-bottom">
          <ShieldCheck size={17} />
          <span>Part of the AC learning experience</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Dipak’s Sales Xray <ChevronRight size={14} />
            <span>{nav.find((v) => v.id === tab)?.label}</span>
          </div>
          <div className="header-actions">
            <span className="session-label">
              <span />
              Local review workspace
            </span>
            <button
              className="icon-button"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label={`Switch to ${theme === "light" ? "dark" : "light"} appearance`}
            >
              {theme === "light" ? <Moon size={19} /> : <Sun size={19} />}
            </button>
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <p className="eyebrow">CONVERSATION INTELLIGENCE</p>
              <h1 ref={heading} tabIndex={-1}>
                {tab === "workbench"
                  ? "Look closer. Learn more."
                  : tab === "evidence"
                    ? "Follow the evidence."
                    : tab === "review"
                      ? "A better second look."
                      : "Your conversations, here."}
              </h1>
              <p className="subtitle">
                {tab === "workbench"
                  ? "Go from what was said to what deserves your attention."
                  : tab === "evidence"
                    ? "Every source, timestamp and measurement keeps its own context."
                    : tab === "review"
                      ? "Contextual feedback and measurement checks have separate review lanes."
                      : "Conversations opened in this tab. Local files stay on this device."}
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => importInput.current?.click()}
              disabled={importing}
            >
              <Upload size={17} />
              {importing ? "Opening checkpoint…" : "Open checkpoint"}
            </button>
            <input
              ref={importInput}
              type="file"
              accept=".json,application/json"
              className="visually-hidden"
              aria-label="Open local checkpoint JSON"
              onChange={(e) => void importCheckpoint(e.target.files?.[0])}
            />
          </div>
          <div aria-live="polite">
            {entryNotice && (
              <div className="notice">
                <LockKeyhole size={18} />
                <span>{entryNotice}</span>
              </div>
            )}
            {importError && (
              <div className="notice error" role="alert">
                <FileJson size={18} />
                <span>{importError}</span>
              </div>
            )}
            {error && (
              <div className="notice error" role="alert">
                <Activity size={18} />
                <span>{error}</span>
                <button
                  className="text-button"
                  onClick={() => {
                    setLoading(true);
                    setRetry((v) => v + 1);
                  }}
                >
                  Retry service
                </button>
              </div>
            )}
          </div>
          {tab === "library" ? (
            <section className="panel library">
              <div className="section-heading">
                <h2>Opened this session</h2>
                <span className="muted">{library.length} conversations</span>
              </div>
              <p className="muted">
                This list is kept in memory and clears when you close or refresh
                the page. Account history is not connected.
              </p>
              {library.length === 0 && (
                <Empty
                  title="Nothing opened yet"
                  text="Open a checkpoint to review a local conversation, or retry the service to explore the synthetic example."
                />
              )}
              {library.map((v) => (
                <button
                  className="library-row"
                  key={`${v.id}:${v.revision}`}
                  onClick={() => {
                    setRun(v);
                    navigate("workbench");
                  }}
                >
                  <span className="file-icon">
                    <AudioLines size={22} />
                  </span>
                  <span>
                    <strong>{v.title}</strong>
                    <small>
                      {v.local ? "Local checkpoint" : "Synthetic example"} ·{" "}
                      {time(v.duration)} · {v.revision}
                    </small>
                  </span>
                  <ArrowRight size={19} />
                </button>
              ))}
              {library.some((v) => v.local) && (
                <button
                  className="secondary-button"
                  onClick={() => {
                    setLibrary((current) => current.filter((v) => !v.local));
                    setRun((current) => (current?.local ? null : current));
                  }}
                >
                  Clear local session data
                </button>
              )}
            </section>
          ) : run ? (
            <RunWorkspace
              key={`${run.id}:${run.revision}`}
              run={run}
              tab={tab}
              navigate={navigate}
            />
          ) : (
            <section className="panel">
              <Empty
                title={
                  loading
                    ? "Opening the conversation studio…"
                    : "Your workspace is ready"
                }
                text={
                  loading
                    ? "Fetching the clearly labelled synthetic example from the AC conversation API."
                    : "Open a local checkpoint to begin. The example will appear when the conversation service is available."
                }
              />
            </section>
          )}
          <footer className="page-footer">
            <span>
              <LockKeyhole size={14} />
              Local files are never uploaded by this workspace.
            </span>
            <span>
              {capabilities
                ? "Provider processing disabled · Numeric publication withheld"
                : "Service capabilities unavailable · Intake disabled"}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <AudioLines size={28} />
      </span>
      <h2>{title}</h2>
      <p>{text}</p>
    </div>
  );
}

function RunWorkspace({
  run,
  tab,
  navigate,
}: {
  run: Run;
  tab: Tab;
  navigate: (v: Tab) => void;
}) {
  const [selected, setSelected] = useState(run.segments[0]?.id ?? "");
  const [search, setSearch] = useState("");
  const [speaker, setSpeaker] = useState("all");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioStatus, setAudioStatus] = useState("");
  const [position, setPosition] = useState(0);
  const [checking, setChecking] = useState(false);
  const [reviewLane, setReviewLane] = useState<"contextual" | "measurements">(
    run.segments.length ? "contextual" : "measurements",
  );
  const [reviewNote, setReviewNote] = useState("");
  const [measurementSelection, setMeasurementSelection] = useState({
    series: "",
    point: "",
  });
  const audio = useRef<HTMLAudioElement>(null);
  const alive = useRef(true);
  const audioAttempt = useRef(0);
  const segment = run.segments.find((v) => v.id === selected);
  const speakers = [...new Set(run.segments.map((v) => v.speaker_id))];
  const visible = run.segments.filter(
    (v) =>
      (speaker === "all" || v.speaker_id === speaker) &&
      v.text.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );
  async function selectAudio(file: File | undefined) {
    if (!file || !run.local) return;
    const attempt = ++audioAttempt.current;
    setChecking(true);
    setAudioStatus("");
    setAudioUrl(null);
    try {
      if (file.size > 100 * 1024 * 1024)
        throw new Error("Local preview is limited to 100 MB per file.");
      const digest = await crypto.subtle.digest(
        "SHA-256",
        await file.arrayBuffer(),
      );
      const hash = Array.from(new Uint8Array(digest), (v) =>
        v.toString(16).padStart(2, "0"),
      ).join("");
      if (hash !== run.local.source.sha256)
        throw new Error(
          "This audio does not match the checkpoint source SHA-256. Playback was not linked.",
        );
      if (alive.current && attempt === audioAttempt.current) {
        setAudioUrl(URL.createObjectURL(file));
        setAudioStatus(
          "Source SHA-256 matched. Playback stays on this device.",
        );
      }
    } catch (e) {
      if (alive.current && attempt === audioAttempt.current)
        setAudioStatus(
          e instanceof Error ? e.message : "The source could not be verified.",
        );
    } finally {
      if (alive.current && attempt === audioAttempt.current) setChecking(false);
    }
  }
  function seek(id: string) {
    setSelected(id);
    const next = run.segments.find((v) => v.id === id);
    if (next && audio.current) {
      audio.current.currentTime = next.start_ms / 1000;
      setPosition(next.start_ms);
    }
  }
  return (
    <>
      <section className="conversation-head panel">
        <div className="conversation-icon">
          <AudioLines size={28} />
        </div>
        <div className="conversation-title">
          <div className="inline-labels">
            <span className={run.local ? "pill local" : "pill"}>
              {run.local ? "LOCAL CHECKPOINT" : "SYNTHETIC EXAMPLE"}
            </span>
            <span className="muted">
              {run.local
                ? "Imported · Unverified review data"
                : "A scripted practice conversation"}
            </span>
          </div>
          <h2>{run.title}</h2>
          <p>
            {time(run.duration)}{" "}
            {run.local?.signal_metadata
              ? "decoded-track duration"
              : "source duration"}{" "}
            <span>·</span>{" "}
            {speakers.length
              ? `${speakers.length} speaker labels`
              : "Speaker attribution unavailable"}{" "}
            <span>·</span>{" "}
            {run.segments.length
              ? `${run.segments.length} evidence spans`
              : "No transcript"}
          </p>
        </div>
        <span className="draft-label">
          <LockKeyhole size={14} />
          No published score
        </span>
      </section>
      {tab === "evidence" ? (
        <Evidence run={run} />
      ) : tab === "review" ? (
        <Review
          run={run}
          selected={selected}
          setSelected={seek}
          lane={reviewLane}
          setLane={setReviewLane}
          note={reviewNote}
          setNote={setReviewNote}
          measurementSelection={measurementSelection}
          setMeasurementSelection={setMeasurementSelection}
          audioSourceMatched={Boolean(audioUrl)}
        />
      ) : (
        <>
          <div className="metric-grid">
            <Metric
              label="Source duration"
              value={time(run.duration)}
              detail={
                run.local?.signal_metadata
                  ? "Decoded track · sync uncertified"
                  : "Original recording clock"
              }
              icon={<AudioLines size={18} />}
            />
            <Metric
              label="Evidence spans"
              value={
                run.segments.length
                  ? String(run.segments.length)
                  : "Not available"
              }
              detail={
                run.segments.length
                  ? "Literal transcript segments"
                  : "C1 contains acoustics only"
              }
              icon={<MessageSquareText size={18} />}
            />
            <Metric
              label="Measurement source"
              value={
                run.local?.channels.length
                  ? `${run.local.channels.length} series`
                  : "Not available"
              }
              detail={
                run.local?.channels.length
                  ? "Profiles retained independently"
                  : "No audio inference in this example"
              }
              icon={<Activity size={18} />}
            />
            <Metric
              label="Coaching profile"
              value="Dipak · draft"
              detail="95 source / 100 declared · Held"
              icon={<Layers3 size={18} />}
            />
          </div>
          <div className="workbench-grid">
            <section className="panel transcript-panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">THE CONVERSATION</p>
                  <h2>Read between the moments.</h2>
                </div>
                <span className="pill subtle">
                  {run.local ? "Local transcript" : "Known script"}
                </span>
              </div>
              <div className="transcript-tools">
                <label className="search-field">
                  <Search size={17} />
                  <input
                    type="search"
                    aria-label="Search transcript"
                    placeholder="Find a word or phrase"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <select
                  aria-label="Filter speaker"
                  value={speaker}
                  onChange={(e) => setSpeaker(e.target.value)}
                >
                  <option value="all">All speakers</option>
                  {speakers.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              <div className="transcript-list" aria-label="Transcript segments">
                {visible.length === 0 &&
                  (run.segments.length ? (
                    <div className="search-empty">
                      No matching evidence. Try a different phrase or speaker.
                    </div>
                  ) : (
                    <Empty
                      title="Acoustics ready. Transcript unavailable."
                      text="This C1 checkpoint measures audio only. A transcript checkpoint is a separate, reusable stage. Speaker attribution and sales context have not been inferred."
                    />
                  ))}
                {visible.map((v) => (
                  <button
                    type="button"
                    className={`transcript-row ${selected === v.id ? "selected" : ""}`}
                    key={v.id}
                    aria-pressed={selected === v.id}
                    onClick={() => seek(v.id)}
                  >
                    <span className="timestamp">
                      {time(v.start_ms)}
                      <Play size={10} />
                    </span>
                    <span className="transcript-content">
                      <span
                        className={`speaker ${speakers.indexOf(v.speaker_id) % 2 ? "speaker-alt" : ""}`}
                      >
                        {v.speaker_id}
                        <span>{time(v.end_ms)}</span>
                      </span>
                      <span className="transcript-text">{v.text}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="transcript-foot">
                <Fingerprint size={15} />
                <span>
                  {run.local
                    ? "Imported data. Attribution awaits measurement review."
                    : "Synthetic boundaries; not word alignment or model transcription."}
                </span>
              </div>
            </section>
            <aside className="right-column">
              <section className="panel focus-panel">
                <div className="section-heading">
                  <p className="eyebrow">IN FOCUS</p>
                  <span className="focus-dot" />
                </div>
                <h2>The moment you selected.</h2>
                {segment ? (
                  <>
                    <div className="evidence-time">
                      <Play size={12} />
                      {time(segment.start_ms)} – {time(segment.end_ms)}
                      <span>{segment.speaker_id}</span>
                    </div>
                    <blockquote>{segment.text}</blockquote>
                    <p className="muted">
                      Start with these words. Check the preceding context before
                      proposing a coaching interpretation.
                    </p>
                    <button
                      className="text-button"
                      onClick={() => navigate("review")}
                    >
                      Add a review note <ArrowRight size={16} />
                    </button>
                  </>
                ) : (
                  <p className="muted">
                    No transcript is available in this checkpoint.
                  </p>
                )}
              </section>
              <section className="panel source-panel">
                <div className="section-heading">
                  <h3>Source playback</h3>
                  <LockKeyhole size={17} />
                </div>
                {run.local ? (
                  <>
                    <p>
                      {run.segments.length
                        ? "Link the original audio to navigate with the transcript. We verify its source fingerprint first."
                        : "Play the original audio beside its measurements. We verify the source fingerprint first."}
                    </p>
                    <label className="secondary-button file-label">
                      <FolderOpen size={16} />
                      {checking ? "Checking source…" : "Choose local audio"}
                      <input
                        type="file"
                        accept="audio/*,.mpeg"
                        aria-label="Choose matching local audio"
                        disabled={checking}
                        onChange={(e) => {
                          void selectAudio(e.target.files?.[0]);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    <p className="audio-status" role="status">
                      {audioStatus}
                    </p>
                    {audioUrl && (
                      <audio
                        ref={audio}
                        src={audioUrl}
                        controls
                        preload="metadata"
                        onTimeUpdate={(e) =>
                          setPosition(e.currentTarget.currentTime * 1000)
                        }
                        onError={() =>
                          setAudioStatus(
                            "The source matches, but this browser cannot play its codec. Choose a supported browser; do not relabel a converted source.",
                          )
                        }
                        aria-label="Verified local source audio"
                      />
                    )}
                  </>
                ) : (
                  <>
                    <span className="playback-placeholder">
                      <AudioLines size={28} />
                      <span>No source audio attached</span>
                    </span>
                    <p>
                      This example contains a script only. Open a source-bound
                      checkpoint to link local audio.
                    </p>
                  </>
                )}
              </section>
              <section className="review-prompt">
                <div className="review-initials">
                  <span>D</span>
                  <span>S</span>
                </div>
                <h3>
                  Two perspectives.
                  <br />
                  One traceable review.
                </h3>
                <p>
                  Dipak reviews sales context.
                  <br />
                  Suyash checks measurements.
                </p>
                <button
                  className="text-button"
                  onClick={() => navigate("review")}
                >
                  Explore review lanes <ArrowRight size={16} />
                </button>
              </section>
            </aside>
          </div>
          {run.segments.length ? (
            <section className="panel timeline-panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">SOURCE CLOCK</p>
                  <h2>Conversation map</h2>
                </div>
                <span className="muted">
                  Segment occupancy · not an audio waveform
                </span>
              </div>
              <div className="timeline-ruler">
                <span>00:00</span>
                <span>{time(run.duration / 2)}</span>
                <span>{time(run.duration)}</span>
              </div>
              {speakers.map((who, i) => (
                <div className="timeline-row" key={who}>
                  <span>{who}</span>
                  <div className={`timeline-track ${i % 2 ? "alternate" : ""}`}>
                    {run.segments
                      .filter((v) => v.speaker_id === who)
                      .map((v) => (
                        <button
                          key={v.id}
                          style={{
                            left: `${(v.start_ms / run.duration) * 100}%`,
                            width: `${((v.end_ms - v.start_ms) / run.duration) * 100}%`,
                          }}
                          className={selected === v.id ? "selected" : ""}
                          onClick={() => seek(v.id)}
                          aria-label={`${who}, ${time(v.start_ms)} to ${time(v.end_ms)}: ${v.text}`}
                        />
                      ))}
                    {audioUrl && (
                      <span
                        className="playhead"
                        style={{
                          left: `${Math.min(position / run.duration, 1) * 100}%`,
                        }}
                      />
                    )}
                  </div>
                </div>
              ))}
              <button
                className="text-button"
                onClick={() => navigate("evidence")}
              >
                Inspect provenance & measurement profiles{" "}
                <ArrowRight size={16} />
              </button>
            </section>
          ) : (
            <div className="timeline-panel">
              <Evidence run={run} />
            </div>
          )}
        </>
      )}
    </>
  );
}
function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="metric">
      <div>
        <span>{label}</span>
        {icon}
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
function ChannelGraph({
  channel: c,
  duration,
}: {
  channel: ChannelMeasurement;
  duration: number;
}) {
  const values = c.points.flatMap((p) => (p.value === null ? [] : [p.value]));
  const low = values.length ? Math.min(...values) : null;
  const high = values.length ? Math.max(...values) : null;
  const min = low ?? 0;
  const max = high === low ? min + 1 : (high ?? 1);
  const path = c.points
    .map((p, index) => {
      if (p.value === null) return "";
      const command =
        index === 0 || c.points[index - 1]?.value === null ? "M" : "L";
      return `${command}${(p.start_ms / duration) * 800},${90 - ((p.value - min) / (max - min)) * 80}`;
    })
    .join(" ");
  return (
    <article className="channel">
      <div className="section-heading">
        <h3>{c.label}</h3>
        <span className="muted">{c.unit}</span>
      </div>
      <p className="small-text">
        {c.clock} · Window {c.window_ms} ms · Hop {c.hop_ms} ms
        {c.display_stride ? ` · Display stride ${c.display_stride} frames` : ""}
      </p>
      {values.length ? (
        <svg
          viewBox="0 0 800 100"
          role="img"
          aria-label={`${c.label}: ${values.length} available points; range ${low} to ${high} ${c.unit}. Missing values remain gaps.`}
          preserveAspectRatio="none"
        >
          <path d="M0 25H800 M0 50H800 M0 75H800" className="chart-grid" />
          <path d={path} className="chart-line" />
          {c.points.map((p, index) =>
            p.value !== null &&
            (index === 0 || c.points[index - 1]?.value === null) &&
            (index === c.points.length - 1 ||
              c.points[index + 1]?.value === null) ? (
              <circle
                key={p.start_ms}
                cx={(p.start_ms / duration) * 800}
                cy={90 - ((p.value - min) / (max - min)) * 80}
                r="2.5"
                className="chart-point"
              />
            ) : null,
          )}
        </svg>
      ) : (
        <p className="muted">
          No usable values in this channel. Missing values are not zero.
        </p>
      )}
      <details>
        <summary>Inspect exact points ({c.points.length})</summary>
        <div className="point-table">
          <table>
            <thead>
              <tr>
                <th>Track time (ms)</th>
                <th>Value ({c.unit})</th>
              </tr>
            </thead>
            <tbody>
              {c.points.map((p) => (
                <tr key={p.start_ms}>
                  <td>{p.start_ms}</td>
                  <td>{p.value ?? "Unavailable"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}
function Evidence({ run }: { run: Run }) {
  const metadata = run.local?.signal_metadata;
  return (
    <div className="evidence-grid">
      <section className="panel">
        <div className="section-heading">
          <h2>Source & provenance</h2>
          <Fingerprint size={21} />
        </div>
        <dl className="provenance-list">
          <dt>Run</dt>
          <dd>{run.id}</dd>
          <dt>Checkpoint revision</dt>
          <dd>{run.revision}</dd>
          <dt>Transcript revision</dt>
          <dd>{run.transcriptRevision}</dd>
          <dt>Transcript provenance</dt>
          <dd>{run.provenance}</dd>
          <dt>Source SHA-256</dt>
          <dd className="mono">
            {run.local?.source.sha256 ?? "Unavailable — script-only example"}
          </dd>
          <dt>Source provenance</dt>
          <dd>
            {run.local?.source.provenance ??
              "Synthetic example provided by the AC conversation API."}
          </dd>
          {metadata && (
            <>
              <dt>Original source</dt>
              <dd>
                {metadata.source_codec} · {metadata.source_rate} Hz ·{" "}
                {metadata.source_channels} channels
              </dd>
              <dt>Decoded layout</dt>
              <dd>
                {metadata.decoded_rate} Hz · {metadata.decoded_channels}{" "}
                channels · {metadata.rows} native feature rows
              </dd>
              <dt>Track start</dt>
              <dd>
                {metadata.source_track_start_seconds ?? "Unavailable"} seconds
              </dd>
              <dt>Track time base</dt>
              <dd>{metadata.source_track_time_base ?? "Unavailable"}</dd>
              <dt>Clock mapping</dt>
              <dd>{metadata.source_mapping_status}</dd>
              <dt>Container/video sync</dt>
              <dd>Uncertified</dd>
            </>
          )}
        </dl>
        <div className="notice">
          <ShieldCheck size={18} />
          <span>
            Imported checkpoints are review data. Displaying a source
            fingerprint does not verify its authorship or accuracy.
          </span>
        </div>
      </section>
      <section className="panel">
        <p className="eyebrow">PROFILE INTEGRITY</p>
        <h2>The original weights stay visible.</h2>
        <div className="weight-comparison">
          <div>
            <strong>95</strong>
            <span>Source total</span>
          </div>
          <span>≠</span>
          <div>
            <strong>100</strong>
            <span>Declared total</span>
          </div>
        </div>
        <p className="muted">
          The difference remains unresolved. Numeric publication is withheld
          until an authorized resolution and validation gates pass.
        </p>
        <p className="small-text">
          Source weights: 15 · 20 · 15 · 10 · 10 · 15 · 5 · 5. Ethics is a hard
          constraint, not an extra five points.
        </p>
      </section>
      <section className="panel channel-panel">
        <div className="section-heading">
          <h2>Measurement channels</h2>
          <span className="pill subtle">Style-independent facts</span>
        </div>
        {!run.local?.channels.length ? (
          <Empty
            title="No signal channels available"
            text="This view does not infer audio measurements from a transcript. Import a checkpoint with source-bound channels to inspect its measurements."
          />
        ) : (
          run.local.channels.map((c, index) => (
            <ChannelGraph
              key={`${c.label}:${index}`}
              channel={c}
              duration={run.duration}
            />
          ))
        )}
        <p className="small-text">
          AudioAtlas and SignalLab retain distinct clocks and window profiles.
          Channel values are not substituted or averaged together. Null points
          remain gaps; display decimation is not a new measurement window.
        </p>
      </section>
    </div>
  );
}
function Review({
  run,
  selected,
  setSelected,
  lane,
  setLane,
  note,
  setNote,
  measurementSelection,
  setMeasurementSelection,
  audioSourceMatched,
}: {
  run: Run;
  selected: string;
  setSelected: (v: string) => void;
  lane: "contextual" | "measurements";
  setLane: (v: "contextual" | "measurements") => void;
  note: string;
  setNote: (v: string) => void;
  measurementSelection: { series: string; point: string };
  setMeasurementSelection: (v: { series: string; point: string }) => void;
  audioSourceMatched: boolean;
}) {
  const [receipt, setReceipt] = useState("");
  const [error, setError] = useState("");
  const [draftUrl, setDraftUrl] = useState<string | null>(null);
  const measurementLane =
    lane === "measurements" && Boolean(run.local?.channels.length);
  const series =
    measurementSelection.series !== ""
      ? run.local?.channels[Number(measurementSelection.series)]
      : undefined;
  const point =
    measurementSelection.point !== ""
      ? series?.points[Number(measurementSelection.point)]
      : undefined;
  useEffect(
    () => () => {
      if (draftUrl) URL.revokeObjectURL(draftUrl);
    },
    [draftUrl],
  );
  function prepare() {
    setError("");
    try {
      if (
        measurementLane &&
        (!series ||
          !point ||
          measurementSelection.series === "" ||
          measurementSelection.point === "")
      )
        throw new Error(
          "Choose an exact measurement point before preparing a proposal.",
        );
      if (!measurementLane && !run.segments.some((v) => v.id === selected))
        throw new Error(
          "Choose source evidence from the current transcript revision.",
        );
      const proposal =
        measurementLane && run.local
          ? createMeasurementProposal(
              run.local,
              Number(measurementSelection.series),
              Number(measurementSelection.point),
              note,
              audioSourceMatched,
            )
          : createReviewProposal(
              {
                run_id: run.id,
                revision: run.revision,
                transcript_revision: run.transcriptRevision,
              },
              lane,
              selected,
              note,
            );
      setDraftUrl(
        URL.createObjectURL(
          new Blob([JSON.stringify(proposal, null, 2)], {
            type: "application/json",
          }),
        ),
      );
      setReceipt(
        "Local proposal prepared. Nothing has been submitted or used for training.",
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The proposal could not be prepared.",
      );
    }
  }
  function invalidate() {
    setDraftUrl(null);
    setReceipt("");
  }
  const selectedSegment = run.segments.find((v) => v.id === selected);
  return (
    <div className="review-grid">
      <section className="panel">
        <p className="eyebrow">LOCAL REVIEW DRAFT</p>
        <h2>What deserves another look?</h2>
        <p className="muted">
          Choose the lane and exact evidence. An exported draft is a proposal;
          reviewer identity and assignment are checked by AC before any
          submission.
        </p>
        <div className="lane-options" role="group" aria-label="Review lane">
          <button
            type="button"
            aria-pressed={lane === "contextual"}
            className={lane === "contextual" ? "lane selected" : "lane"}
            onClick={() => {
              setLane("contextual");
              invalidate();
            }}
          >
            <span className="review-avatar">D</span>
            <span>
              <strong>Sales context</strong>
              <small>Dipak · contextual adjudication</small>
            </span>
            {lane === "contextual" && <Check size={17} />}
          </button>
          <button
            type="button"
            aria-pressed={lane === "measurements"}
            className={lane === "measurements" ? "lane selected" : "lane"}
            onClick={() => {
              setLane("measurements");
              invalidate();
            }}
          >
            <span className="review-avatar alternate">S</span>
            <span>
              <strong>Measurement & attribution</strong>
              <small>Suyash · technical validation</small>
            </span>
            {lane === "measurements" && <Check size={17} />}
          </button>
        </div>
        {measurementLane ? (
          <>
            <label className="field-label" htmlFor="measurement-series">
              Measurement series
            </label>
            <select
              id="measurement-series"
              value={measurementSelection.series}
              onChange={(e) => {
                setMeasurementSelection({ series: e.target.value, point: "" });
                invalidate();
              }}
            >
              <option value="">Choose a channel and measurement</option>
              {run.local?.channels.map((channel, index) => (
                <option key={`${channel.label}:${index}`} value={String(index)}>
                  {channel.label} · {channel.unit}
                </option>
              ))}
            </select>
            <label className="field-label" htmlFor="measurement-point">
              Exact measurement point
            </label>
            <select
              id="measurement-point"
              disabled={!series}
              value={measurementSelection.point}
              onChange={(e) => {
                setMeasurementSelection({
                  ...measurementSelection,
                  point: e.target.value,
                });
                invalidate();
              }}
            >
              <option value="">Choose a specific point to review</option>
              {series?.points.map((value, index) => (
                <option key={value.start_ms} value={String(index)}>
                  {value.start_ms} ms · {value.value ?? "Unavailable"}{" "}
                  {series.unit}
                </option>
              ))}
            </select>
            {series && point ? (
              <div className="measurement-anchor">
                <strong>{series.label}</strong>
                <p>
                  {point.start_ms} ms · {point.value ?? "Unavailable"}{" "}
                  {series.unit}
                </p>
                <p>
                  {series.clock} · Window {series.window_ms} ms · Hop{" "}
                  {series.hop_ms} ms
                  {series.display_stride
                    ? ` · Display stride ${series.display_stride}`
                    : ""}
                </p>
                <p>
                  {audioSourceMatched
                    ? "Original audio SHA-256 matched locally."
                    : "Checkpoint fingerprint only; original audio has not been matched."}{" "}
                  Feature binary and checkpoint authorship remain unverified.
                </p>
                <p>
                  Measurement revision{" "}
                  <span className="mono">
                    {run.local?.signal_metadata?.feature_sha256 ?? run.revision}
                  </span>
                </p>
              </div>
            ) : (
              <p className="small-text">
                Choose an exact point. This proposal will not invent transcript
                text or a speaker attribution.
              </p>
            )}
          </>
        ) : (
          <>
            <label className="field-label" htmlFor="review-evidence">
              Source evidence
            </label>
            <select
              id="review-evidence"
              value={selected}
              onChange={(e) => {
                setSelected(e.target.value);
                invalidate();
              }}
            >
              {run.segments.map((v) => (
                <option key={v.id} value={v.id}>
                  {time(v.start_ms)} · {v.speaker_id} · {v.id}
                </option>
              ))}
            </select>
            {selectedSegment && (
              <blockquote className="review-quote">
                {selectedSegment.text}
              </blockquote>
            )}
            {!selectedSegment && (
              <p className="small-text">
                Contextual review needs a source-bound transcript. Use the
                measurement lane to review this acoustic checkpoint.
              </p>
            )}
          </>
        )}
        <label className="field-label" htmlFor="review-note">
          Proposed correction
        </label>
        <textarea
          id="review-note"
          rows={6}
          maxLength={6000}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            invalidate();
          }}
          placeholder={
            lane === "contextual"
              ? "What context changes the interpretation? Cite the preceding or following evidence."
              : "What measurement or speaker attribution needs correction? Describe how to reproduce it."
          }
        />
        <div className="note-footer">
          <span>{note.length} / 6,000</span>
          <span>Held only in this tab</span>
        </div>
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        <div className="review-actions">
          <button
            className="primary-button"
            disabled={
              !(measurementLane ? Boolean(point) : Boolean(selectedSegment)) ||
              !note.trim()
            }
            onClick={prepare}
          >
            <FileJson size={17} />
            Prepare local proposal
          </button>
          {draftUrl && (
            <a
              className="secondary-button"
              href={draftUrl}
              download="sales-xray-review-proposal.json"
            >
              <ArrowDownToLine size={17} />
              Download JSON
            </a>
          )}
        </div>
        <p role="status" className="receipt">
          {receipt}
        </p>
      </section>
      <aside>
        <section className="panel">
          <div className="section-heading">
            <h3>Review, then improve</h3>
            <MessageSquareText size={19} />
          </div>
          <ol className="review-steps">
            <li>
              <span>01</span>
              <div>
                <strong>Preserve the evidence</strong>
                <p>
                  Keep the original run, transcript revision and precise span.
                </p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Adjudicate both lanes</strong>
                <p>
                  Sales interpretation and measurement validity are separate
                  decisions.
                </p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Reproduce and test</strong>
                <p>
                  Approved corrections become targeted fixtures for development
                  and calibration.
                </p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>Promote passing versions</strong>
                <p>
                  Holdout stays sealed. Feedback never triggers automatic
                  retraining.
                </p>
              </div>
            </li>
          </ol>
        </section>
        <div className="notice review-notice">
          <LockKeyhole size={18} />
          <span>
            Authenticated submission is unavailable in this local workspace.
            Exported proposals do not claim Dipak or Suyash submitted them.
          </span>
        </div>
      </aside>
    </div>
  );
}
