"use client";

import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  ChevronDown,
  CircleDot,
  Flag,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { formatClock } from "./lightbox/time";
import type { DocumentReportData } from "./report-document-data";
import type { ReportEvidence, Transcript } from "./report-contract";
import { RichText } from "./report-entities";
import { useReportPeople, type Person } from "./report-kit";
import {
  reportStoryModel,
  type Item,
  type Line,
  type Moment,
  type MomentKind,
  type Outcome,
  type SkillState,
  type StoryModel,
} from "./report-story-model";
import { ClipPlayIcon, ClipPlayState } from "./source-waveform";
import styles from "./report-story-view.module.css";

export type Select = (evidence: ReportEvidence, title: string) => void;

/** Calm prose: words only, no coloured entity chips inside the story. */
const NO_CHIPS = [] as const;
function Text({ text }: { text: string }) {
  return <RichText text={text} kinds={NO_CHIPS} />;
}

export const STORY_PILLARS = [
  {
    id: "overview",
    label: "The Big Picture",
    short: "Big Picture",
    subtitle: "Understand the call in seconds.",
  },
  {
    id: "coaching",
    label: "How the Call Played Out",
    short: "Call Flow",
    subtitle: "See how the conversation moved.",
  },
  {
    id: "moments",
    label: "What Worked — & What Didn't",
    short: "Worked / Didn't",
    subtitle: "See what helped the conversation and what made it harder.",
  },
  {
    id: "missed",
    label: "Moments That Mattered",
    short: "Moments",
    subtitle: "Replay the moments that changed the conversation.",
  },
  {
    id: "skills",
    label: "Your Skills on This Call",
    short: "Skills",
    subtitle: "See how your sales skills showed up in this conversation.",
  },
  {
    id: "facts",
    label: "Where the Deal Stands",
    short: "Deal",
    subtitle: "Know exactly what happens next.",
  },
] as const;

const EMPTY_TRANSCRIPT: Transcript = {
  revision: "",
  timebase_id: "",
  duration_ms: 0,
  segments: [],
} as unknown as Transcript;

/** One model per report and speaker roles, shared by all six pillars. */
function useStory(data: DocumentReportData, callId: string | null) {
  const transcript = data.transcript ?? EMPTY_TRANSCRIPT;
  const people = useReportPeople(callId, transcript);
  const seller = people.roles?.seller ?? null;
  const prospect = people.roles?.prospect ?? null;
  const model = useMemo(
    () =>
      data.report
        ? reportStoryModel(data.report, data.transcript, {
            roles: { seller, prospect },
          })
        : null,
    [data.report, data.transcript, seller, prospect],
  );
  return { model, people };
}

function Play({
  source,
  title,
  onSelect,
  label,
}: {
  source: ReportEvidence | undefined;
  title: string;
  onSelect?: Select;
  label?: string;
}) {
  if (!source) return null;
  const at = formatClock(source.start_ms);
  if (!onSelect) return <span className={styles.time}>{at}</span>;
  return (
    <ClipPlayState startMs={source.start_ms} endMs={source.end_ms}>
      {(playing) => (
        <button
          type="button"
          className={styles.play}
          aria-pressed={playing}
          aria-label={`${playing ? "Pause" : "Play"} ${at}: ${title}`}
          onClick={() => onSelect(source, title)}
        >
          <ClipPlayIcon playing={playing} size={9} />
          {label ? `${label} · ` : ""}
          {at}
        </button>
      )}
    </ClipPlayState>
  );
}

function Inferred() {
  return (
    <span
      className={styles.inferred}
      title="The analysis suggests this; it is not confirmed."
    >
      Inferred
    </span>
  );
}

function Quote({
  source,
  person,
}: {
  source: ReportEvidence;
  person: Person | null;
}) {
  return (
    <blockquote className={styles.quote}>
      {person ? <cite>{person.name}</cite> : null}
      <span>
        “<Text text={source.quote} />”
      </span>
    </blockquote>
  );
}

function Missing({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <p className={styles.missing}>
      <span>Not in this report:</span> {items.join(" · ")}
    </p>
  );
}

