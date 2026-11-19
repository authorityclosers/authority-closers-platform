import { existsSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LESSON_VIDEOS, LessonVideo, VIDEO_COPY, clock } from "./lesson-video";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "../../public");
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("LessonVideo (the Mac studio's lesson videos, 19 Nov 2026)", () => {
  it("ships each lesson's video and poster, encoded small for phones", () => {
    expect(Object.keys(LESSON_VIDEOS).sort()).toEqual(["OB03", "PB03"]);
    for (const file of Object.values(LESSON_VIDEOS)) {
      for (const path of [file.src, file.poster])
        expect(existsSync(join(PUBLIC, path)), path).toBe(true);
      expect(statSync(join(PUBLIC, file.src)).size).toBeLessThan(2_000_000);
    }
  });

  it("shows the poster and one play button first: nothing plays, nothing loads", () => {
    act(() => root.render(<LessonVideo id="PB03" />));
    expect(host.querySelector("video")).toBeNull();
    const start = host.querySelector("button");
    expect(start?.getAttribute("aria-label")).toBe(
      `${VIDEO_COPY.play}, ${clock(61)}`,
    );
    expect(host.querySelector("img")?.getAttribute("src")).toBe(
      LESSON_VIDEOS.PB03.poster,
    );
  });

  it("plays only after a tap, with the phone's controls and never on its own", () => {
    act(() => root.render(<LessonVideo id="OB03" />));
    act(() => host.querySelector("button")?.click());
    const video = host.querySelector("video");
    expect(video?.getAttribute("src")).toBe(LESSON_VIDEOS.OB03.src);
    expect(video?.hasAttribute("controls")).toBe(true);
    expect(video?.hasAttribute("autoplay")).toBe(false);
    // No caption file yet: no empty track.
    expect(host.querySelector("track")).toBeNull();
  });

  it("shows nothing for a lesson without a video", () => {
    act(() => root.render(<LessonVideo id="DM02" />));
    expect(host.innerHTML).toBe("");
  });

  it("writes the time as minutes and seconds", () => {
    expect(clock(61)).toBe("1:01");
    expect(clock(55)).toBe("0:55");
  });
});
