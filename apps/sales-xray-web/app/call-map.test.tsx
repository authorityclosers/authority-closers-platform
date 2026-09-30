import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { CallMap } from "./call-map";
import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { updateShellState } from "./shell/shell-store";
import { readSpeakerProfiles, saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL_ID = "4f0c2a77-1b53-4c55-8d11-9f3a2b6e7c10";
const report = fixture.report as SalesReport;
const transcript = fixture.transcript as Transcript;

let root: Root;
let host: HTMLDivElement;
let onSeek: ReturnType<typeof vi.fn<(ms: number) => void>>;
let onSelectEvidence: ReturnType<
  typeof vi.fn<(evidence: ReportEvidence) => void>
>;

async function renderMap(
  source: Transcript = transcript,
  sourceReport: SalesReport = report,
) {
  await act(async () =>
    root.render(
      <CallMap
        callId={CALL_ID}
        transcript={source}
        report={sourceReport}
        durationMs={source.duration_ms}
        onSelectEvidence={onSelectEvidence}
        onSeek={onSeek}
      />,
    ),
  );
}

async function sayAndConfirm(text: string, sourceReport: SalesReport) {
  await renderMap(
    {
      ...transcript,
      segments: [
        {
          id: "a1",
          speaker_id: "a",
          start_ms: 0,
          end_ms: 1200,
          text,
        },
        {
          id: "b1",
          speaker_id: "b",
          start_ms: 1300,
          end_ms: 2000,
          text: "Hello.",
        },
      ],
    },
    sourceReport,
  );
  const yes = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Yes",
  )!;
  await act(async () => yes.click());
}

beforeEach(async () => {
  localStorage.clear();
  updateShellState({ profileName: null });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onSeek = vi.fn();
  onSelectEvidence = vi.fn();
  await renderMap();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  localStorage.clear();
});

function slider() {
  const element = host.querySelector<HTMLElement>('[role="slider"]')!;
  // jsdom has no layout: give the track a known 500px width.
  element.getBoundingClientRect = () =>
    ({
      left: 0,
      top: 0,
      width: 500,
      height: 56,
      right: 500,
      bottom: 56,
    }) as DOMRect;
  return element;
}

function pointer(type: string, clientX: number) {
  const event = new MouseEvent(type, { bubbles: true, clientX, button: 0 });
  Object.defineProperty(event, "pointerId", { value: 1 });
  Object.defineProperty(event, "pointerType", { value: "mouse" });
  return event;
}

function chips() {
  return Array.from(
    host.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Speakers"] > button',
    ),
  );
}

function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

it("peeks at who is speaking where the pointer rests", async () => {
  const track = slider();
  // 2.6s of 5s: inside segment s2 (2.5s to 3.3s), the second voice.
  await act(async () => track.dispatchEvent(pointer("pointermove", 260)));
  const peek = host.textContent ?? "";
  expect(peek).toContain("Speaker 2");
  expect(peek).toContain(transcript.segments[1].text);
  expect(peek).toContain("Click to play from here");
});

it("clicking the waveform plays the call from that time", async () => {
  const track = slider();
  await act(async () => track.dispatchEvent(pointer("pointerdown", 100)));
  await act(async () => track.dispatchEvent(pointer("pointerup", 100)));
  expect(onSeek).toHaveBeenCalledTimes(1);
  expect(onSeek.mock.calls[0][0]).toBeCloseTo(1000, 5);
});

it("the waveform is a keyboard slider that seeks in five-second steps", async () => {
  const track = slider();
  expect(track.getAttribute("aria-valuetext")).toContain("of");
  await act(async () =>
    track.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
    ),
  );
  expect(onSeek).toHaveBeenLastCalledWith(4999);
  await act(async () =>
    track.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Home", bubbles: true }),
    ),
  );
  expect(onSeek).toHaveBeenLastCalledWith(0);
  await act(async () =>
    track.dispatchEvent(
      new KeyboardEvent("keydown", { key: "End", bubbles: true }),
    ),
  );
  expect(onSeek).toHaveBeenLastCalledWith(transcript.duration_ms - 1);
});

