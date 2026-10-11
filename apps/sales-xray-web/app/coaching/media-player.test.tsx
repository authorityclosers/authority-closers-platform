import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dipakTake, FocusHero } from "./coaching-ui";
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
  window.localStorage.clear();
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
    expect(host.textContent).toContain("Read by a stand-in voice");
    expect(host.querySelector("audio")).toBeNull();
    expect(host.textContent).toContain("Find the consequence");
    await act(async () => button("Next slide").click());
    expect(host.textContent).toContain("Wait for their answer.");
    await act(async () => button("Previous slide").click());
    expect(host.textContent).toContain("Find the consequence");
    expect(host.textContent).toContain(fictionalClip.transcript_excerpt);
  });
  it("'Hear Dipak's take' brings the recommended clip into view and plays it", async () => {
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    const take = dipakTake([fictionalClip]);
    await act(async () =>
      root.render(
        <>
          <FocusHero
            label="Focus"
            chips={[]}
            explanation="Explain."
            why="Why."
            reason="Reason."
            mission="Mission."
            missionAnchor="m"
            take={take}
          />
          <CoachingMedia clips={[fictionalClip]} />
        </>,
      ),
    );
    const hear = [...host.querySelectorAll("button")].find((b) =>
      b.textContent?.startsWith("Hear Dipak’s take"),
    )!;
    expect(hear.textContent).toBe("Hear Dipak’s take · 0:04");
    expect(host.querySelector("audio")).toBeNull();
    await act(async () => hear.click());
    expect(scroll).toHaveBeenCalled();
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(audio.play).toHaveBeenCalled();
    // A locked clip is never offered from the focus.
    expect(dipakTake([{ ...fictionalClip, access: "locked" }])).toBeNull();
    expect(dipakTake(undefined)).toBeNull();
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
  it("resumes where the learner stopped on a later visit", async () => {
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    await act(async () => button("Play coaching clip").click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    audio.currentTime = 3.5;
    await act(async () => audio.dispatchEvent(new Event("timeupdate")));
    await act(async () => button("Pause").click());
    await act(async () => root.unmount());
    root = createRoot(host);
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    expect(host.querySelector("audio")).toBeNull();
    expect(host.textContent).toContain("0:02");
    await act(async () => button("Resume clip").click());
    const next = host.querySelector("audio")!;
    await act(async () => next.dispatchEvent(new Event("loadedmetadata")));
    expect(next.currentTime).toBe(3.5);
    next.currentTime = 5;
    await act(async () => next.dispatchEvent(new Event("timeupdate")));
    expect(window.localStorage.length).toBe(0);
  });
  it("never restores a position outside the preview window", async () => {
    const [clip] = parseClips([
      {
        ...fictionalClip,
        access: "preview",
        entitlement_policy: "future-preview-plan",
        preview_end_ms: 3000,
      },
    ]);
    window.localStorage.setItem(
      `sx-coaching-clip:${clip.topic_id}:${clip.revision}:${clip.review_id}`,
      "2500",
    );
    await act(async () => root.render(<CoachingMedia clips={[clip]} />));
    expect(button("Play coaching clip")).toBeTruthy();
    await act(async () => button("Play coaching clip").click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(audio.currentTime).toBe(1);
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
  it("stops a preview where the server said and opens the full-coaching offer", async () => {
    const [clip] = parseClips([
      {
        ...fictionalClip,
        access: "preview",
        entitlement_policy: "future-preview-plan",
        preview_end_ms: 3000,
        offer: {
          full_coaching_href: "/plans",
          academy: {
            href: "https://learn.authorityclosers.com/courses/impact",
            label: "Impact before solution",
          },
        },
      },
    ]);
    expect(clip.preview_end_ms).toBe(3000);
    await act(async () => root.render(<CoachingMedia clips={[clip]} />));
    expect(host.textContent).toContain("Free preview · 0:02");
    expect(host.textContent).not.toContain("Get the full coaching");
    await act(async () => button("Play coaching clip").click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    audio.currentTime = 3;
    await act(async () => audio.dispatchEvent(new Event("timeupdate")));
    expect(audio.pause).toHaveBeenCalled();
    expect(host.textContent).toContain("That’s the free preview");
    const links = [...host.querySelectorAll<HTMLAnchorElement>("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/plans",
      "https://learn.authorityclosers.com/courses/impact",
    ]);
    expect(button("Preview finished").disabled).toBe(true);
  });
  it("shows a locked clip's offer without loading audio or its transcript", async () => {
    const [clip] = parseClips([
      {
        ...fictionalClip,
        access: "locked",
        entitlement_policy: "future-preview-plan",
        offer: {
          full_coaching_href: "https://pay.example.test/checkout",
          academy: { href: "https://evil.example.test/", label: "Course" },
        },
      },
    ]);
    await act(async () => root.render(<CoachingMedia clips={[clip]} />));
    expect(host.textContent).toContain("Part of Dipak’s full coaching");
    expect(host.textContent).not.toContain(fictionalClip.transcript_excerpt);
    // Unsafe destinations fall back to the app's own offer; no foreign link.
    expect(
      [...host.querySelectorAll<HTMLAnchorElement>("a")].map((a) =>
        a.getAttribute("href"),
      ),
    ).toEqual(["/plans"]);
    await act(async () => button("Locked coaching clip").click());
    expect(host.querySelector("audio")).toBeNull();
  });
  it("never accepts a full clip outside the open Coaching policy or a bad preview", () => {
    expect(
      parseClips([{ ...fictionalClip, entitlement_policy: "paid-plan" }]),
    ).toEqual([]);
    for (const preview_end_ms of [undefined, 1000, 5000, 9000, 2.5])
      expect(
        parseClips([
          {
            ...fictionalClip,
            access: "preview",
            entitlement_policy: "plan",
            preview_end_ms,
          },
        ]),
      ).toEqual([]);
  });
});
