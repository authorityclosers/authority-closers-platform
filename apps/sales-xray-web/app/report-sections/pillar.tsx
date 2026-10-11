"use client";

import { Component, type ReactNode } from "react";

import { COMMON, PILLAR_COPY, PILLAR_IDS } from "../report-copy";
import type { DocumentReportData } from "../report-document-data";
import { BigPicture } from "./big-picture";
import { CallFlow } from "./call-flow";
import { DealStands } from "./deal";
import { Moments } from "./moments";
import { useStory, type Select } from "./shared";
import { Skills } from "./skills";
import { WorkedDidnt } from "./worked-didnt";
import styles from "./sections.module.css";

/** The six pillars in Dipak's order (spec 9 Oct, section 1). */
export const STORY_PILLARS = PILLAR_IDS.map((id) => ({
  id,
  label: PILLAR_COPY[id].label,
  short: PILLAR_COPY[id].short,
  subtitle: PILLAR_COPY[id].subtitle,
}));

function PillarUnavailable({ id }: { id: string }) {
  return (
    <div className={styles.pillar} data-report-pillar={id}>
      <p className={styles.gap} role="status">
        {COMMON.pillarFailed}
      </p>
    </div>
  );
}

/** One pillar's render error stays inside that pillar. */
class PillarBoundary extends Component<
  { id: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <PillarUnavailable id={this.props.id} />
    ) : (
      this.props.children
    );
  }
}

/** One pillar of the story; all six share the same model. */
export function StoryPillar({
  index,
  data,
  callId,
  onSelect,
  prospectControls,
  onOpenCoaching,
  liveReads = true,
}: {
  index: number;
  data: DocumentReportData;
  callId: string | null;
  onSelect?: Select;
  prospectControls?: ReactNode;
  onOpenCoaching?: () => void;
  /** False on fictional fixtures: nothing is read from the server. */
  liveReads?: boolean;
}) {
  const { model, people } = useStory(data, callId);
  const id = STORY_PILLARS[index].id;
  if (!model) return null;
  if (model === "unavailable") return <PillarUnavailable id={id} />;
  return (
    <PillarBoundary id={id}>
      <div className={styles.pillar} data-report-pillar={id}>
        {index === 0 ? (
          <BigPicture model={model} onSelect={onSelect} />
        ) : index === 1 ? (
          <CallFlow
            model={model}
            data={data}
            people={people}
            onSelect={onSelect}
          />
        ) : index === 2 ? (
          <WorkedDidnt
            model={model}
            onSelect={onSelect}
            preview={data.report?.preview}
            callId={liveReads ? callId : null}
          />
        ) : index === 3 ? (
          <Moments
            model={model}
            people={people}
            onSelect={onSelect}
            preview={data.report?.preview}
          />
        ) : index === 4 ? (
          <Skills model={model} onSelect={onSelect} />
        ) : (
          <DealStands
            model={model}
            people={people}
            onSelect={onSelect}
            prospectControls={prospectControls}
            onOpenCoaching={onOpenCoaching}
            guest={Boolean(data.report?.preview)}
          />
        )}
      </div>
    </PillarBoundary>
  );
}