it("a moment dot plays its cited evidence", async () => {
  const dot = host.querySelector<HTMLButtonElement>("button[data-tone]")!;
  expect(dot.getAttribute("aria-label")).toMatch(/Play this moment/);
  await act(async () => dot.click());
  expect(onSelectEvidence).toHaveBeenCalledTimes(1);
});

it("draws one lane per speaker, each with that voice's own turns", () => {
  expect(chips().map((chip) => chip.getAttribute("aria-label"))).toEqual([
    "Edit Speaker 1",
    "Edit Speaker 2",
  ]);
  const lanes = host.querySelectorAll("svg[data-voice]");
  expect(lanes).toHaveLength(2);
  expect(lanes[0].querySelectorAll("rect").length).toBeGreaterThan(0);
  expect(lanes[1].querySelectorAll("rect").length).toBeGreaterThan(0);
});

it("names a speaker, gives them a role and an icon, and remembers it", async () => {
  await act(async () => chips()[1].click());
  const editor = host.querySelector<HTMLElement>(
    '[role="dialog"][aria-label="Edit Speaker 2"]',
  )!;
  expect(editor).not.toBeNull();
  // The other lane dims while this speaker is being edited.
  const lanes = host.querySelectorAll("svg[data-voice]");
  expect(lanes[0].getAttribute("data-dim")).toBe("true");

  const name = editor.querySelector<HTMLInputElement>("input")!;
  await act(async () => type(name, "Rahul Mehta"));
  const prospect = Array.from(editor.querySelectorAll("button")).find(
    (button) => button.textContent === "Prospect",
  )!;
  await act(async () => prospect.click());
  // Choosing "Prospect" preselects the icon the report suggests.
  expect(
    editor.querySelector('button[aria-pressed="true"][title]'),
  ).not.toBeNull();
  const hammer = editor.querySelector<HTMLButtonElement>(
    'button[aria-label="Carpentry & building"]',
  )!;
  if (hammer.getAttribute("aria-pressed") !== "true")
    await act(async () => hammer.click());
  const save = Array.from(editor.querySelectorAll("button")).find(
    (button) => button.textContent === "Save",
  )!;
  await act(async () => save.click());

  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(chips()[1].getAttribute("aria-label")).toBe("Edit Rahul Mehta");
  expect(chips()[1].textContent).toContain("Prospect");
  expect(readSpeakerProfiles(CALL_ID)).toEqual({
    closer: { name: "Rahul Mehta", role: "prospect", icon: "carpentry" },
  });
  expect(host.querySelector("figcaption")?.textContent).toContain(
    "Who talked more · Speaker 1 : Rahul Mehta",
  );
});

it("keeps speaker edits available for retry when device storage rejects a save", async () => {
  await act(async () => chips()[1].click());
  const editor = host.querySelector<HTMLElement>('[role="dialog"]')!;
  const name = editor.querySelector<HTMLInputElement>("input")!;
  await act(async () => type(name, "Fictional speaker"));
  const prospect = Array.from(editor.querySelectorAll("button")).find(
    (button) => button.textContent === "Prospect",
  )!;
  await act(async () => prospect.click());
  const save = Array.from(editor.querySelectorAll("button")).find(
    (button) => button.textContent === "Save",
  )!;
  const write = vi.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Storage full", "QuotaExceededError");
  });
  await act(async () => save.click());
  expect(write).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="dialog"]') === editor).toBe(true);
  expect(editor.querySelector('[role="alert"]')?.textContent).toContain(
    "Couldn’t save on this device. Try again.",
  );
  expect(name.value).toBe("Fictional speaker");
  expect(prospect.getAttribute("aria-pressed")).toBe("true");
  expect(readSpeakerProfiles(CALL_ID)).toEqual({});
  write.mockRestore();
  await act(async () => save.click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(readSpeakerProfiles(CALL_ID).closer).toMatchObject({
    name: "Fictional speaker",
    role: "prospect",
  });
});

