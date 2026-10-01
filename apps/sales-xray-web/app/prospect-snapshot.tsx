"use client";

import { CircleHelp, Quote, ScanSearch } from "lucide-react";
import { useMemo } from "react";

import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { RichText } from "./report-entities";
import {
  Card,
  Clip,
  Empty,
  KitSection,
  Locked,
  Tag,
  useReportPeople,
} from "./report-kit";
import { ownWords } from "./sales-signals";
import styles from "./prospect-snapshot.module.css";

export type ProspectSnapshotProps = {
  report: SalesReport;
  onSelectEvidence: (evidence: ReportEvidence, title: string) => void;
  onUnlock?: () => void;
  callId?: string | null;
  transcript?: Transcript;
};

const EMPTY_TRANSCRIPT: Transcript = {
  source_sha256: "",
  revision: "",
  timebase_id: "1ms",
  duration_ms: 0,
  segments: [],
};

/**
 * What the prospect may have meant, kept apart from what they said: the
 * report's observation, their exact words with a play control, and the
 * possible meaning marked as a hypothesis to check. Then their own words
 * about their problems. This call only; nothing becomes a lasting profile.
 */
export function ProspectSnapshot({
  report,
  onSelectEvidence,
  onUnlock,
  callId = null,
  transcript = EMPTY_TRANSCRIPT,
}: ProspectSnapshotProps) {
  const people = useReportPeople(callId, transcript);
  const interpretations = report.overview?.prospect_interpretations ?? [];
  const preview = report.preview?.sections.prospect_interpretations;
  const hidden = preview?.hidden_count ?? 0;
  const said = useMemo(
    () => (people.roles ? ownWords(transcript, people.roles) : []),
    // roles comes from saved profiles; its two ids are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transcript, people.roles?.seller, people.roles?.prospect],
  );

  return (
    <div
      className={styles.snapshot}
      aria-label="Prospect snapshot"
      data-prospect-snapshot
    >
      <KitSection
        icon={ScanSearch}
        tone="hypothesis"
        title="What they may have meant"
        hint="Possible meanings to check on the next call. Not facts about the person."
        count={interpretations.length || undefined}
      >
        {interpretations.length ? (
          <div className={styles.cards}>
            {interpretations.map((item, index) => (
              <Card
                key={index}
                tone="hypothesis"
                index={index}
                className={styles.card}
              >
                <div data-prospect-index={index} className={styles.parts}>
                  <p className={styles.observation} data-prospect-part="source">
                    <small>What the report noticed</small>
                    <span>
                      <RichText text={item.source.text} />
                    </span>
                  </p>
                  <div data-prospect-part="verbatim" className={styles.words}>
                    {item.source.evidence.map((evidence) => (
                      <Clip
                        key={`${evidence.segment_id}-${evidence.start_ms}`}
                        evidence={evidence}
                        title={`Prospect signal ${index + 1}`}
                        onPlay={onSelectEvidence}
                        person={people.speakerOf(evidence)}
                      />
                    ))}
                  </div>
                  <div
                    className={styles.meaning}
                    data-prospect-part="hypothesis"
                    aria-label={`Possible concern hypothesis ${index + 1}`}
                  >
                    <Tag tone="hypothesis" icon={CircleHelp}>
                      A guess, not a fact
                    </Tag>
                    <p>
                      <b>It may mean:</b>{" "}
                      <span>
                        <RichText text={item.possible_concern} />
                      </span>
                    </p>
                    <small>Ask on the next call rather than assume.</small>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <div data-prospect-empty>
            <Empty icon={CircleHelp}>
              <b>No separate prospect interpretation.</b> Missing information
              does not establish anything about the prospect.
            </Empty>
          </div>
        )}
        <Locked
          count={hidden}
          noun="prospect interpretations"
          onUnlock={onUnlock}
          section="prospect_interpretations"
          visible={preview?.visible_count}
          total={preview?.total_count}
        />
      </KitSection>

      {people.roles ? (
        <KitSection
          icon={Quote}
          tone="info"
          title="In their own words"
          hint="What the prospect said about their situation, word for word."
          count={said.length}
          index={1}
        >
          {said.length ? (
            <div className={styles.cards}>
              {said.map((item) => (
                <Clip
                  key={`${item.segment.id}-${item.text}`}
                  evidence={{
                    segment_id: item.segment.id,
                    quote: item.text,
                    start_ms: item.segment.start_ms,
                    end_ms: item.segment.end_ms,
                  }}
                  title="Prospect’s own words"
                  onPlay={onSelectEvidence}
                  person={people.prospect}
                />
              ))}
            </div>
          ) : (
            <Empty icon={Quote}>
              The prospect did not describe a problem in their own words.
            </Empty>
          )}
        </KitSection>
      ) : null}

      <p className={styles.footnote}>
        This reflects this call only. It is not an ongoing profile of the
        prospect, and it cannot show what happened after the call.
      </p>
    </div>
  );
}
