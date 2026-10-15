import { parseReportContent } from "./report-content";
import {
  contentFixture,
  contentReport,
  contentTranscript,
} from "./review-fixture/report/pillars/content-fixture";
import { act, useContext, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

const { signIn } = vi.hoisted(() => ({ signIn: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: signIn, replace: vi.fn(), prefetch: vi.fn() }),
}));
import { LinkedProspectContext } from "./prospect-link-control";
import { BIG_PICTURE, SKILLS, WORKED_DIDNT } from "./report-copy";
import { ReportModes } from "./report-modes";
import { REPORT_PILLARS } from "./report-pillars";
import { WorkedDidnt } from "./report-sections/worked-didnt";
import { reportStoryModel } from "./report-story-model";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

async function mount(
  report: typeof amitReport,
  transcript?: typeof amitTranscript,
) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const select = vi.fn();
  await act(async () =>
    root.render(
      <ReportModes
        structure="pillars"
        initialView="story"
        panels={[
          {
            id: "prospect",
            label: "Old buyer profile",
            content: "full profile content",
          },
        ]}
        documentData={{ report, transcript }}
        onSelectEvidence={select}
      />,
    ),
  );
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  return { host, select };
}

const pillar = (host: HTMLElement, id: string) =>
  host.querySelector<HTMLElement>(`[data-report-pillar="${id}"]`)!;

it("tells the call as six pillars in the spec's order, without profile or coaching panels", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  expect(
    [...host.querySelectorAll("[data-report-mode-section]")].map((e) =>
      e.getAttribute("data-report-mode-section"),
    ),
  ).toEqual(REPORT_PILLARS.map((p) => p.id));
  expect(host.textContent).not.toContain("full profile content");
  // Practice exercises belong to Coaching, not the Report.
  expect(host.textContent).not.toContain(
    amitReport.overview!.practice!.instructions,
  );
  const picture = pillar(host, "overview").textContent;
  expect(picture).toContain("Follow-up Set");
  expect(picture).toContain("As heard on the call");
  expect(picture).toContain("Strongest part");
  expect(picture).toContain("Biggest concern");
  expect(picture).toContain("Next step");
  expect(picture).not.toContain("This report doesn't cover");
});

it("plays the exact quoted moment from any pillar", async () => {
  const { host, select } = await mount(amitReport, amitTranscript);
  const strongest = amitReport.strengths[0].evidence[0];
  const button = pillar(host, "overview").querySelector<HTMLButtonElement>(
    'button[aria-label="Play 18:42: Strongest part"]',
  )!;
  await act(async () => button.click());
  expect(select).toHaveBeenCalledWith(strongest, "Strongest part");
});

it.each(["saved", "matching pillars", "validated content"] as const)(
  "makes %s summary clips reachable once each, in saved order",
  async (kind) => {
    const validated = kind === "validated content";
    const report = validated ? contentReport : amitReport;
    const transcript = validated ? contentTranscript : amitTranscript;
    const sources = validated
      ? contentFixture.summary_sentences.flatMap((note) => note.evidence)
      : amitReport.summary_evidence!;
    const summary = validated
      ? contentFixture.summary_sentences.map((note) => note.text).join(" ")
      : report.summary;
    const { host, select } = await mount(
      {
        ...report,
        summary_evidence: [sources[0], { ...sources[0] }, ...sources.slice(1)],
        ...(kind === "matching pillars"
          ? { pillars: { version: "report-pillars/1" as const, summary } }
          : {}),
        ...(validated
          ? {
              report_content: {
                ...contentFixture,
                summary_sentences: [
                  contentFixture.summary_sentences[0],
                  ...contentFixture.summary_sentences.slice(1).map((note) => ({
                    ...note,
                    evidence: [{ ...sources[0] }, ...note.evidence],
                  })),
                ],
              },
            }
          : {}),
      },
      transcript,
    );
    const picture = pillar(host, "overview");
    expect(picture.textContent).toContain(summary);
    const buttons = picture.querySelectorAll<HTMLButtonElement>(
      '[role="group"][aria-label="Summary"] button',
    );
    expect(buttons).toHaveLength(sources.length);
    expect(select).not.toHaveBeenCalled();
    for (const [index, button] of [...buttons].entries()) {
      expect(button.type).toBe("button");
      await act(async () => button.click());
      expect(select).toHaveBeenCalledTimes(index + 1);
      expect(select.mock.calls[index][0]).toBe(sources[index]);
      expect(select.mock.calls[index][1]).toBe(BIG_PICTURE.summary.label);
    }
    expect(
      [...host.querySelectorAll("[data-report-mode-section]")].map((node) =>
        node.getAttribute("data-report-mode-section"),
      ),
    ).toEqual(REPORT_PILLARS.map((part) => part.id));
  },
);