it("suggests which voice is you from an introduction, confirmed in one tap", async () => {
  updateShellState({ profileName: "Suyash Rao" });
  await act(async () =>
    saveSpeakerProfiles(CALL_ID, {
      rep: { name: "Suyash Rao", role: null, icon: "person" },
    }),
  );
  await renderMap({
    ...transcript,
    segments: [
      {
        id: "a1",
        speaker_id: "rep",
        start_ms: 0,
        end_ms: 1500,
        text: "Hello, this is Suyash from Authority Closers.",
      },
      {
        id: "a2",
        speaker_id: "buyer",
        start_ms: 1600,
        end_ms: 3000,
        text: "Hi, yes, tell me about the programme.",
      },
    ],
  });
  expect(host.textContent).toContain("looks like you");
  const yes = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Yes",
  )!;
  await act(async () => yes.click());

  expect(host.textContent).not.toContain("looks like you");
  expect(chips()[0].getAttribute("aria-label")).toBe("Edit Suyash Rao");
  expect(chips()[0].textContent).toContain("You");
  expect(chips()[1].textContent).toContain("Prospect");
  const saved = readSpeakerProfiles(CALL_ID);
  expect(saved.rep.role).toBe("you");
  expect(saved.rep.icon).toBe("person");
  expect(saved.buyer.role).toBe("prospect");
});

it("summarises talk ratio, monologue, switches and the report balance", () => {
  const text = host.querySelector("figcaption")?.textContent ?? "";
  expect(text).toMatch(/Who talked more\d+ : \d+/);
  expect(text).toContain("Longest non-stop talk");
  expect(text).toMatch(/Questions asked · Speaker 1 : Speaker 2\d+ : \d+/);
  expect(text).toMatch(/1 done well · \d+ to work on/);
});

it("names another salesperson and the prospect from the opening, in one tap", async () => {
  updateShellState({ profileName: "Suyash Rao" });
  await renderMap({
    ...transcript,
    segments: [
      {
        id: "o1",
        speaker_id: "caller",
        start_ms: 0,
        end_ms: 4000,
        text: "नंदलाल जी नमस्ते मेरा नाम मानस है। मैं team से बोल रहा हूं।",
      },
      {
        id: "o2",
        speaker_id: "owner",
        start_ms: 4200,
        end_ms: 5000,
        text: "हां बोलो।",
      },
    ],
  });
  expect(host.textContent).toContain("is the salesperson");
  expect(host.textContent).not.toContain("looks like you");
  const yes = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Yes",
  )!;
  await act(async () => yes.click());
  expect(chips()[0].getAttribute("aria-label")).toBe("Edit मानस");
  expect(chips()[0].textContent).toContain("Salesperson");
  expect(chips()[1].getAttribute("aria-label")).toBe("Edit नंदलाल जी");
  expect(chips()[1].textContent).toContain("Prospect");
});

it("does not infer salesperson from a buyer name alone", async () => {
  await renderMap(
    {
      ...transcript,
      segments: [
        {
          id: "a1",
          speaker_id: "a",
          start_ms: 0,
          end_ms: 1200,
          text: "My name is Rahul.",
        },
        {
          id: "b1",
          speaker_id: "b",
          start_ms: 1300,
          end_ms: 2000,
          text: "Hello.",
        },
      ],
    },
    { ...report, strengths: [], improvements: [] },
  );

  expect(host.textContent).not.toContain("is the salesperson");
  expect(
    Array.from(host.querySelectorAll("button")).some(
      (button) => button.textContent === "Yes",
    ),
  ).toBe(false);
  expect(readSpeakerProfiles(CALL_ID)).toEqual({});
});

it("confirms a hello-here self introduction on the speaking voice", async () => {
  updateShellState({ profileName: "Rahul" });
  await sayAndConfirm("Hello Rahul here", {
    ...report,
    strengths: [],
    improvements: [],
  });

  expect(readSpeakerProfiles(CALL_ID)).toEqual({
    a: { name: "Rahul", role: "you", icon: null },
    b: { name: "", role: "prospect", icon: expect.any(String) },
  });
});

it("does not save just as a name after confirming a generic opening", async () => {
  updateShellState({ profileName: "Suyash Rao" });
  const cited = {
    segment_id: "a1",
    quote: "I am just calling about your enquiry.",
    start_ms: 0,
    end_ms: 1200,
  };
  const coachingReport: SalesReport = {
    ...report,
    strengths: [{ title: "Fictional", explanation: "", evidence: [cited] }],
    improvements: [{ title: "Fictional", explanation: "", evidence: [cited] }],
  };
  await sayAndConfirm("I am just calling about your enquiry.", coachingReport);

  expect(readSpeakerProfiles(CALL_ID).a).toMatchObject({
    name: "",
    role: "salesperson",
  });
  expect(readSpeakerProfiles(CALL_ID).a.name).not.toBe("just");
});

