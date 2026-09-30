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
import { readSpeakerProfiles } from "./speaker-profiles";

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

async function renderMap(source: Transcript = transcript) {
  await act(async () =>
    root.render(
      <CallMap
        callId={CALL_ID}
        transcript={source}
        report={report}
        durationMs={source.duration_ms}
        onSelectEvidence={onSelectEvidence}
        onSeek={onSeek}
      />,
    ),
  );
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
    "Talk ratio · Speaker 1 : Rahul Mehta",
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
  expect(saved.buyer.role).toBe("prospect");
});

it("summarises talk ratio, monologue, switches and the report balance", () => {
  const text = host.querySelector("figcaption")?.textContent ?? "";
  expect(text).toMatch(/Talk ratio\d+ : \d+/);
  expect(text).toContain("Longest monologue");
  expect(text).toContain("Speaker switches");
  expect(text).toMatch(/1 win · \d+ to work on/);
});
