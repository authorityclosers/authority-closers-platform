import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import {
  CallTimeline,
  ChangeSteps,
  CommitmentQuality,
  FactList,
  MetricRow,
  MomentTag,
  OutcomeBadge,
  PillarHeading,
  PossibleTag,
  PlayChip,
  Quote,
  ShareDial,
  SkillStateMark,
  SplitBar,
  SummaryStrip,
} from "./visuals";

const source = {
  segment_id: "a1",
  quote: "I want to reach ten lakh consistently.",
  start_ms: 395_000,
  end_ms: 418_000,
};

const html = (node: React.ReactNode) => renderToStaticMarkup(<>{node}</>);

it("names the pillar with its number and promise", () => {
  const markup = html(
    <PillarHeading
      index={2}
      title="How the Call Played Out"
      subtitle="See how the conversation moved."
    />,
  );
  expect(markup).toContain(">2<");
  expect(markup).toContain("<h2");
  expect(markup).toContain("See how the conversation moved.");
});

it("plays a clip when there is a player, else shows the time as text", () => {
  expect(
    html(<PlayChip source={source} title="Goal" onSelect={vi.fn()} />),
  ).toContain('aria-label="Play 06:35: Goal"');
  expect(html(<PlayChip source={source} title="Goal" />)).not.toContain(
    "<button",
  );
  expect(html(<PlayChip source={source} title="Goal" range />)).toContain(
    "06:35–06:58",
  );
  expect(html(<PlayChip source={undefined} title="Goal" />)).toBe("");
  // With a label the time comes first, as in Dipak's document.
  expect(
    html(
      <PlayChip
        source={source}
        title="Goal"
        onSelect={vi.fn()}
        label="Play"
        range
      />,
    ).replace(/<[^>]*>/g, ""),
  ).toContain("06:35–06:58 · Play");
  expect(
    html(<PlayChip source={source} title="Goal" label="Play" />),
  ).toContain("06:35 · Play");
});

it("quotes in the UI face with who said it", () => {
  const markup = html(
    <Quote
      text={source.quote}
      speaker={{ name: "Amit Sharma", role: "prospect" }}
    />,
  );
  expect(markup).toContain("“");
  expect(markup).toContain("Amit Sharma");
  expect(markup).toContain("Prospect");
});

it("says the outcome in words and who established it", () => {
  const markup = html(<OutcomeBadge status="Decision Pending" origin="call" />);
  expect(markup).toContain("Decision Pending");
  expect(markup).toContain('data-tone="warn"');
  expect(markup).toContain("As heard on the call");
  expect(html(<OutcomeBadge status={null} origin={null} />)).toContain(
    "Only a person can mark a call Won or Lost",
  );
});

it("shows measured figures and splits without a score", () => {
  const markup = html(
    <MetricRow
      items={[
        { label: "Call length", value: "25:08" },
        {
          label: "Talk share",
          value: "62 : 38",
          visual: (
            <SplitBar
              unit="%"
              parts={[
                { label: "You", value: 62 },
                { label: "Amit", value: 38 },
              ]}
            />
          ),
        },
      ]}
    />,
  );
  expect(markup).toContain("Call length");
  expect(markup).toContain('aria-label="You 62%, Amit 38%"');
  expect(
    html(
      <SplitBar
        parts={[
          { label: "You", value: 17 },
          { label: "Amit", value: 8 },
        ]}
      />,
    ),
  ).toContain('aria-label="You 17, Amit 8"');
  expect(
    html(
      <ShareDial value={62} total={100} label="You talked 62% of the time" />,
    ),
  ).toContain(">62%<");
  expect(html(<MetricRow items={[]} />)).toBe("");
});