const OUTCOME_TONE: Record<string, string> = {
  Won: "good",
  "Follow-up Set": "good",
  "Meeting Booked": "good",
  "Decision Pending": "warn",
  Deferred: "warn",
  "Still Open": "warn",
  "No Clear Next Step": "bad",
  Lost: "bad",
  Disqualified: "neutral",
};

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return (
    <span className={styles.outcomeRow}>
      <span
        className={styles.outcome}
        data-tone={outcome.status ? OUTCOME_TONE[outcome.status] : "neutral"}
      >
        <CircleDot size={14} aria-hidden="true" />
        {outcome.status ?? "Outcome not recorded"}
      </span>
      <span className={styles.origin}>
        {outcome.origin === "person"
          ? "Recorded by your team"
          : outcome.origin === "call"
            ? "As heard on the call"
            : "Only a person records won or lost"}
      </span>
    </span>
  );
}

function Callout({
  label,
  line,
  tone,
  icon,
  onSelect,
}: {
  label: string;
  line: Line | null;
  tone: "good" | "warn" | "accent";
  icon: ReactNode;
  onSelect?: Select;
}) {
  if (!line) return null;
  return (
    <div className={styles.callout} data-tone={tone}>
      <p className={styles.calloutLabel}>
        {icon}
        {label}
        {line.inferred ? <Inferred /> : null}
      </p>
      <p className={styles.calloutText}>
        <Text text={line.text} />
      </p>
      <Play source={line.sources[0]} title={label} onSelect={onSelect} />
    </div>
  );
}

function BigPicture({
  model,
  onSelect,
}: {
  model: StoryModel;
  onSelect?: Select;
}) {
  const { picture } = model;
  const nextStepRepeats =
    picture.nextStep && picture.nextStep.text === picture.outcome.detail?.text;
  return (
    <>
      <div className={styles.hero}>
        <OutcomeBadge outcome={picture.outcome} />
        {picture.summary ? (
          <p className={styles.lead}>
            <Text text={picture.summary.text} />
          </p>
        ) : null}
        {picture.assessment ? (
          <p className={styles.leadMore}>
            <Text text={picture.assessment} />
          </p>
        ) : null}
        {picture.outcome.detail && !nextStepRepeats ? (
          <p className={styles.outcomeDetail}>
            <Text text={picture.outcome.detail.text} />{" "}
            <Play
              source={picture.outcome.detail.sources[0]}
              title="Call outcome"
              onSelect={onSelect}
            />
          </p>
        ) : null}
      </div>
      <Callout
        label="What most affected this call"
        line={picture.influence}
        tone="accent"
        icon={<Sparkles size={14} aria-hidden="true" />}
        onSelect={onSelect}
      />
      {picture.strongest || picture.concern ? (
        <div className={styles.pair}>
          <Callout
            label="Strongest part"
            line={picture.strongest}
            tone="good"
            icon={<Flag size={14} aria-hidden="true" />}
            onSelect={onSelect}
          />
          <Callout
            label="Biggest concern"
            line={picture.concern}
            tone="warn"
            icon={<TriangleAlert size={14} aria-hidden="true" />}
            onSelect={onSelect}
          />
        </div>
      ) : null}
      {picture.nextStep ? (
        <div className={styles.nextStep}>
          <CalendarClock size={16} aria-hidden="true" />
          <div>
            <p className={styles.calloutLabel}>Next step</p>
            <p className={styles.calloutText}>
              <Text text={picture.nextStep.text} />
            </p>
          </div>
          <Play
            source={picture.nextStep.sources.at(-1)}
            title="Next step"
            onSelect={onSelect}
          />
        </div>
      ) : null}
      <Missing items={model.missing[0]} />
    </>
  );
}

