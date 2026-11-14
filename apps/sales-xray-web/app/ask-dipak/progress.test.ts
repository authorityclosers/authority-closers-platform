import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  PROGRESS_PATH,
  loadProgress,
  parseProgress,
  progressFor,
  progressNow,
  resetProgress,
  setItem,
} from "./progress";

const answer = (saved: string[], missions: string[]) =>
  new Response(JSON.stringify({ saved, missions }), { status: 200 });

beforeEach(() => {
  resetProgress();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

it("reads only well-formed lists of question IDs", () => {
  expect(parseProgress(null)).toBeNull();
  expect(parseProgress({ saved: [] })).toBeNull();
  const parsed = parseProgress({
    saved: ["PB03", 7, "<script>", "NEW-035"],
    missions: ["OB03"],
  });
  expect([...(parsed?.saved ?? [])]).toEqual(["PB03", "NEW-035"]);
  expect([...(parsed?.missions ?? [])]).toEqual(["OB03"]);
});

it("reads the account's progress once, from its own address", async () => {
  const fetch = vi.fn(async () => answer(["RP01"], ["RP01"]));
  vi.stubGlobal("fetch", fetch);
  await Promise.all([loadProgress(), loadProgress()]);
  await loadProgress();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0]).toEqual([
    PROGRESS_PATH,
    expect.objectContaining({ method: "GET", credentials: "same-origin" }),
  ]);
});

it("writes one item with its on or off, and takes the account's answer", async () => {
  const fetch = vi.fn(async () => answer(["PB03"], []));
  vi.stubGlobal("fetch", fetch);
  expect(await setItem("PB03", "saved", true)).toBe(true);
  expect([...progressNow().saved]).toEqual(["PB03"]);
  expect(progressNow().status).toBe("ready");
  expect(fetch).toHaveBeenCalledWith(
    `${PROGRESS_PATH}/PB03`,
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ item: "saved", on: true }),
    }),
  );
});

it("takes a failed write back", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 500 })),
  );
  const writing = setItem("OB03", "mission", true);
  // The screen shows it at once ...
  expect([...progressNow().missions]).toEqual(["OB03"]);
  // ... and takes it back when the account says no.
  expect(await writing).toBe(false);
  expect([...progressNow().missions]).toEqual([]);
});

it("starts afresh when another person signs in on the same screen", async () => {
  const fetch = vi.fn(async () => answer([], []));
  vi.stubGlobal("fetch", fetch);
  progressFor("person-a");
  await loadProgress();
  progressFor("person-a");
  await loadProgress();
  expect(fetch).toHaveBeenCalledTimes(1);
  progressFor("person-b");
  await loadProgress();
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("keeps the newest tap when an older answer arrives late", async () => {
  const replies: ((response: Response) => void)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          replies.push(resolve);
        }),
    ),
  );
  const first = setItem("CF01", "saved", true);
  const second = setItem("CF01", "saved", false);
  replies[1](answer([], []));
  await second;
  replies[0](answer(["CF01"], []));
  await first;
  expect([...progressNow().saved]).toEqual([]);
});
