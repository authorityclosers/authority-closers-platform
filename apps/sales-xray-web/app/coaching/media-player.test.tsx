import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CoachingMedia } from "./media-player";
import { parseClips, clipSource } from "./media-contract";
import { fictionalClip } from "./coaching.fixture";

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === name,
  )!;
describe("reviewed placeholder clips", () => {
  it("drops malformed media without crashing the text lesson", () => {
    expect(parseClips(undefined)).toEqual([]);
    for (const change of [
      { url: "https://untrusted.test" },
      { voice: "dipak" },
      { placeholder: false },
      { topic_id: "../../private" },
      { access: "preview" },
      { end_ms: 500 },
      { slides: [{}] },
    ]) {
      expect(parseClips([{ ...fictionalClip, ...change }])).toEqual([]);
    }
    expect(parseClips([fictionalClip])).toEqual([fictionalClip]);
    expect(clipSource(fictionalClip)).toMatch(
      /^\/v1\/me\/coaching\/media\/fictional-impact\//,
    );
  });
  it("labels narration, keeps slides interactive and fetches no eager audio", async () => {
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    expect(host.textContent).toContain("Placeholder · neutral narration");
    expect(host.querySelector("audio")).toBeNull();
    expect(host.textContent).toContain("Find the consequence");
    await act(async () => button("Next slide").click());
    expect(host.textContent).toContain("Wait for their answer.");
    await act(async () => button("Previous slide").click());
    expect(host.textContent).toContain("Find the consequence");
    expect(host.textContent).toContain(fictionalClip.transcript_excerpt);
  });
  it("plays exact timestamps, stops the clip and retries failed source", async () => {
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    await act(async () => button("Play coaching clip").click());
    const audio = host.querySelector("audio")!;
    expect(audio.getAttribute("src")).toBe(clipSource(fictionalClip));
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(audio.currentTime).toBe(1);
    expect(audio.play).toHaveBeenCalled();
    expect(button("Pause")).toBeTruthy();
    audio.currentTime = 5;
    await act(async () => audio.dispatchEvent(new Event("timeupdate")));
    expect(audio.pause).toHaveBeenCalled();
    expect(button("Play again")).toBeTruthy();
    await act(async () => audio.dispatchEvent(new Event("error")));
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      "Narration is unavailable",
    );
    await act(async () => button("Try clip again").click());
    expect(host.querySelector("audio")).not.toBe(audio);
  });
  it("pauses narration when another coaching player takes over", async () => {
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    await act(async () => button("Play coaching clip").click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(button("Pause")).toBeTruthy();
    await act(async () =>
      window.dispatchEvent(
        new CustomEvent("sx-coaching-play", { detail: "other-player" }),
      ),
    );
    expect(button("Pause")).toBeUndefined();
    expect(audio.pause).toHaveBeenCalled();
  });
});