it.each(["no sources", "different pillar summary"] as const)(
  "adds no summary clip row for %s",
  async (kind) => {
    const report = {
      ...amitReport,
      ...(kind === "no sources"
        ? { summary_evidence: [] }
        : {
            pillars: {
              version: "report-pillars/1" as const,
              summary: "A different saved summary without its own citations.",
            },
          }),
    };
    const { host, select } = await mount(report, amitTranscript);
    const picture = pillar(host, "overview");
    expect(picture.textContent).toContain(
      report.pillars?.summary ?? report.summary,
    );
    expect(
      picture.querySelector('[role="group"][aria-label="Summary"]'),
    ).toBeNull();
    expect(select).not.toHaveBeenCalled();
  },
);

const findingSources = amitReport.dimensions.flatMap(
  (skill) => skill.evidence ?? [],
);

async function mountWorked(sources: (typeof findingSources)[]) {
  const base = reportStoryModel(amitReport, amitTranscript);
  const withSources = (items: typeof base.worked, index: number) =>
    items.map((item, itemIndex) =>
      itemIndex === 0 && sources[index]
        ? { ...item, what: { ...item.what, sources: sources[index] } }
        : item,
    );
  const model = {
    ...base,
    worked: withSources(base.worked, 0),
    didnt: withSources(base.didnt, 1),
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const select = vi.fn();
  await act(async () =>
    root.render(<WorkedDidnt model={model} onSelect={select} />),
  );
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  return { host, select };
}

it.each([0, 1, 2])(
  "needs no Worked / Didn't disclosure for %i saved clips",
  async (count) => {
    const sources = findingSources.slice(0, count);
    const { host, select } = await mountWorked([sources]);
    const row = host.querySelector("li")!;
    expect(row.querySelector("button[aria-controls]")).toBeNull();
    const clips = [...row.querySelectorAll<HTMLButtonElement>("button")];
    expect(clips).toHaveLength(count);
    expect(row.textContent).toContain(amitReport.strengths[0].explanation);
    expect(select).not.toHaveBeenCalled();
    for (const [index, clip] of clips.entries()) {
      await act(async () => clip.click());
      expect(select).toHaveBeenCalledTimes(index + 1);
      expect(select.mock.calls[index][0]).toBe(sources[index]);
      expect(select.mock.calls[index][1]).toBe(amitReport.strengths[0].title);
    }
  },
);

it("reaches all Worked / Didn't clips in saved order, with independent cards and fold focus", async () => {
  const sources = [
    [
      findingSources[4],
      findingSources[0],
      findingSources[2],
      findingSources[0],
    ],
    findingSources.slice(1, 4),
  ];
  const { host, select } = await mountWorked(sources);
  const section = host;
  const columns = [
    section.querySelector(
      `section[aria-label="${WORKED_DIDNT.worked.label}"]`,
    )!,
    section.querySelector(`section[aria-label="${WORKED_DIDNT.didnt.label}"]`)!,
  ];
  const rows = columns.map((column) => column.querySelector("li")!);
  const toggles = rows.map(
    (row) => row.querySelector<HTMLButtonElement>("button[aria-controls]")!,
  );
  const groups = toggles.map(
    (toggle) => document.getElementById(toggle.getAttribute("aria-controls")!)!,
  );
  const clips = (index: number) => [
    ...groups[index].querySelectorAll<HTMLButtonElement>("button"),
  ];
  expect(groups[0]).not.toBe(groups[1]);
  expect(columns[0].querySelectorAll("li")).toHaveLength(3);
  expect(columns[1].querySelectorAll("li")).toHaveLength(3);
  for (const [index, toggle] of toggles.entries()) {
    expect(toggle.textContent).toBe(SKILLS.showAllClips(sources[index].length));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(clips(index)).toHaveLength(2);
  }
  await act(async () => toggles[0].click());
  expect(clips(0)).toHaveLength(4);
  expect(clips(1)).toHaveLength(2);
  await act(async () => toggles[1].click());
  expect(clips(1)).toHaveLength(3);
  expect(select).not.toHaveBeenCalled();
  const titles = [
    amitReport.strengths[0].title,
    amitReport.improvements[0].title,
  ];
  for (const [rowIndex, refs] of sources.entries()) {
    expect(toggles[rowIndex].getAttribute("aria-expanded")).toBe("true");
    expect(toggles[rowIndex].textContent).toBe(SKILLS.showFewerClips);
    for (const [index, clip] of clips(rowIndex).entries()) {
      select.mockClear();
      await act(async () => clip.click());
      expect(select).toHaveBeenCalledTimes(1);
      expect(select.mock.calls[0][0]).toBe(refs[index]);
      expect(select.mock.calls[0][1]).toBe(titles[rowIndex]);
    }
  }
  select.mockClear();
  clips(0).at(-1)!.focus();
  await act(async () => toggles[0].click());
  expect(document.activeElement).toBe(toggles[0]);
  expect(toggles[0].getAttribute("aria-expanded")).toBe("false");
  expect(clips(0)).toHaveLength(2);
  expect(clips(1)).toHaveLength(3);
  expect(select).not.toHaveBeenCalled();
  expect(rows[0].textContent).toContain(WORKED_DIDNT.whyHelped);
  expect(rows[1].textContent).toContain(WORKED_DIDNT.whatAffected);
});

it("shows eight compact skill rows that expand to evidence and Coaching", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const skills = pillar(host, "skills");
  const rows = skills.querySelectorAll("details > summary");
  // Eight skills plus the collapsed deeper analysis.
  expect(rows).toHaveLength(9);
  expect(rows[0].textContent).toContain("Human Connection & Trust");
  expect(rows[0].textContent).toContain("Strongly Demonstrated");
  expect(rows[1].textContent).toContain("Needs Attention");
  expect(skills.querySelectorAll('a[href^="/coaching?focus="]')).toHaveLength(
    8,
  );
  expect(skills.textContent).toContain("Explore deeper analysis");
});

