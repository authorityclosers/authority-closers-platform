"use client";

import {
  ChartNoAxesColumnIncreasing,
  ListChecks,
  UserRound,
} from "lucide-react";
import { Component, useMemo, type ReactNode } from "react";

import { computeCallMetrics } from "../call-metrics";
import type { DocumentReportData } from "../report-document-data";
import {
  VERSION_1_LOOK,
  lookPointers,
  useReportLook,
  type ReportLook,
} from "../report-settings";
import { useStory, type Select } from "../report-sections/shared";
import { TargetArrow } from "./icons";
import {
  clock,
  outcomeFromStory,
  spelled,
  unscoredPointers,
  type XrayView,
} from "./model";
import { OverviewScore } from "./overview";
import { readStructure } from "./structure";
import { FinalOutcome } from "./outcome";
import { CallAnalysis, PointerProgress } from "./pointers";
import { ProspectPart } from "./prospect";
import styles from "./xray.module.css";

export type XrayPanel = {
  id: string;
  label: string;
  compactLabel: string;
  summary: string;
  icon: ReactNode;
  aside?: ReactNode;
  content: ReactNode;
};

const EMPTY_OUTCOME: XrayView["outcome"] = {
  kind: null,
  label: null,
  origin: null,
  detail: null,
  value: null,
  date: null,
  stages: [],
  reasons: [],
  objections: [],
  nextSteps: [],
  notes: [],
  suggested: null,
};

/** The Report's three parts for one call: measured numbers, the analysis' own words, the person's outcome. */
export function useXrayView(
  data: DocumentReportData,
  callId: string | null,
  illustration: XrayView | null,
): XrayView {
  const { model, people } = useStory(data, callId);
  const transcript = data.transcript;
  const seller = people.roles?.seller ?? null;
  const prospect = people.roles?.prospect ?? null;
  return useMemo(() => {
    if (illustration) return illustration;
    const story = model && model !== "unavailable" ? model : null;
    const metrics = transcript
      ? computeCallMetrics(transcript.segments, transcript.duration_ms || null)
      : null;
    const durationMs = metrics?.time_used_ms ?? 0;
    const you = seller ? metrics?.speakers[seller] : undefined;
    const them = prospect ? metrics?.speakers[prospect] : undefined;
    const pair = you && them;
    const talkTotal = pair ? you.talk_ms + them.talk_ms : 0;
    const yourShare =
      pair && talkTotal > 0
        ? Math.round((you.talk_ms / talkTotal) * 100)
        : null;
    const api = readStructure(
      data.report?.structure,
      transcript,
      seller,
      prospect,
    );
    return {
      illustrative: false,
      guest: Boolean(data.report?.preview),
      aiDraft: api?.aiDraft ?? false,
      scoring: api?.scoring ?? null,
      overview: {
        summary:
          story?.picture.summary ??
          api?.overview.summary ??
          (data.report?.summary
            ? { text: data.report.summary, sources: [] }
            : null),
        score: api?.overview.score ?? null,
        stats: api?.overview.stats ?? {
          duration:
            durationMs > 0
              ? { value: clock(durationMs), sub: spelled(durationMs) }
              : null,
          talk:
            yourShare !== null
              ? {
                  value: `${yourShare} : ${100 - yourShare}`,
                  sub: "Salesperson : Prospect",
                }
              : null,
          questions: pair
            ? {
                value: `${you.questions} : ${them.questions}`,
                sub: "Salesperson : Prospect",
              }
            : null,
          longest:
            you && you.longest_monologue_ms > 0
              ? {
                  value: clock(you.longest_monologue_ms),
                  sub: spelled(you.longest_monologue_ms),
                }
              : null,
        },
        strength: api?.overview.strength ?? story?.picture.strongest ?? null,
        improvement:
          api?.overview.improvement ?? story?.picture.concern ?? null,
      },
      pointers: api?.pointers ?? unscoredPointers(),
      outcome: {
        ...(story ? outcomeFromStory(story) : EMPTY_OUTCOME),
        ...(api?.outcome ?? {}),
      },
    };
  }, [illustration, model, transcript, seller, prospect, data.report]);
}

/** One part's render error stays inside that part. */
class PartBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <p className={`${styles.card} ${styles.empty}`} role="status">
        This part of the report couldn&rsquo;t be shown. The rest of the report
        is fine.
      </p>
    ) : (
      this.props.children
    );
  }
}

type PartProps = {
  data: DocumentReportData;
  callId: string | null;
  illustration: XrayView | null;
  onSelect?: Select;
};

