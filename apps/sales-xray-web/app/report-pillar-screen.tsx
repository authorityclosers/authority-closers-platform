"use client";

import type { ReactNode } from "react";

import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence } from "./report-contract";
import type { ReportPanel } from "./report-modes";
import { STORY_PILLARS, StoryPillar } from "./report-sections/pillar";
import type { ContextualSourcePlayback } from "./source-playback-context";

type Select = (evidence: ReportEvidence, title: string) => void;
type SelectContext = (
  playback: ContextualSourcePlayback,
  title: string,
) => void;

/** The six Report pillars (spec 9 Oct) as the Report view's sections. */
export function reportScreenPanels(
  data: DocumentReportData,
  onSelect?: Select,
  _onContext?: SelectContext,
  prospectControls?: ReactNode,
  options: { callId?: string | null; onOpenCoaching?: () => void } = {},
): ReportPanel[] {
  if (!data.report) return [];
  return STORY_PILLARS.map((pillar, index) => ({
    id: pillar.id,
    label: pillar.label,
    compactLabel: pillar.short,
    summary: pillar.subtitle,
    content: (
      <StoryPillar
        index={index}
        data={data}
        callId={options.callId ?? null}
        onSelect={onSelect}
        prospectControls={index === 5 ? prospectControls : undefined}
        onOpenCoaching={index === 5 ? options.onOpenCoaching : undefined}
      />
    ),
  }));
}
