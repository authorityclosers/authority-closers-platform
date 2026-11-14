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

it("sends taps one after another, so the last answer holds them all", async () => {
  // Dev, 14 Nov 2026: a mission and a bookmark tapped together crossed, and
  // the bookmark's answer unticked the mission on screen.
  const server = { saved: [] as string[], missions: [] as string[] };
  let open = 0;
  let most = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      open += 1;
      most = Math.max(most, open);
      await new Promise((resolve) => setTimeout(resolve, 5));
      const id = url.split("/").pop() ?? "";
      const body = JSON.parse(String(init.body)) as {
        item: string;
        on: boolean;
      };
      const list = body.item === "saved" ? server.saved : server.missions;
      if (body.on && !list.includes(id)) list.push(id);
      open -= 1;
      return answer([...server.saved], [...server.missions]);
    }),
  );
  const both = Promise.all([
    setItem("PB03", "mission", true),
    setItem("PB03", "saved", true),
  ]);
  expect([...progressNow().missions]).toEqual(["PB03"]);
  expect([...progressNow().saved]).toEqual(["PB03"]);
  expect(await both).toEqual([true, true]);
  expect(most).toBe(1);
  expect([...progressNow().missions]).toEqual(["PB03"]);
  expect([...progressNow().saved]).toEqual(["PB03"]);
});

it("takes back only the failed tap, not a later one", async () => {
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      calls += 1;
      return calls === 1
        ? new Response("{}", { status: 500 })
        : answer(["OB03"], []);
    }),
  );
  const failed = setItem("DM02", "mission", true);
  const saved = setItem("OB03", "saved", true);
  expect(await failed).toBe(false);
  expect(await saved).toBe(true);
  expect([...progressNow().missions]).toEqual([]);
  expect([...progressNow().saved]).toEqual(["OB03"]);
});