function OverviewPart(props: PartProps) {
  const view = useXrayView(props.data, props.callId, props.illustration);
  return <OverviewScore view={view} onSelect={props.onSelect} />;
}

function AnalysisPart(props: PartProps) {
  const view = useXrayView(props.data, props.callId, props.illustration);
  return (
    <CallAnalysis
      pointers={view.pointers}
      illustrative={view.illustrative}
      aiDraft={view.aiDraft}
      scoring={view.scoring}
      onSelect={props.onSelect}
    />
  );
}

function ProspectSection(props: PartProps) {
  const view = useXrayView(props.data, props.callId, props.illustration);
  return (
    <ProspectPart
      data={props.data}
      callId={props.callId}
      view={view}
      onSelect={props.onSelect}
    />
  );
}

function AnalysisProgress(props: PartProps) {
  const view = useXrayView(props.data, props.callId, props.illustration);
  const look = useReportLook();
  return <PointerProgress pointers={lookPointers(view.pointers, look)} />;
}

function OutcomePart(props: PartProps) {
  const view = useXrayView(props.data, props.callId, props.illustration);
  return <FinalOutcome view={view} onSelect={props.onSelect} />;
}

/** The part head (images 2, 6 and 8): icon square, number and title, one line, optional aside. */
export function PartHead({
  number,
  icon,
  title,
  summary,
  aside,
  headingId,
}: {
  number: number;
  icon: ReactNode;
  title: string;
  summary: string;
  aside?: ReactNode;
  headingId: string;
}) {
  // Guided (version 1) explains each part; compact and scorecard just name it.
  const look = useReportLook();
  return (
    <header className={`${styles.xr} ${styles.partHead}`}>
      <div className={styles.head}>
        <span
          className={`${styles.square} ${styles.squareTone} ${styles.blue}`}
        >
          {icon}
        </span>
        <div className={styles.headText}>
          <h2 id={headingId} tabIndex={-1} className={styles.headTitle}>
            {number}. {title}
          </h2>
          {look.style === "guided" ? (
            <p className={styles.headSub}>{summary}</p>
          ) : null}
        </div>
      </div>
      {aside}
    </header>
  );
}

export function xrayReportPanels(
  data: DocumentReportData,
  onSelect?: Select,
  options: {
    callId?: string | null;
    illustration?: XrayView | null;
    /** The report settings version's look (names and counts follow it). */
    look?: ReportLook;
  } = {},
): XrayPanel[] {
  if (!data.report) return [];
  const look = options.look ?? VERSION_1_LOOK;
  const props: PartProps = {
    data,
    callId: options.callId ?? null,
    illustration: options.illustration ?? null,
    onSelect,
  };
  return [
    {
      id: "overview",
      label: look.scores ? "Overview & Score" : "Overview",
      compactLabel: "Overview",
      summary: "A quick snapshot of the call.",
      icon: <ChartNoAxesColumnIncreasing />,
      content: (
        <PartBoundary>
          <OverviewPart {...props} />
        </PartBoundary>
      ),
    },
    {
      id: "analysis",
      label: "Detailed Call Analysis",
      compactLabel: "Analysis",
      summary: `Analysis based on ${lookPointers(unscoredPointers(), look).length} key sales conversation pointers. Expand each one to see detailed feedback, examples, and recommendations.`,
      icon: <ListChecks />,
      aside: <AnalysisProgress {...props} />,
      content: (
        <PartBoundary>
          <AnalysisPart {...props} />
        </PartBoundary>
      ),
    },
    {
      id: "outcome",
      label: "Final Call Outcome",
      compactLabel: "Outcome",
      summary: "Here’s what happened commercially and what’s next.",
      icon: <TargetArrow />,
      content: (
        <PartBoundary>
          <OutcomePart {...props} />
        </PartBoundary>
      ),
    },
  ];
}

/**
 * Prospect's Information as its own top tab (owner, 19 Oct: Report | Prospect |
 * Coaching), not a part of the Report. Guest previews and illustrations have
 * no saved prospect behind them.
 */
export function prospectPanel(
  data: DocumentReportData,
  onSelect?: Select,
  options: { callId?: string | null } = {},
): XrayPanel | null {
  if (!data.report || data.report.preview) return null;
  return {
    id: "prospect-information",
    label: "Prospect’s Information",
    compactLabel: "Prospect",
    summary:
      "Who they are, what they want, what’s stopping them and what happens next.",
    icon: <UserRound />,
    content: (
      <PartBoundary>
        <ProspectSection
          data={data}
          callId={options.callId ?? null}
          illustration={null}
          onSelect={onSelect}
        />
      </PartBoundary>
    ),
  };
}
