"use client";

import {
  ArrowRight,
  CalendarClock,
  Flag,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

import { formatClock } from "../../../lightbox/time";
import type { ReportEvidence } from "../../../report-contract";
import { reportStoryModel } from "../../../report-story-model";
import {
  speechFromTranscript,
  splitPair,
} from "../../../report-visuals/timeline";
import {
  CallTimeline,
  ChangeSteps,
  CommitmentQuality,
  FactList,
  FindingCard,
  InferredTag,
  MetricRow,
  MomentCard,
  OUTCOME_TONE,
  OutcomeBadge,
  PillarHeading,
  PlayChip,
  Quote,
  ShareDial,
  SkillRow,
  SkillStateMark,
  MomentTag,
  SplitBar,
  StoryCard,
  SummaryStrip,
  type MetricItem,
} from "../../../report-visuals/visuals";
import { AMIT_SPEAKERS, amitReport, amitTranscript } from "../story/amit-call";
import styles from "./visuals-gallery.module.css";

const NAMES = {
  [AMIT_SPEAKERS.seller]: "Arjun",
  [AMIT_SPEAKERS.prospect]: "Amit Sharma",
};

/**
 * The Report's building blocks composed on the spec's own fictional call
 * (Amit Sharma, 25:08), so the look can be judged on dev. Fixture only: no
 * account, recording or provider call; Play only says what it would play.
 */
export function VisualsGallery() {
  const [said, setSaid] = useState(
    "Fictional fixture: Play shows what it would play.",
  );
  const select = (evidence: ReportEvidence, title: string) =>
    setSaid(
      `Would play ${formatClock(evidence.start_ms)}–${formatClock(evidence.end_ms)} · ${title}`,
    );
  const model = useMemo(
    () =>
      reportStoryModel(amitReport, amitTranscript, {
        roles: {
          seller: AMIT_SPEAKERS.seller,
          prospect: AMIT_SPEAKERS.prospect,
        },
      }),
    [],
  );
  const speech = useMemo(
    () =>
      speechFromTranscript(amitTranscript, {
        top: AMIT_SPEAKERS.seller,
        bottom: AMIT_SPEAKERS.prospect,
      }),
    [],
  );
  const speakerOf = (source: ReportEvidence) => {
    const id = amitTranscript.segments.find(
      (s) => s.id === source.segment_id,
    )?.speaker_id;
    if (!id || !NAMES[id]) return null;
    return {
      name: NAMES[id],
      role:
        id === AMIT_SPEAKERS.seller ? ("you" as const) : ("prospect" as const),
    };
  };
  const { picture, flow, deal } = model;
  const turn = flow.change?.turn.sources[0];

  const metrics: MetricItem[] = flow.metrics.map((metric) => {
    const pair = splitPair(metric.value);
    if (pair && metric.label === "Talk share")
      return {
        label: metric.label,
        value: metric.value,
        visual: (
          <SplitBar
            unit="%"
            parts={[
              { label: "You", value: pair[0] },
              { label: "Amit", value: pair[1] },
            ]}
          />
        ),
      };
    if (pair && metric.label === "Questions asked")
      return {
        label: metric.label,
        value: metric.value,
        visual: (
          <SplitBar
            parts={[
              { label: "You", value: pair[0] },
              { label: "Amit", value: pair[1] },
            ]}
          />
        ),
      };
    return { label: metric.label, value: metric.value, note: metric.note };
  });

  return (
    <main className={styles.page}>
      <p className={styles.banner}>
        Report visuals · fictional Amit Sharma call ·{" "}
        <span role="status">{said}</span>
      </p>

      <header className={styles.callHead}>
        <h1>Amit Sharma · discovery call</h1>
        <p>25:08 · English · Arjun with Amit Sharma</p>
      </header>

      {/* 1 */}
      <section className={styles.pillar} aria-labelledby="p1">
        <PillarHeading
          index={1}
          id="p1"
          title="The Big Picture"
          subtitle="Understand the call in seconds."
        />
        <StoryCard emphasis>
          <OutcomeBadge
            status={picture.outcome.status}
            origin={picture.outcome.origin}
            size="lg"
          />
          {picture.summary ? (
            <p className={styles.lead}>{picture.summary.text}</p>
          ) : null}
          {picture.assessment ? (
            <p className={styles.leadMore}>{picture.assessment}</p>
          ) : null}
        </StoryCard>
        <div className={styles.trio}>
          {picture.influence ? (
            <StoryCard
              label="What most affected this call"
              tone="accent"
              icon={Sparkles}
            >
              <p>{picture.influence.text}</p>
              <PlayChip
                source={picture.influence.sources[0]}
                title="What most affected this call"
                onSelect={select}
              />
            </StoryCard>
          ) : null}
          {picture.strongest ? (
            <StoryCard label="Strongest part" tone="good" icon={Flag}>
              <p>{picture.strongest.text}</p>
              <PlayChip
                source={picture.strongest.sources[0]}
                title="Strongest part"
                onSelect={select}
              />
            </StoryCard>
          ) : null}
          {picture.concern ? (
            <StoryCard label="Biggest concern" tone="warn" icon={TriangleAlert}>
              <p>{picture.concern.text}</p>
              <PlayChip
                source={picture.concern.sources[0]}
                title="Biggest concern"
                onSelect={select}
              />
            </StoryCard>
          ) : null}
        </div>
        {picture.nextStep ? (
          <StoryCard
            label="Next step"
            tone="accent"
            icon={CalendarClock}
            aside={
              <PlayChip
                source={picture.nextStep.sources.at(-1)}
                title="Next step"
                onSelect={select}
              />
            }
          >
            <p className={styles.nextStep}>{picture.nextStep.text}</p>
          </StoryCard>
        ) : null}
      </section>

      {/* 2 */}
      <section className={styles.pillar} aria-labelledby="p2">
        <PillarHeading
          index={2}
          id="p2"
          title="How the Call Played Out"
          subtitle="See how the conversation moved."
        />
        <MetricRow items={metrics} />
        <p className={styles.note}>
          Numbers describe the call. What they mean depends on the moment.
        </p>
        <StoryCard>
          <CallTimeline
            durationMs={amitTranscript.duration_ms}
            speech={speech}
            names={{ top: "You (Arjun)", bottom: "Amit Sharma" }}
            phases={flow.phases}
            moments={model.moments.map((moment) => ({
              key: moment.key,
              kind: moment.kind,
              title: moment.title,
              at_ms: moment.source.start_ms,
              source: moment.source,
            }))}
            change={
              turn ? { at_ms: turn.start_ms, label: "The call changed" } : null
            }
            onSelect={select}
          />
        </StoryCard>
        {flow.change && turn ? (
          <StoryCard
            label={`The call changed here · ${formatClock(turn.start_ms)}`}
            tone="accent"
            aside={
              <PlayChip
                source={turn}
                title="The call changed here"
                onSelect={select}
                label="Play"
              />
            }
          >
            <Quote text={turn.quote} speaker={speakerOf(turn)} size="lg" />
            <ChangeSteps
              before={<p>{flow.change.before.text}</p>}
              turn={<p>{flow.change.turn.text}</p>}
              after={<p>{flow.change.after.text}</p>}
            />
            {flow.change.effect ? (
              <p className={styles.effect}>
                <InferredTag /> {flow.change.effect}
              </p>
            ) : null}
          </StoryCard>
        ) : null}
      </section>

      {/* 3 */}
      <section className={styles.pillar} aria-labelledby="p3">
        <PillarHeading
          index={3}
          id="p3"
          title="What Worked — & What Didn't"
          subtitle="See what helped the conversation and what made it harder."
        />
        <div className={styles.columns}>
          <div className={styles.column}>
            <h3 className={styles.columnHead}>What worked</h3>
            {model.worked.map((item, index) => (
              <FindingCard
                key={index}
                tone="good"
                title={item.title}
                play={
                  <PlayChip
                    source={item.what.sources[0]}
                    title={item.title}
                    onSelect={select}
                  />
                }
                whyLabel="Why it helped"
                why={item.why ? <p>{item.why.text}</p> : null}
              >
                <p>{item.what.text}</p>
              </FindingCard>
            ))}
          </div>
          <div className={styles.column}>
            <h3 className={styles.columnHead}>What didn&apos;t</h3>
            {model.didnt.map((item, index) => (
              <FindingCard
                key={index}
                tone="warn"
                title={item.title}
                play={
                  <PlayChip
                    source={item.what.sources[0]}
                    title={item.title}
                    onSelect={select}
                  />
                }
                whyLabel="What it affected"
                why={item.why ? <p>{item.why.text}</p> : null}
              >
                <p>{item.what.text}</p>
              </FindingCard>
            ))}
          </div>
        </div>
      </section>

      {/* 4 */}
      <section className={styles.pillar} aria-labelledby="p4">
        <PillarHeading
          index={4}
          id="p4"
          title="Moments That Mattered"
          subtitle="Replay the moments that changed the conversation."
        />
        <div className={styles.stack}>
          {model.topMoments.map((moment) => (
            <MomentCard
              key={moment.key}
              kind={moment.kind}
              atMs={moment.source.start_ms}
              title={moment.title}
              play={
                <PlayChip
                  source={moment.source}
                  title={moment.title}
                  onSelect={select}
                  label="Play"
                  range
                />
              }
              quote={
                <Quote
                  text={moment.source.quote}
                  speaker={speakerOf(moment.source)}
                />
              }
              details={[
                ...(moment.movedToward
                  ? [
                      {
                        label: "You moved toward",
                        text: moment.movedToward.text,
                      },
                    ]
                  : []),
                ...(moment.couldExplore
                  ? [{ label: "What was missed", text: moment.couldExplore }]
                  : []),
                ...(moment.why
                  ? [{ label: "Why it mattered", text: moment.why.text }]
                  : []),
              ]}
            />
          ))}
        </div>
      </section>

      {/* 5 */}
      <section className={styles.pillar} aria-labelledby="p5">
        <PillarHeading
          index={5}
          id="p5"
          title="Your Skills on This Call"
          subtitle="See how your sales skills showed up in this conversation."
        />
        <div className={styles.skills}>
          {model.skills.map((skill) => (
            <SkillRow
              key={skill.id}
              name={skill.short}
              title={skill.label}
              state={skill.state}
            >
              <p>
                {skill.observation ??
                  "This report does not establish a state for this skill."}
              </p>
              {skill.sources.length ? (
                <p className={styles.plays}>
                  <span>Evidence</span>
                  {skill.sources.slice(0, 4).map((source, index) => (
                    <PlayChip
                      key={index}
                      source={source}
                      title={skill.label}
                      onSelect={select}
                    />
                  ))}
                </p>
              ) : null}
            </SkillRow>
          ))}
        </div>
      </section>

      {/* 6 */}
      <section className={styles.pillar} aria-labelledby="p6">
        <PillarHeading
          index={6}
          id="p6"
          title="Where the Deal Stands"
          subtitle="Know exactly what happens next."
        />
        <div className={styles.dealHead}>
          <OutcomeBadge
            status={deal.outcome.status}
            origin={deal.outcome.origin}
          />
          {deal.quality ? <CommitmentQuality quality={deal.quality} /> : null}
        </div>
        <FactList
          items={[
            ...(deal.position
              ? [
                  {
                    label: "Prospect's position",
                    value: (
                      <LineWithPlay
                        text={deal.position.text}
                        source={deal.position.sources.at(-1)}
                        onSelect={select}
                      />
                    ),
                  },
                ]
              : []),
            ...(deal.blocker
              ? [
                  {
                    label: "Possible blocker",
                    extra: <InferredTag />,
                    value: (
                      <LineWithPlay
                        text={deal.blocker.text}
                        source={deal.blocker.sources.at(-1)}
                        onSelect={select}
                      />
                    ),
                  },
                ]
              : []),
            ...deal.prospectCommitments.map((line) => ({
              label: "Amit agreed to",
              value: (
                <LineWithPlay
                  text={line.text}
                  source={line.sources.at(-1)}
                  onSelect={select}
                />
              ),
            })),
            ...deal.sellerCommitments.map((line) => ({
              label: "You agreed to",
              value: (
                <LineWithPlay
                  text={line.text}
                  source={line.sources.at(-1)}
                  onSelect={select}
                />
              ),
            })),
            ...(deal.nextEvent
              ? [
                  {
                    label: "Next event",
                    value: (
                      <LineWithPlay
                        text={deal.nextEvent.text}
                        source={deal.nextEvent.sources.at(-1)}
                        onSelect={select}
                      />
                    ),
                  },
                ]
              : []),
            ...(deal.unclear.length
              ? [
                  {
                    label: "Still needs to become clear",
                    value: (
                      <ul className={styles.bullets}>
                        {deal.unclear.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ),
                  },
                ]
              : []),
            ...(deal.action
              ? [{ label: "Recommended next move", value: deal.action }]
              : []),
          ]}
        />
        <div className={styles.ctas}>
          <a className={styles.cta} href="#p6">
            View Prospect&apos;s Information{" "}
            <ArrowRight size={14} aria-hidden="true" />
          </a>
          <a className={styles.ctaQuiet} href="#p6">
            Coaching for this call <ArrowRight size={14} aria-hidden="true" />
          </a>
        </div>
        <SummaryStrip
          cells={[
            {
              label: "Call outcome",
              value: deal.outcome.status ?? "Not recorded",
              tone: deal.outcome.status
                ? (OUTCOME_TONE[deal.outcome.status] ?? "neutral")
                : "neutral",
            },
            { label: "Strongest part", value: model.worked[0]?.title ?? "—" },
            { label: "Biggest issue", value: model.didnt[0]?.title ?? "—" },
            {
              label: "Most important moment",
              value: model.topMoments[0]
                ? `${model.topMoments[0].kind} · ${formatClock(model.topMoments[0].source.start_ms)}`
                : "—",
            },
            { label: "Next event", value: deal.nextEvent?.text ?? "—" },
          ]}
        />
      </section>
      <EdgeCases onSelect={select} />
    </main>
  );
}

const minute = (m: number, sec = 0) => (m * 60 + sec) * 1000;

/** Fictional stress data: many short stages, many moments, Hindi words. */
const EDGE_PHASES = [
  ["Opening", 0],
  ["Business Context", 1.5],
  ["Problems & Goals", 4],
  ["Decision & Next Step", 6.2],
  ["Price", 7],
  ["Partner Objection", 7.6],
  ["Program Discussion", 9],
  ["Decision & Next Step", 15],
  ["Close", 16.2],
].map(([label, at], index, all) => ({
  label: label as string,
  start_ms: minute(at as number),
  end_ms: minute((all[index + 1]?.[1] as number) ?? 17),
}));

const EDGE_KINDS = [
  "Strong Moment",
  "Turning Point",
  "Buying Signal",
  "Important Miss",
  "Objection",
  "Price Moment",
  "Decision Moment",
  "Trust Moment",
  "Commitment",
  "Risk",
  "Worth Replaying",
];

const hindi = {
  segment_id: "h1",
  quote:
    "सच कहूँ तो कीमत ठीक है, पर मुझे अपने पार्टनर से एक बार बात करनी होगी।",
  start_ms: minute(7, 40),
  end_ms: minute(7, 52),
};

function EdgeCases({
  onSelect,
}: {
  onSelect: (evidence: ReportEvidence, title: string) => void;
}) {
  // A monologue-heavy seller: long turns, short replies (fictional).
  const speech = {
    top: Array.from({ length: 34 }, (_, index) => ({
      start_ms: index * 30_000,
      end_ms: index * 30_000 + 24_000,
    })),
    bottom: Array.from({ length: 34 }, (_, index) => ({
      start_ms: index * 30_000 + 24_500,
      end_ms: index * 30_000 + 29_000,
    })),
  };
  return (
    <section className={styles.pillar} aria-labelledby="edge">
      <PillarHeading
        index={7}
        id="edge"
        title="Edge cases"
        subtitle="Not a pillar: how the blocks hold up with messy, long and Hindi content."
      />
      <StoryCard label="Nine short stages, eleven moments">
        <CallTimeline
          durationMs={minute(17)}
          speech={speech}
          names={{ top: "राहुल (You)", bottom: "समीर जोशी" }}
          phases={EDGE_PHASES}
          moments={EDGE_KINDS.map((kind, index) => ({
            key: kind,
            kind,
            title: `${kind} example`,
            at_ms: minute(0.6 + index * 1.5),
            source: { ...hindi, start_ms: minute(0.6 + index * 1.5) },
          }))}
          change={{ at_ms: minute(7, 2), label: "The call changed" }}
          onSelect={onSelect}
        />
      </StoryCard>
      <StoryCard label="One speaker only, no stages">
        <CallTimeline
          durationMs={minute(3)}
          speech={{
            top: [{ start_ms: 0, end_ms: minute(2, 50) }],
            bottom: [],
          }}
          names={{ top: "Voice note", bottom: "" }}
        />
      </StoryCard>
      <div className={styles.trio}>
        <StoryCard label="Hindi quote">
          <Quote
            text={hindi.quote}
            speaker={{ name: "समीर जोशी", role: "prospect" }}
            source={hindi}
            onSelect={onSelect}
          />
        </StoryCard>
        <StoryCard label="Every outcome">
          <div className={styles.wrapRow}>
            {Object.keys(OUTCOME_TONE).map((status) => (
              <OutcomeBadge key={status} status={status} />
            ))}
            <OutcomeBadge status={null} />
          </div>
        </StoryCard>
        <StoryCard label="Every skill state and commitment">
          <div className={styles.stackTight}>
            {[
              "Strongly Demonstrated",
              "Observed",
              "Needs Attention",
              "Not Enough Evidence",
              "Not Applicable",
              null,
            ].map((state) => (
              <SkillStateMark key={String(state)} state={state} />
            ))}
            {(["Clear", "Soft", "Unclear"] as const).map((quality) => (
              <CommitmentQuality key={quality} quality={quality} />
            ))}
          </div>
        </StoryCard>
      </div>
      <StoryCard label="Every moment kind">
        <div className={styles.wrapRow}>
          {EDGE_KINDS.map((kind, index) => (
            <MomentTag key={kind} kind={kind} atMs={minute(index)} />
          ))}
        </div>
      </StoryCard>
      <MetricRow
        items={[
          { label: "Call length", value: "1:02:41" },
          {
            label: "Talk share",
            value: "88 : 12",
            visual: (
              <ShareDial
                value={88}
                total={100}
                label="You talked 88% of the time"
              />
            ),
          },
          { label: "Questions asked", value: "0 : 14" },
          { label: "Longest seller turn", value: "11:07" },
          { label: "Talk-overs", value: "27" },
        ]}
      />
    </section>
  );
}

function LineWithPlay({
  text,
  source,
  onSelect,
}: {
  text: string;
  source: ReportEvidence | undefined;
  onSelect: (evidence: ReportEvidence, title: string) => void;
}) {
  return (
    <>
      {text} <PlayChip source={source} title={text} onSelect={onSelect} />
    </>
  );
}