it("does not save a generic greeting as the prospect name after seller confirmation", async () => {
  const cited = {
    segment_id: "a1",
    quote: "We should review your current process.",
    start_ms: 0,
    end_ms: 1200,
  };
  const coachingReport: SalesReport = {
    ...report,
    strengths: [{ title: "Fictional", explanation: "", evidence: [cited] }],
    improvements: [{ title: "Fictional", explanation: "", evidence: [cited] }],
  };
  await renderMap(
    {
      ...transcript,
      segments: [
        {
          id: "a1",
          speaker_id: "a",
          start_ms: 0,
          end_ms: 1200,
          text: cited.quote,
        },
        {
          id: "b1",
          speaker_id: "b",
          start_ms: 1300,
          end_ms: 2000,
          text: "Hello there.",
        },
      ],
    },
    coachingReport,
  );

  const yes = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Yes",
  )!;
  await act(async () => yes.click());

  expect(readSpeakerProfiles(CALL_ID).a).toMatchObject({
    name: "",
    role: "salesperson",
  });
  expect(readSpeakerProfiles(CALL_ID).b).toMatchObject({
    name: "",
    role: "prospect",
  });
});

it("does not offer a name confirmation for an ordinary here phrase", async () => {
  await renderMap(
    {
      ...transcript,
      segments: [
        {
          id: "a1",
          speaker_id: "a",
          start_ms: 0,
          end_ms: 1200,
          text: "Thanks for being here.",
        },
        {
          id: "b1",
          speaker_id: "b",
          start_ms: 1300,
          end_ms: 2000,
          text: "Hello.",
        },
      ],
    },
    { ...report, strengths: [], improvements: [] },
  );

  expect(
    Array.from(host.querySelectorAll("button")).some(
      (button) => button.textContent === "Yes",
    ),
  ).toBe(false);
  expect(readSpeakerProfiles(CALL_ID)).toEqual({});
});

it("keeps all three lenses and asks for a role before showing talk share", async () => {
  // Owner decision (30 Sep): Who talked, Call stages and Talk share always show.
  await act(async () => root.unmount());
  localStorage.setItem("ac.xray.map-lens", "stages");
  root = createRoot(host);
  await renderMap();
  const controls = host.querySelector('[aria-label="What the map shows"]')!;
  const lens = (name: string) =>
    Array.from(controls.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent === name,
    )!;
  expect(
    Array.from(controls.querySelectorAll("button")).map((b) => b.textContent),
  ).toEqual(["Who talked", "Call stages", "Talk share by minute"]);
  expect(lens("Call stages").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("once the analysis marks them");

  await act(async () => lens("Talk share by minute").click());
  expect(host.textContent).toContain(
    "Assign a speaker role to view talk share.",
  );
});

it("shows factual talk share only after the call has a confirmed role", async () => {
  const voices = [
    ...new Set(transcript.segments.map((segment) => segment.speaker_id)),
  ];
  const seller = voices[0]!;
  const buyer = voices[1]!;
  await act(async () =>
    saveSpeakerProfiles(CALL_ID, {
      [seller]: { name: "Fictional Seller", role: "you", icon: null },
      [buyer]: { name: "Fictional Buyer", role: "prospect", icon: null },
    }),
  );
  await renderMap();

  const lens = (name: string) =>
    Array.from(
      host.querySelectorAll<HTMLButtonElement>(
        '[aria-label="What the map shows"] button',
      ),
    ).find((button) => button.textContent === name)!;
  expect(lens("Who talked").getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelectorAll("svg[data-voice]")).toHaveLength(2);

  await act(async () => lens("Talk share by minute").click());
  expect(host.querySelectorAll("svg[data-voice]")).toHaveLength(0);
  expect(host.textContent).toContain("talk share in each minute");
  expect(host.textContent).not.toContain("went quiet");
  expect(localStorage.getItem("ac.xray.map-lens")).toBe("talk-share");
});