function SpeakerStrip({
  transcript,
  people,
  moments,
}: {
  transcript: Transcript;
  people: ReturnType<typeof useReportPeople>;
  moments: Moment[];
}) {
  const duration = transcript.duration_ms;
  const lanes = useMemo(() => {
    const totals = new Map<string, number>();
    for (const segment of transcript.segments)
      if (segment.speaker_id)
        totals.set(
          segment.speaker_id,
          (totals.get(segment.speaker_id) ?? 0) +
            segment.end_ms -
            segment.start_ms,
        );
    return [...totals.keys()]
      .sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0))
      .slice(0, 3);
  }, [transcript]);
  if (!duration || !lanes.length) return null;
  const pct = (ms: number) => `${Math.min(100, (ms / duration) * 100)}%`;
  return (
    <figure className={styles.strip} aria-label="Who spoke when">
      {lanes.map((speaker, lane) => (
        <div key={speaker} className={styles.lane}>
          <span className={styles.laneName}>
            {people.person(speaker)?.name ?? `Speaker ${lane + 1}`}
          </span>
          <span className={styles.track} data-lane={lane}>
            {transcript.segments
              .filter((segment) => segment.speaker_id === speaker)
              .map((segment) => (
                <i
                  key={segment.id}
                  style={{
                    left: pct(segment.start_ms),
                    width: pct(Math.max(segment.end_ms - segment.start_ms, 1)),
                  }}
                />
              ))}
          </span>
        </div>
      ))}
      <div className={styles.lane} aria-hidden="true">
        <span className={styles.laneName}>Moments</span>
        <span className={styles.track} data-markers>
          {moments.map((moment) => (
            <b
              key={moment.key}
              data-kind={KIND_TONE[moment.kind]}
              style={{ left: pct(moment.source.start_ms) }}
              title={`${moment.kind} · ${formatClock(moment.source.start_ms)}`}
            />
          ))}
        </span>
      </div>
      <figcaption className={styles.axis}>
        <span>00:00</span>
        <span>{formatClock(duration / 2)}</span>
        <span>{formatClock(duration)}</span>
      </figcaption>
    </figure>
  );
}