it("draws the call in stages with moments and the change point", () => {
  const onSelect = vi.fn();
  const markup = html(
    <CallTimeline
      durationMs={1_508_000}
      speech={{
        top: [{ start_ms: 0, end_ms: 60_000 }],
        bottom: [{ start_ms: 60_000, end_ms: 400_000 }],
      }}
      names={{ top: "You", bottom: "Amit" }}
      phases={[
        { label: "Opening", start_ms: 0, end_ms: 150_000 },
        { label: "Business Context", start_ms: 150_000, end_ms: 1_508_000 },
      ]}
      moments={[
        {
          key: "m1",
          kind: "Strong Moment",
          title: "Goal",
          at_ms: 395_000,
          source,
        },
      ]}
      change={{ at_ms: 678_000, label: "The call changed" }}
      onSelect={onSelect}
    />,
  );
  expect(markup).toContain("Business Context");
  expect(markup).toContain("02:30");
  expect(markup).toContain('aria-label="Play Strong Moment · 06:35: Goal"');
  // Where the call changed: a dashed line on the wave, named in the key and
  // the figure's label (its words never sit over the bars).
  expect(markup).toContain(
    'aria-label="How the call moved: 2 stages over 25:08; The call changed · 11:18"',
  );
  expect(markup).toMatch(/data-key="change">.*The call changed · 11:18/);
  expect(markup).toContain('data-mode="speech"');
  // The phone track's span sits over the stages.
  expect(markup).toMatch(/<span>00:00<\/span><span>25:08<\/span>/);
  // Phones: each stage sits on one track of the call at its own place and
  // length, with its own set of wider bars (56 across the whole call).
  expect(markup).toContain("--from:0.09946949602122016");
  expect(markup).toContain("--span:0.9005305039787799");
  const rows = [...markup.matchAll(/data-set="rows"[^>]*>(.*?)<\/span>/g)];
  expect(rows).toHaveLength(2);
  expect(
    rows.reduce((sum, [, bars]) => sum + (bars.match(/<i /g) ?? []).length, 0),
  ).toBe(56);
  // No duration, no timeline; no speech or sound, stage blocks only.
  expect(html(<CallTimeline durationMs={0} />)).toBe("");
  expect(html(<CallTimeline durationMs={10_000} />)).toContain(
    'data-mode="none"',
  );
});

it("keeps skill states and moment kinds as words, never numbers", () => {
  expect(html(<SkillStateMark state="Needs Attention" />)).toContain(
    "Needs Attention",
  );
  expect(html(<SkillStateMark state={null} />)).toContain("Not covered");
  expect(html(<MomentTag kind="Important Miss" atMs={532_000} />)).toContain(
    "08:52",
  );
  expect(html(<MomentTag kind="Something new" />)).toContain(
    'data-tone="neutral"',
  );
});

it("lays out the switch, commitment, facts and the end strip", () => {
  expect(
    html(
      <ChangeSteps before="Discovery" turn="Amit asked" after="Presentation" />,
    ),
  ).toContain("The switch");
  const quality = html(<CommitmentQuality quality="Clear" />);
  expect(quality).toContain("Specific action + specific date/time.");
  expect(quality.match(/data-on/g)).toHaveLength(3);
  expect(
    html(
      <FactList items={[{ label: "Next event", value: "Friday · 4:00 PM" }]} />,
    ),
  ).toContain("Friday · 4:00 PM");
  expect(
    html(<SummaryStrip cells={[{ label: "Only one", value: "x" }]} />),
  ).toBe("");
});

it("marks Sales Xray's own reading as Possible, in the copy module's words", () => {
  const markup = html(<PossibleTag />);
  expect(markup).toContain(">Possible<");
  expect(markup).toContain("Nobody said this in so many words.");
});

it("draws figures without a second frame inside a card", () => {
  const markup = html(
    <MetricRow bare items={[{ label: "Call length", value: "25:08" }]} />,
  );
  expect(markup).toContain("data-bare");
});

it("draws the measured sound when there is no speech, and the player's position", () => {
  const envelope = {
    schema: "ac.sales-xray.waveform/1" as const,
    kind: "rms_envelope" as const,
    duration_ms: 10_000,
    points: Array.from({ length: 10 }, (_, index) => ({
      start_ms: index * 1000,
      level: 0.5,
    })),
  };
  const markup = html(
    <CallTimeline durationMs={10_000} envelope={envelope} playheadMs={5_000} />,
  );
  expect(markup).toContain('data-mode="level"');
  expect(markup).toContain("left:50%");
  // Without stages a phone gets one strip of 60 wider bars (96 on desktop).
  const sets = (set: string) =>
    (
      markup.match(new RegExp(`data-set="${set}"[^>]*>(.*?)</span>`))?.[1] ?? ""
    ).split("<i ").length - 1;
  expect(sets("wide")).toBe(96);
  expect(sets("rows")).toBe(60);
  // Outside a report (no player) and no explicit position: no playhead.
  expect(
    html(<CallTimeline durationMs={10_000} envelope={envelope} />),
  ).not.toContain("left:50%");
});