const skillSources = amitReport.dimensions.flatMap(
  (skill) => skill.evidence ?? [],
);

it.each([0, 4])(
  "needs no skill clip disclosure for %i saved refs",
  async (count) => {
    const sources = skillSources.slice(0, count);
    const { host, select } = await mount(
      {
        ...amitReport,
        dimensions: amitReport.dimensions.map((skill, index) =>
          index === 0 ? { ...skill, evidence: sources } : skill,
        ),
      },
      amitTranscript,
    );
    const row = pillar(host, "skills").querySelector("li")!;
    expect(row.querySelector("button[aria-controls]")).toBeNull();
    const clips = [...row.querySelectorAll<HTMLButtonElement>("button")];
    expect(clips).toHaveLength(count);
    expect(row.textContent?.includes(SKILLS.evidence)).toBe(count > 0);
    expect(select).not.toHaveBeenCalled();
    for (const [index, clip] of clips.entries()) {
      await act(async () => clip.click());
      expect(select).toHaveBeenCalledTimes(index + 1);
      expect(select.mock.calls[index][0]).toBe(sources[index]);
      expect(select.mock.calls[index][1]).toBe(amitReport.dimensions[0].label);
    }
  },
);

it("expands skill clips independently in saved order, retaining duplicate refs and fold focus", async () => {
  const sources = [
    [
      skillSources[4],
      skillSources[0],
      skillSources[2],
      skillSources[3],
      skillSources[0],
    ],
    skillSources.slice(1, 7),
  ];
  const { host, select } = await mount(
    {
      ...amitReport,
      dimensions: amitReport.dimensions.map((skill, index) =>
        index < 2 ? { ...skill, evidence: sources[index] } : skill,
      ),
    },
    amitTranscript,
  );
  const skills = pillar(host, "skills");
  const rows = [...skills.querySelectorAll("ul > li")].slice(0, 2);
  const toggles = rows.map(
    (row) => row.querySelector<HTMLButtonElement>("button[aria-controls]")!,
  );
  const groups = toggles.map(
    (toggle) => document.getElementById(toggle.getAttribute("aria-controls")!)!,
  );
  const clips = (index: number) => [
    ...groups[index].querySelectorAll<HTMLButtonElement>("button"),
  ];
  expect(groups[0]).not.toBe(groups[1]);
  for (const [index, toggle] of toggles.entries()) {
    expect(toggle.textContent).toBe(SKILLS.showAllClips(sources[index].length));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(clips(index)).toHaveLength(4);
    rows[index].querySelector("details")!.open = true;
  }
  await act(async () => toggles[0].click());
  expect(clips(0)).toHaveLength(5);
  expect(clips(1)).toHaveLength(4);
  await act(async () => toggles[1].click());
  expect(clips(0)).toHaveLength(5);
  expect(clips(1)).toHaveLength(6);
  expect(select).not.toHaveBeenCalled();
  for (const [rowIndex, refs] of sources.entries()) {
    expect(toggles[rowIndex].getAttribute("aria-expanded")).toBe("true");
    expect(toggles[rowIndex].textContent).toBe(SKILLS.showFewerClips);
    for (const [index, button] of clips(rowIndex).entries()) {
      select.mockClear();
      await act(async () => button.click());
      expect(select).toHaveBeenCalledTimes(1);
      expect(select.mock.calls[0][0]).toBe(refs[index]);
      expect(select.mock.calls[0][1]).toBe(
        amitReport.dimensions[rowIndex].label,
      );
    }
  }
  select.mockClear();
  clips(0).at(-1)!.focus();
  await act(async () => toggles[0].click());
  expect(document.activeElement).toBe(toggles[0]);
  expect(clips(0)).toHaveLength(4);
  expect(clips(1)).toHaveLength(6);
  expect(toggles[0].getAttribute("aria-expanded")).toBe("false");
  expect(rows[0].querySelector("details")!.open).toBe(true);
  expect(rows[1].querySelector("details")!.open).toBe(true);
  expect(skills.querySelectorAll('a[href^="/coaching?focus="]')).toHaveLength(
    8,
  );
  expect(rows[0].textContent).toContain(amitReport.dimensions[0].observation);
  expect(rows[1].textContent).toContain(amitReport.dimensions[1].observation);
  expect(select).not.toHaveBeenCalled();
});

