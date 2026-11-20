import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { KINDS, LIBRARY_VERSION, PACKS, SX_EVENTS } from "./library";
import { playEvent, playSound, resetPlayer } from "./player";
import {
  forgetSounds,
  localView,
  playsFor,
  readSounds,
  saveMine,
} from "./prefs";
import {
  choiceLabel,
  eventById,
  resolveChoice,
  soundFiles,
  soundsOfKind,
  validFor,
} from "./sounds";

type Library = {
  version: string;
  events: {
    id: string;
    app: string;
    label: string;
    kind: string;
    default: string;
  }[];
  packs: { id: string }[];
  sounds: {
    id: string;
    pack: string;
    kind: string;
    loop: boolean;
    files: Record<string, string>;
  }[];
};

const library = JSON.parse(
  readFileSync(resolve(__dirname, "../../public/sounds/library.json"), "utf8"),
) as Library;

afterEach(() => {
  vi.unstubAllGlobals();
  resetPlayer();
  forgetSounds();
  window.localStorage.clear();
});

describe("the sound library copy", () => {
  it("matches the shipped library.json: moments, defaults, packs, kinds", () => {
    expect(LIBRARY_VERSION).toBe(library.version);
    const sx = library.events.filter((event) => event.app === "sales-x-ray");
    expect(
      SX_EVENTS.map(({ id, label, kind, default: d }) => ({
        id,
        label,
        kind,
        default: d,
      })),
    ).toEqual(
      sx.map(({ id, label, kind, default: d }) => ({
        id,
        label,
        kind,
        default: d,
      })),
    );
    expect(new Set(PACKS.map((pack) => pack.id))).toEqual(
      new Set(library.packs.map((pack) => pack.id)),
    );
    // Every pack × kind is a sound whose web files are where soundFiles says.
    for (const pack of PACKS)
      for (const kind of Object.keys(KINDS)) {
        const id = `${pack.id}.${kind}`;
        const sound = library.sounds.find((item) => item.id === id);
        expect(sound, id).toBeDefined();
        expect(sound?.loop).toBe(kind === "ringtone");
        const files = soundFiles(id);
        expect(files).toEqual({
          mp3: `/${sound?.files.mp3.replace(/^sets\//, "sounds/")}`,
        });
        // Shipped: public/sounds holds every library MP3 (and no .webm).
        expect(
          existsSync(resolve(__dirname, `../../public${files?.mp3}`)),
          id,
        ).toBe(true);
      }
  });
});

describe("choices", () => {
  const lead = eventById("sx.new_lead")!;

  it("plays mine, else the team's, else the library default; only the moment's kind", () => {
    expect(resolveChoice(lead)).toBe("glass-v2.mention");
    expect(resolveChoice(lead, null, "warm-v1.mention")).toBe(
      "warm-v1.mention",
    );
    expect(resolveChoice(lead, "none", "warm-v1.mention")).toBe("none");
    expect(resolveChoice(lead, "A.ringtone", "B.error")).toBe(
      "glass-v2.mention",
    );
    expect(validFor(lead, "system")).toBe(true);
    expect(validFor(lead, "/sounds/glass-v1/mention.webm")).toBe(false);
  });

  it("names a choice and groups a kind's sounds by family, Glass first", () => {
    expect(choiceLabel("glass-v2.mention")).toBe("Glass V2 · Mention");
    expect(choiceLabel("A.ringtone")).toBe("Synth A · Ringtone");
    expect(choiceLabel("none")).toBe("None");
    expect(choiceLabel("system")).toBe("Phone default");
    const groups = soundsOfKind("mention");
    expect(groups.map((group) => group.label)).toEqual([
      "Glass",
      "Warm",
      "Pulse",
      "Synth",
    ]);
    expect(groups.flatMap((group) => group.sounds)).toHaveLength(12);
  });
});

describe("prefs", () => {
  it("keeps a personal workspace's picks on this device and remembers what plays", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "no" }), { status: 403 }),
      ),
    );
    const view = await readSounds();
    expect(view.local).toBe(true);
    const saved = await saveMine(view, { "sx.new_lead": "pulse-v1.mention" });
    expect(saved.events.find((row) => row.id === "sx.new_lead")?.plays).toBe(
      "pulse-v1.mention",
    );
    forgetSounds();
    expect(playsFor("sx.new_lead")).toBe("pulse-v1.mention");
    expect(
      localView().events.find((row) => row.id === "sx.new_lead")?.mine,
    ).toBe("pulse-v1.mention");
  });

  it("sends a person's own pick to the server inside an organisation", async () => {
    const answer = {
      events: SX_EVENTS.map((event) => ({
        id: event.id,
        team: event.default,
        mine: null,
        plays: event.id === "sx.report_ready" ? "none" : event.default,
      })),
      sellers_pick: true,
      manager: false,
      own_picks: 1,
    };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(answer)));
    vi.stubGlobal("fetch", fetchMock);
    const view = await readSounds();
    await saveMine(view, { "sx.report_ready": "none" });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/v1/lead-desk/sounds",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ mine: { "sx.report_ready": "none" } }),
      }),
    );
    expect(playsFor("sx.report_ready")).toBe("none");
  });
});

describe("player", () => {
  class FakeAudio {
    static made: FakeAudio[] = [];
    src = "";
    loop = false;
    preload = "";
    currentTime = 0;
    listeners: Record<string, (() => void)[]> = {};
    constructor() {
      FakeAudio.made.push(this);
    }
    canPlayType(type: string) {
      return type.includes("opus") ? "probably" : "";
    }
    addEventListener(name: string, run: () => void) {
      (this.listeners[name] ??= []).push(run);
    }
    play = vi.fn(async () => undefined);
    pause = vi.fn(() => this.listeners.pause?.forEach((run) => run()));
  }

  it("plays the MP3, stops the last sound for the next, and loops only a ringtone when asked", () => {
    FakeAudio.made = [];
    vi.stubGlobal("Audio", FakeAudio);
    const ended = vi.fn();
    expect(playSound("glass-v2.mention", { ended })).toBe(true);
    expect(FakeAudio.made[0].src).toBe("/sounds/glass-v2/mention.mp3");
    playSound("glass-v3.ringtone", { loop: true });
    expect(FakeAudio.made[0].pause).toHaveBeenCalled();
    expect(ended).toHaveBeenCalledOnce();
    expect(FakeAudio.made[1].loop).toBe(true);
    playSound("glass-v2.mention", { loop: true });
    expect(FakeAudio.made[2].loop).toBe(false);
    expect(playSound("none")).toBe(false);
  });

  it("plays a moment's picked sound once for moments that arrive together", () => {
    FakeAudio.made = [];
    vi.stubGlobal("Audio", FakeAudio);
    window.localStorage.setItem(
      "sx-sounds-plays",
      JSON.stringify({ "sx.report_ready": "warm-v2.success" }),
    );
    expect(playEvent("sx.report_ready")).toBe("warm-v2.success");
    expect(FakeAudio.made[0].src).toBe("/sounds/warm-v2/success.mp3");
    expect(playEvent("sx.new_lead")).toBeNull();
  });

  it("is quiet without audio in the browser", () => {
    vi.stubGlobal("Audio", undefined);
    expect(playSound("glass-v2.mention")).toBe(false);
  });
});
