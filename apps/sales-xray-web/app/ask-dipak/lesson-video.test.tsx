import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LessonVideo, VIDEO_COPY, clock } from "./lesson-video";
import { VIDEOS_PATH, forgetVideos, fromServed } from "./lesson-videos";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const HERE = dirname(fileURLToPath(import.meta.url));
const PUBLIC = join(HERE, "../../public");
const REPO = join(HERE, "../../../..");
// The dev workbench's own copies (git-ignored, never in a build): see .gitignore.
const DEV_ONLY = "dev-media";

const PB03 = {
  src: "/dev-media/ask-dipak/lessons/pb03-lesson.mp4",
  poster: "/dev-media/ask-dipak/lessons/pb03-lesson-poster.jpg",
  seconds: 61,
};
const OB03 = {
  src: "https://media.example.test/ob03-lesson.mp4",
  poster: "https://media.example.test/ob03-lesson-poster.jpg",
  seconds: 55,
};

let host: HTMLDivElement;
let root: Root;

function serve(body: unknown, ok = true) {
  const fetcher = vi.fn(async () => ({ ok, json: async () => body }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

async function draw(id: string) {
  await act(async () => {
    root.render(<LessonVideo id={id} />);
  });
  // The one request of the visit, then its answer drawn.
  await act(async () => {
    await Promise.resolve();
  });
}

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === DEV_ONLY && dir === PUBLIC) return [];
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

beforeEach(() => {
  forgetVideos();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("LessonVideo: only approved videos, behind the server's switch (owner, 19 Nov 2026)", () => {
  it("switch off: the server sends no videos and nothing is drawn, no player, no placeholder", async () => {
    const fetcher = serve({ videos: {} });
    await draw("PB03");
    expect(fetcher).toHaveBeenCalledWith(VIDEOS_PATH, expect.anything());
    expect(host.innerHTML).toBe("");
    expect(host.querySelector("[data-lesson-video]")).toBeNull();
  });

  it("no answer or a failed one: nothing is drawn", async () => {
    serve({}, false);
    await draw("PB03");
    expect(host.innerHTML).toBe("");
    forgetVideos();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    await draw("OB03");
    expect(host.innerHTML).toBe("");
  });

  it("shows nothing for a lesson without an approved video", async () => {
    serve({ videos: { PB03 } });
    await draw("DM02");
    expect(host.innerHTML).toBe("");
  });

  it("switch on: the poster and one play button first, nothing plays, nothing loads", async () => {
    serve({ videos: { PB03 } });
    await draw("PB03");
    expect(host.querySelector("video")).toBeNull();
    expect(host.querySelector("[data-lesson-video='PB03']")).not.toBeNull();
    const start = host.querySelector("button");
    expect(start?.getAttribute("aria-label")).toBe(
      `${VIDEO_COPY.play}, ${clock(61)}`,
    );
    expect(host.querySelector("img")?.getAttribute("src")).toBe(PB03.poster);
  });

  it("plays only after a tap, with the phone's controls and never on its own", async () => {
    serve({ videos: { OB03 } });
    await draw("OB03");
    act(() => host.querySelector("button")?.click());
    const video = host.querySelector("video");
    expect(video?.getAttribute("src")).toBe(OB03.src);
    expect(video?.hasAttribute("controls")).toBe(true);
    expect(video?.hasAttribute("autoplay")).toBe(false);
    expect(host.querySelector("track")).toBeNull();
  });

  it("asks the server once per visit", async () => {
    const fetcher = serve({ videos: { PB03 } });
    await draw("PB03");
    await draw("OB03");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("leaves out anything it can't show safely", () => {
    expect(
      fromServed({
        videos: {
          PB03,
          A: { ...PB03, src: "//evil.test/x.mp4" },
          B: { ...PB03, src: "http://plain.test/x.mp4" },
          C: { ...PB03, src: "/a/../x.mp4" },
          D: { ...PB03, poster: "/x.gif" },
          E: { ...PB03, seconds: 0 },
          F: "nope",
        },
      }),
    ).toEqual({ PB03 });
    expect(fromServed(null)).toEqual({});
  });

  it("writes the time as minutes and seconds", () => {
    expect(clock(61)).toBe("1:01");
    expect(clock(55)).toBe("0:55");
  });
});

describe("no lesson video ships in the app's build", () => {
  it("public/ (copied whole into every web build and the phone bundle) has no lesson video or poster", () => {
    const shipped = files(PUBLIC).map((path) =>
      relative(PUBLIC, path).split("\\").join("/"),
    );
    expect(
      shipped.filter((path) => path.startsWith("media/ask-dipak/lessons")),
    ).toEqual([]);
    expect(shipped.filter((path) => /-lesson/.test(path))).toEqual([]);
    // No video of any kind: the characters' idle loops are not approved either (19 Nov 2026).
    expect(shipped.filter((path) => /\.(mp4|webm|mov)$/i.test(path))).toEqual(
      [],
    );
  });

  it("the dev workbench's copies stay out of git and so out of every build", () => {
    const ignored = readFileSync(join(REPO, ".gitignore"), "utf8").split("\n");
    expect(ignored).toContain(`/apps/sales-xray-web/public/${DEV_ONLY}/`);
  });
});