it("keeps moments to five, then shows all on request", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const moments = pillar(host, "missed");
  expect(moments.querySelectorAll("ol > li").length).toBeLessThanOrEqual(5);
  const more = [...moments.querySelectorAll("button")].find((b) =>
    b.textContent?.startsWith("View all"),
  );
  expect(more).toBeDefined();
  await act(async () => more!.click());
  expect(moments.querySelectorAll("ol > li").length).toBeGreaterThan(5);
  expect(moments.textContent).not.toContain("Important Miss");
  expect(moments.textContent).not.toContain("You moved toward");
  expect(moments.textContent).not.toContain("What was missed");
});

it("ends where the deal stands, with links to the prospect and Coaching", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const deal = pillar(host, "facts");
  expect(deal.textContent).toContain("Commitment quality");
  expect(deal.textContent).toContain("Clear");
  expect(deal.textContent).toContain("Friday · 4:00 PM");
  expect(deal.textContent).toContain("Still needs to become clear");
  expect(deal.querySelector('a[href="/prospects"]')).not.toBeNull();
  expect(deal.textContent).toContain("View Prospect Information");
  expect(deal.textContent).toContain("View Personalized Coaching");
  // The end strip names the next event, not just "Agreed".
  expect(
    deal.querySelector('dl[aria-label="Report summary"]')?.textContent,
  ).toContain("Friday · 4:00 PM");
});