function CallFlow({
  model,
  data,
  people,
  onSelect,
}: {
  model: StoryModel;
  data: DocumentReportData;
  people: ReturnType<typeof useReportPeople>;
  onSelect?: Select;
}) {
  const { flow } = model;
  const turn = flow.change?.turn.sources[0];
  return (
    <>
      {/* The report header moves its interactive call map in here. */}
      <div className={styles.mapSlot} data-report-map-slot />
      <div className={styles.fallback}>
        {flow.metrics.length ? (
          <dl className={styles.metrics}>
            {flow.metrics.map((metric) => (
              <div key={metric.label}>
                <dd>{metric.value}</dd>
                <dt>
                  {metric.label}
                  {metric.note ? <small>{metric.note}</small> : null}
                </dt>
              </div>
            ))}
          </dl>
        ) : null}
        {flow.metrics.length ? (
          <p className={styles.note}>
            Numbers describe the call. What they mean depends on the moment.
          </p>
        ) : null}
        {!flow.phases && data.transcript ? (
          <SpeakerStrip
            transcript={data.transcript}
            people={people}
            moments={model.topMoments}
          />
        ) : null}
      </div>
      {flow.phases ? (
        <ol className={styles.phases} aria-label="Conversation stages">
          {flow.phases.map((phase, index) => (
            <li
              key={`${phase.label}-${index}`}
              data-phase={index % 5}
              style={{ flexGrow: Math.max(1, phase.end_ms - phase.start_ms) }}
            >
              <strong>{phase.label}</strong>
              <span>
                {formatClock(phase.start_ms)}–{formatClock(phase.end_ms)}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {flow.change && turn ? (
        <div className={styles.change}>
          <p className={styles.changeHead}>
            The call changed here · {formatClock(turn.start_ms)}
            <Play
              source={turn}
              title="The call changed here"
              onSelect={onSelect}
            />
          </p>
          <Quote source={turn} person={people.speakerOf(turn)} />
          <ol className={styles.steps}>
            <li>
              <span>Before</span>
              <p>
                <Text text={flow.change.before.text} />
              </p>
            </li>
            <li data-switch>
              <span>The switch</span>
              <p>
                <Text text={flow.change.turn.text} />
              </p>
            </li>
            <li>
              <span>After</span>
              <p>
                <Text text={flow.change.after.text} />
              </p>
            </li>
          </ol>
          {flow.change.effect ? (
            <p className={styles.effect}>
              <span>Possible effect</span> <Inferred />{" "}
              <Text text={flow.change.effect} />
            </p>
          ) : null}
        </div>
      ) : null}
      <Missing items={model.missing[1]} />
    </>
  );
}

function ItemCard({
  item,
  whyLabel,
  tone,
  onSelect,
}: {
  item: Item;
  whyLabel: string;
  tone: "good" | "warn";
  onSelect?: Select;
}) {
  return (
    <li className={styles.item} data-tone={tone}>
      <p className={styles.itemTitle}>
        <Text text={item.title} />
      </p>
      <p className={styles.itemText}>
        <Text text={item.what.text} />
      </p>
      <Play
        source={item.what.sources[0]}
        title={item.title}
        onSelect={onSelect}
      />
      {item.why ? (
        <p className={styles.why}>
          <span>{whyLabel}</span>
          <Text text={item.why.text} />
        </p>
      ) : null}
    </li>
  );
}

function WorkedDidnt({
  model,
  onSelect,
}: {
  model: StoryModel;
  onSelect?: Select;
}) {
  return (
    <>
      <div className={styles.columns}>
        <section aria-label="What worked">
          <h3 className={styles.columnHead} data-tone="good">
            What worked
          </h3>
          {model.worked.length ? (
            <ul className={styles.items}>
              {model.worked.map((item, index) => (
                <ItemCard
                  key={index}
                  item={item}
                  whyLabel="Why it helped"
                  tone="good"
                  onSelect={onSelect}
                />
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>No supported strength was supplied.</p>
          )}
        </section>
        <section aria-label="What didn't">
          <h3 className={styles.columnHead} data-tone="warn">
            What didn&apos;t
          </h3>
          {model.didnt.length ? (
            <ul className={styles.items}>
              {model.didnt.map((item, index) => (
                <ItemCard
                  key={index}
                  item={item}
                  whyLabel="What it affected"
                  tone="warn"
                  onSelect={onSelect}
                />
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>
              No supported issue was supplied. That does not mean there were
              none.
            </p>
          )}
        </section>
      </div>
      <Missing items={model.missing[2]} />
    </>
  );
}

const KIND_TONE: Record<MomentKind, string> = {
  "Strong Moment": "good",
  "Turning Point": "accent",
  "Important Miss": "warn",
  Objection: "bad",
  "Price Moment": "info",
  "Decision Moment": "accent",
  Commitment: "good",
  "Worth Replaying": "neutral",
};

function MomentCard({
  moment,
  people,
  onSelect,
}: {
  moment: Moment;
  people: ReturnType<typeof useReportPeople>;
  onSelect?: Select;
}) {
  return (
    <li className={styles.moment} data-kind={KIND_TONE[moment.kind]}>
      <p className={styles.momentHead}>
        <span className={styles.kind}>{moment.kind}</span>
        <span className={styles.momentAt}>
          {formatClock(moment.source.start_ms)}
        </span>
        <Play source={moment.source} title={moment.title} onSelect={onSelect} />
      </p>
      <p className={styles.itemTitle}>
        <Text text={moment.title} />
      </p>
      <Quote source={moment.source} person={people.speakerOf(moment.source)} />
      {moment.movedToward ? (
        <p className={styles.why}>
          <span>You moved toward</span>
          <Text text={moment.movedToward.text} />
        </p>
      ) : null}
      {moment.couldExplore ? (
        <p className={styles.why}>
          <span>Could have explored</span>
          <Text text={moment.couldExplore} />
        </p>
      ) : null}
      {moment.why ? (
        <p className={styles.why}>
          <span>Why it mattered</span>
          <Text text={moment.why.text} />
        </p>
      ) : null}
    </li>
  );
}

function Moments({
  model,
  people,
  onSelect,
}: {
  model: StoryModel;
  people: ReturnType<typeof useReportPeople>;
  onSelect?: Select;
}) {
  const [all, setAll] = useState(false);
  const shown = all
    ? [...model.moments].sort((a, b) => a.source.start_ms - b.source.start_ms)
    : model.topMoments;
  return (
    <>
      {shown.length ? (
        <ol className={styles.moments}>
          {shown.map((moment) => (
            <MomentCard
              key={moment.key}
              moment={moment}
              people={people}
              onSelect={onSelect}
            />
          ))}
        </ol>
      ) : null}
      {model.moments.length > model.topMoments.length ? (
        <button
          type="button"
          className={styles.more}
          aria-expanded={all}
          onClick={() => setAll((value) => !value)}
        >
          {all
            ? "Show the key moments only"
            : `View all ${model.moments.length} moments`}
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      ) : null}
      <Missing items={model.missing[3]} />
    </>
  );
}

const STATE_TONE: Record<SkillState, string> = {
  "Strongly Demonstrated": "good",
  Observed: "accent",
  "Needs Attention": "warn",
  "Not Enough Evidence": "neutral",
  "Not Applicable": "neutral",
};

function Skills({ model, onSelect }: { model: StoryModel; onSelect?: Select }) {
  const { deeper } = model;
  const hasDeeper =
    deeper.unclear.length || deeper.concerns.length || deeper.findings.length;
  return (
    <>
      <ul className={styles.skills}>
        {model.skills.map((skill) => (
          <li key={skill.id}>
            <details className={styles.skill}>
              <summary>
                <span className={styles.skillName} title={skill.label}>
                  {skill.short}
                </span>
                <span
                  className={styles.state}
                  data-tone={skill.state ? STATE_TONE[skill.state] : "neutral"}
                >
                  {skill.state ?? "Not established"}
                </span>
                <ChevronDown
                  className={styles.chevron}
                  size={14}
                  aria-hidden="true"
                />
              </summary>
              <div className={styles.skillBody}>
                <p className={styles.itemText}>
                  {skill.observation ? (
                    <Text text={skill.observation} />
                  ) : (
                    "This report does not establish a state for this skill."
                  )}
                </p>
                {skill.sources.length ? (
                  <p className={styles.plays}>
                    <span>Evidence</span>
                    {skill.sources.slice(0, 4).map((source, index) => (
                      <Play
                        key={`${source.segment_id}-${index}`}
                        source={source}
                        title={skill.label}
                        onSelect={onSelect}
                      />
                    ))}
                  </p>
                ) : null}
                <Link
                  className={styles.link}
                  href={`/coaching?focus=${skill.id}`}
                >
                  Coaching on this skill
                  <ArrowRight size={13} aria-hidden="true" />
                </Link>
              </div>
            </details>
          </li>
        ))}
      </ul>
      {hasDeeper ? (
        <details className={styles.deeper}>
          <summary>
            Explore deeper analysis
            <ChevronDown
              className={styles.chevron}
              size={14}
              aria-hidden="true"
            />
          </summary>
          <div className={styles.deeperBody}>
            {deeper.unclear.length ? (
              <section>
                <h4>Still unclear</h4>
                <ul className={styles.bullets}>
                  {deeper.unclear.map((item) => (
                    <li key={item}>
                      <Text text={item} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {deeper.concerns.length ? (
              <section>
                <h4>
                  What the prospect may be worried about <Inferred />
                </h4>
                <ul className={styles.bullets}>
                  {deeper.concerns.map((concern, index) => (
                    <li key={index}>
                      <Text text={concern.text} />{" "}
                      <Play
                        source={concern.sources[0]}
                        title="Possible concern"
                        onSelect={onSelect}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {deeper.findings.length ? (
              <section>
                <h4>Objections and closing</h4>
                <ul className={styles.bullets}>
                  {deeper.findings.map((finding, index) => (
                    <li key={index}>
                      <strong>
                        <Text text={finding.title} />
                      </strong>{" "}
                      <Text text={finding.what.text} />{" "}
                      <Play
                        source={finding.what.sources[0]}
                        title={finding.title}
                        onSelect={onSelect}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        </details>
      ) : null}
      <Missing items={model.missing[4]} />
    </>
  );
}

function Fact({
  label,
  children,
  extra,
}: {
  label: string;
  children: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <div className={styles.fact}>
      <dt>
        {label}
        {extra}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}

function LineText({
  line,
  title,
  onSelect,
}: {
  line: Line;
  title: string;
  onSelect?: Select;
}) {
  return (
    <>
      <Text text={line.text} />{" "}
      <Play source={line.sources.at(-1)} title={title} onSelect={onSelect} />
    </>
  );
}

function DealStands({
  model,
  onSelect,
  prospectControls,
  onOpenCoaching,
}: {
  model: StoryModel;
  onSelect?: Select;
  prospectControls?: ReactNode;
  onOpenCoaching?: () => void;
}) {
  const { deal } = model;
  return (
    <>
      <div className={styles.dealHead}>
        <OutcomeBadge outcome={deal.outcome} />
        {deal.quality ? (
          <span className={styles.quality} data-quality={deal.quality}>
            Commitment: {deal.quality}
          </span>
        ) : null}
      </div>
      <dl className={styles.facts}>
        {deal.position ? (
          <Fact label="Prospect's position">
            <LineText
              line={deal.position}
              title="Prospect's position"
              onSelect={onSelect}
            />
          </Fact>
        ) : null}
        {deal.blocker ? (
          <Fact label="Possible blocker" extra={<Inferred />}>
            <LineText
              line={deal.blocker}
              title="Possible blocker"
              onSelect={onSelect}
            />
          </Fact>
        ) : null}
        {deal.prospectCommitments.map((item, index) => (
          <Fact key={`p${index}`} label="Prospect agreed to">
            <LineText
              line={item}
              title="Prospect commitment"
              onSelect={onSelect}
            />
          </Fact>
        ))}
        {deal.sellerCommitments.map((item, index) => (
          <Fact key={`s${index}`} label="You agreed to">
            <LineText
              line={item}
              title="Seller commitment"
              onSelect={onSelect}
            />
          </Fact>
        ))}
        {deal.nextEvent ? (
          <Fact label="Next event">
            <LineText
              line={deal.nextEvent}
              title="Next event"
              onSelect={onSelect}
            />
          </Fact>
        ) : null}
        {deal.unclear.length ? (
          <Fact label="Still needs to become clear">
            <ul className={styles.bullets}>
              {deal.unclear.map((item) => (
                <li key={item}>
                  <Text text={item} />
                </li>
              ))}
            </ul>
          </Fact>
        ) : null}
        {deal.action ? (
          <Fact label="Recommended next move">
            <Text text={deal.action} />
          </Fact>
        ) : null}
      </dl>
      <Missing items={model.missing[5]} />
      <div className={styles.ctas}>
        <Link className={styles.cta} href="/prospects">
          View Prospect&apos;s Information
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
        {onOpenCoaching ? (
          <button
            type="button"
            className={styles.ctaQuiet}
            onClick={onOpenCoaching}
          >
            Coaching for this call
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {deal.coachingMission ? (
        <p className={styles.note}>
          Coaching mission for your next call:{" "}
          <Text text={deal.coachingMission} />
        </p>
      ) : null}
      {prospectControls ? (
        <section
          className={styles.prospectLink}
          aria-label="Prospect for this call"
        >
          <h3 className={styles.columnHead}>Prospect for this call</h3>
          {prospectControls}
        </section>
      ) : null}
      <EndStrip model={model} />
    </>
  );
}

function EndStrip({ model }: { model: StoryModel }) {
  const moment =
    model.topMoments.find((m) => m.kind === "Turning Point") ??
    model.topMoments[0];
  const cells = [
    ["Call outcome", model.picture.outcome.status],
    ["Strongest part", model.worked[0]?.title],
    ["Biggest issue", model.didnt[0]?.title],
    [
      "Most important moment",
      moment ? `${moment.kind} · ${formatClock(moment.source.start_ms)}` : null,
    ],
    ["Next step", model.picture.nextStep ? "Agreed" : null],
  ].filter((cell): cell is [string, string] => Boolean(cell[1]));
  if (cells.length < 2) return null;
  return (
    <dl className={styles.endStrip} aria-label="Report summary">
      {cells.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd title={value}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** One pillar of the story; all six share the same model. */
export function StoryPillar({
  index,
  data,
  callId,
  onSelect,
  prospectControls,
  onOpenCoaching,
}: {
  index: number;
  data: DocumentReportData;
  callId: string | null;
  onSelect?: Select;
  prospectControls?: ReactNode;
  onOpenCoaching?: () => void;
}) {
  const { model, people } = useStory(data, callId);
  if (!model) return null;
  return (
    <div className={styles.pillar} data-report-pillar={STORY_PILLARS[index].id}>
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
        <WorkedDidnt model={model} onSelect={onSelect} />
      ) : index === 3 ? (
        <Moments model={model} people={people} onSelect={onSelect} />
      ) : index === 4 ? (
        <Skills model={model} onSelect={onSelect} />
      ) : (
        <DealStands
          model={model}
          onSelect={onSelect}
          prospectControls={prospectControls}
          onOpenCoaching={onOpenCoaching}
        />
      )}
    </div>
  );
}
