import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ notify: vi.fn(), haptic: vi.fn() }));

vi.mock("../notice-center", () => ({ notify: calls.notify }));
vi.mock("../ui/haptics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../ui/haptics")>()),
  haptic: calls.haptic,
}));

import { CHARACTERS_PATH, resetCharactersForTests } from "../people/characters";
import { CharacterSheet } from "./character-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Choose your character (owner #32, 26 Oct 2026): a tap saves it as your
// photo; replacing a photo asks first.
const LIST = ["Fox", "Owl", "Panda", "Cat"].map((label) => ({
  key: label.toLowerCase(),
  label,
  url: `${CHARACTERS_PATH}/${label.toLowerCase()}?v=0123abcd`,
}));

let root: Root;
let host: HTMLDivElement;
let status = 200;
const sent: { url: string; method?: string; body?: unknown }[] = [];

beforeEach(() => {
  resetCharactersForTests();
  calls.notify.mockReset();
  calls.haptic.mockReset();
  sent.length = 0;
  status = 200;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (url === CHARACTERS_PATH) return Response.json({ characters: LIST });
    sent.push({ url, method: init?.method, body: init?.body });
    return status === 200
      ? Response.json({})
      : Response.json({ detail: "No." }, { status });
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function open(props: {
  current?: string | null;
  replacesPhoto?: boolean;
  onChosen?: (key: { key: string }) => void;
}) {
  await act(async () =>
    root.render(
      <CharacterSheet
        open
        current={props.current ?? null}
        replacesPhoto={props.replacesPhoto ?? false}
        onClose={() => undefined}
        onChosen={props.onChosen ?? (() => undefined)}
      />,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
}

const choice = (label: string) =>
  [
    ...document.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Characters"] button',
    ),
  ].find((button) => button.textContent === label)!;
const button = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === label,
  )!;

it("ticks the one shown now and saves a tap at once without a photo", async () => {
  const chosen = vi.fn();
  await open({ current: "panda", onChosen: chosen });
  expect(choice("Panda").getAttribute("aria-pressed")).toBe("true");
  expect(
    choice("Panda").querySelector('[aria-label="Shown now"]'),
  ).not.toBeNull();
  expect(choice("Owl").querySelector("img")?.getAttribute("src")).toBe(
    `${CHARACTERS_PATH}/owl?v=0123abcd`,
  );

  await act(async () => choice("Owl").click());
  expect(sent).toEqual([
    {
      url: "/v1/me/sales-xray-profile/character",
      method: "PUT",
      body: JSON.stringify({ character: "owl" }),
    },
  ]);
  expect(calls.haptic.mock.calls).toEqual([["tap"], ["success"]]);
  expect(chosen).toHaveBeenCalledWith(LIST[1]);
});

it("asks before a character replaces a photo", async () => {
  const chosen = vi.fn();
  await open({ replacesPhoto: true, onChosen: chosen });
  await act(async () => choice("Fox").click());
  expect(sent).toEqual([]);
  expect(document.body.textContent).toContain(
    "This replaces your current photo.",
  );
  await act(async () => button("Keep my photo").click());
  expect(document.body.textContent).not.toContain(
    "This replaces your current photo.",
  );
  await act(async () => choice("Fox").click());
  await act(async () => button("Use the fox").click());
  expect(sent.map((item) => item.body)).toEqual([
    JSON.stringify({ character: "fox" }),
  ]);
  expect(chosen).toHaveBeenCalledWith(LIST[0]);
});

it("says so in a corner card when characters aren't ready", async () => {
  status = 409;
  const chosen = vi.fn();
  await open({ onChosen: chosen });
  await act(async () => choice("Cat").click());
  expect(chosen).not.toHaveBeenCalled();
  expect(calls.haptic.mock.calls).toEqual([["tap"], ["error"]]);
  expect(calls.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "Character not saved",
      message: "Characters aren't ready yet. Try again later.",
    }),
  );
});