it("opens a sparse older report with honest, one-line gaps", async () => {
  const { host } = await mount(syntheticReport);
  const picture = pillar(host, "overview");
  expect(picture.textContent).toContain(BIG_PICTURE.outcomeNotSet);
  expect(picture.textContent).toContain(BIG_PICTURE.outcomeOnlyPerson);
  expect(picture.textContent).toContain("This report doesn't cover:");
  expect(
    pillar(host, "skills").querySelectorAll("details > summary").length,
  ).toBeGreaterThanOrEqual(8);
  // Never invents a strength or a next event to fill the page.
  expect(pillar(host, "facts").textContent).toContain("Next event");
});

function LinkedTo({ id }: { id: string }) {
  const report = useContext(LinkedProspectContext);
  useEffect(() => report?.(id), [report, id]);
  return <span>Linked prospect</span>;
}

it("opens this call's own prospect from the end of the Report", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <ReportModes
        structure="pillars"
        initialView="story"
        panels={[]}
        prospectControls={<LinkedTo id="prospect-7" />}
        documentData={{ report: amitReport, transcript: amitTranscript }}
      />,
    ),
  );
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  const deal = pillar(host, "facts");
  expect(
    deal.querySelector('a[href="/prospects/prospect-7"]')?.textContent,
  ).toContain("View Prospect Information");
});

it("gives a guest the same six pillars, with locked items counted and a sign-in link", async () => {
  const counts = (hidden: number) => ({
    visible_count: 1,
    total_count: 1 + hidden,
    hidden_count: hidden,
  });
  const preview = {
    version: "guest-findings-v1" as const,
    sections: {
      strengths: counts(2),
      improvements: counts(1),
      missed_opportunities: counts(1),
      objection_analysis: counts(0),
      closing_analysis: counts(0),
      golden_moments: counts(1),
      prospect_interpretations: counts(0),
      rewatch: counts(0),
      ethics_notes: counts(0),
    },
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  await act(async () =>
    root.render(
      <ReportModes
        structure="pillars"
        panels={[]}
        documentData={{
          report: { ...amitReport, preview },
          transcript: amitTranscript,
        }}
      />,
    ),
  );
  expect(
    host.querySelector("[data-report-modes]")?.getAttribute("data-view"),
  ).toBe("story");
  const worked = pillar(host, "moments").textContent;
  expect(worked).toContain("2 more strengths are saved for your account.");
  expect(worked).toContain("1 more issue is saved for your account.");
  expect(pillar(host, "missed").textContent).toContain(
    "2 more moments are saved for your account.",
  );
  // One way on for a guest: sign in. No Coaching or prospect buttons.
  const deal = pillar(host, "facts");
  const signInButton = [...deal.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Sign in to see the full report"),
  );
  await act(async () => signInButton!.click());
  expect(signIn).toHaveBeenCalledWith("/login");
  expect(deal.textContent).not.toContain("View Personalized Coaching");
  expect(deal.textContent).not.toContain("View Prospect Information");
});

it("shows a validated missed chance with its opening, response opportunity and relevance", async () => {
  const title = "The seller moved to scheduling before clarifying delivery";
  const response = "The seller proposed a meeting time.";
  const relevance = "The delivery date remained open for the meeting.";
  const content = parseReportContent(
    {
      ...contentFixture,
      missed_chances: [
        {
          title,
          opening: contentFixture.blocker!,
          response_opportunity: {
            ...contentFixture.seller_commitments[0],
            text: response,
          },
          relevance: { ...contentFixture.blocker!, text: relevance },
        },
      ],
    },
    contentTranscript,
  );
  const { host, select } = await mount(
    { ...contentReport, report_content: content },
    contentTranscript,
  );
  const moments = pillar(host, "missed");
  const miss = [...moments.querySelectorAll("ol > li")].find((item) =>
    item.textContent?.includes("Important Miss"),
  )!;
  for (const text of [
    title,
    contentTranscript.segments[3].text,
    response,
    relevance,
  ])
    expect(miss.textContent).toContain(text);
  await act(async () =>
    miss.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(select).toHaveBeenCalledWith(
    content.missed_chances[0].opening.evidence[0],
    title,
  );
});
