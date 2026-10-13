import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  AcquisitionFileStage,
  type AcquisitionFileStageProps,
} from "./acquisition-file-stage";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const first = new File([new Uint8Array(1024)], "Discovery call.m4a", {
  type: "audio/mp4",
  lastModified: 1,
});
const second = new File([new Uint8Array(512)], "Follow-up call.wav", {
  type: "audio/wav",
  lastModified: 2,
});
const third = new File([new Uint8Array(256)], "Closing call.mp3", {
  type: "audio/mpeg",
  lastModified: 3,
});

let host: HTMLDivElement;
let root: Root;
let callbacks: Pick<
  AcquisitionFileStageProps,
  "onSelect" | "onRemove" | "onClear" | "onAddFiles"
>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  callbacks = {
    onSelect: vi.fn(),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onAddFiles: vi.fn(),
  };
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function renderStage(props: Partial<AcquisitionFileStageProps> = {}) {
  await act(async () =>
    root.render(
      <AcquisitionFileStage
        files={[]}
        selectedFile={null}
        maxBytes={100_000_000}
        maxMinutes={60}
        disabled={false}
        {...callbacks}
        {...props}
      />,
    ),
  );
}

it("offers accessible local browse and only supplied file limits", async () => {
  await renderStage();
  expect(host.textContent).toContain("Drop your call recording here");
  expect(host.textContent).toContain(
    "Audio or video recordings · up to 100 MB · 60 min per call",
  );
  expect(host.textContent).toContain("Choose a file");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const click = vi.spyOn(input, "click").mockImplementation(() => {});
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(click).toHaveBeenCalledOnce();
  expect(input.multiple).toBe(true);
});

it.each([
  "amr",
  "awb",
  "aac",
  "3ga",
  "webm",
  "opus",
  "mp4",
  "mov",
  "m4b",
  "3gp",
  "mkv",
  "mka",
  "aiff",
  "aif",
  "wma",
  "asf",
  "wmv",
  "caf",
])(
  "keeps a phone %s file selectable even without a browser MIME type",
  async (extension) => {
    const phone = new File(["fictional"], `Phone call.${extension}`);
    await renderStage({ files: [phone], selectedFile: null });
    const select = host.querySelector<HTMLButtonElement>("li button")!;
    expect(select.disabled).toBe(false);
    expect(host.textContent).not.toContain("Unsupported");
    await act(async () => select.click());
    expect(callbacks.onSelect).toHaveBeenCalledWith(phone);
  },
);

it("shows local file facts and selects or removes one file without claiming a duration", async () => {
  await renderStage({ files: [first, second], selectedFile: first });
  expect(host.textContent).toContain("2 files added");
  expect(host.textContent).toContain(
    "Discovery call.m4a selected for analysis",
  );
  expect(host.textContent).not.toContain("42 min");
  const cards = host.querySelectorAll("li");
  expect(cards).toHaveLength(2);
  expect(cards[0]?.getAttribute("data-selected")).toBe("true");
  await act(async () =>
    cards[1]?.querySelector<HTMLButtonElement>("button")?.click(),
  );
  expect(callbacks.onSelect).toHaveBeenCalledWith(second);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        'button[aria-label="Remove Discovery call.m4a"]',
      )!
      .click(),
  );
  expect(callbacks.onRemove).toHaveBeenCalledWith(first);
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Clear all")!
      .click(),
  );
  expect(callbacks.onClear).toHaveBeenCalledOnce();
});

it("forwards dropped files locally without an upload or analysis action", async () => {
  await renderStage();
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", {
    value: { files: [first, second] },
  });
  await act(async () =>
    host.querySelector('[role="group"]')!.dispatchEvent(drop),
  );
  expect(drop.defaultPrevented).toBe(true);
  expect(callbacks.onAddFiles).toHaveBeenCalledWith([first, second]);
  expect(host.textContent).not.toContain("Processing");
});

it("keeps all files reachable in two-card pages within a compact stage", async () => {
  await renderStage({ files: [first, second, third], selectedFile: null });
  expect(host.querySelectorAll("li")).toHaveLength(2);
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Next")!
      .click(),
  );
  expect(host.querySelectorAll("li")).toHaveLength(1);
  expect(host.textContent).toContain("Closing call.mp3");
  expect(host.textContent).toContain("Files 3–3 of 3");
});

it("disables browse, selection, removal and drop during an active action", async () => {
  await renderStage({
    files: [first, second],
    selectedFile: first,
    disabled: true,
  });
  expect(
    [...host.querySelectorAll<HTMLButtonElement>("button")].filter(
      (button) => !button.disabled,
    ),
  ).toHaveLength(0);
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [third] } });
  await act(async () =>
    host.querySelector('[role="group"]')!.dispatchEvent(drop),
  );
  expect(callbacks.onAddFiles).not.toHaveBeenCalled();
});

it("shows the call's wave, quiet and hidden from screen readers, until a file is added", async () => {
  await renderStage();
  const wave = host.querySelector('[data-state="idle"]');
  expect(wave).not.toBeNull();
  expect(wave?.closest('[aria-hidden="true"]')).not.toBeNull();
  await renderStage({ files: [first], selectedFile: first });
  // The drop area gives the wave to the chosen file's card, which keeps its
  // room from the start (the motif until the file is measured).
  expect(
    host.querySelector(
      '[aria-label="Add sales call audio files"] [data-state]',
    ),
  ).toBeNull();
  const card = host.querySelector('li[data-selected="true"]')!;
  expect(card.querySelector('[role="img"][data-compact]')).not.toBeNull();
  expect(host.querySelectorAll('li [role="img"]')).toHaveLength(1);
});
