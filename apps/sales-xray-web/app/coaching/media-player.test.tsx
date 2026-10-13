import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dipakTake, FocusHero } from "./coaching-ui";
import { CoachingMedia, requestClip } from "./media-player";
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
  vi.useRealTimers();
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
    expect(host.textContent).toContain("A stand-in voice reads Dipak’s words");
    expect(host.querySelector("audio")).toBeNull();
    expect(host.textContent).toContain("Find the consequence");
    await act(async () => button("Next slide").click());
    expect(host.textContent).toContain("Wait for their answer.");
    await act(async () => button("Previous slide").click());
    expect(host.textContent).toContain("Find the consequence");
    expect(host.textContent).toContain(fictionalClip.transcript_excerpt);
  });
  it("names whose focus the recommended lesson is for", async () => {
    const second = { ...fictionalClip, topic_id: "fictional-other-topic" };
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip, second]} />),
    );
    expect(host.textContent).toContain("Recommended for your current focus");
    expect(host.textContent).toContain("Also relevant");
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip, second]} forCall />),
    );
    expect(host.textContent).toContain("Recommended for this call’s focus");
    expect(host.textContent).not.toContain("your current focus");
    expect(host.textContent).toContain("Also relevant");
  });
  it("keeps only the recommendation open and preserves every secondary access rule", async () => {
    const preview = {
      ...fictionalClip,
      topic_id: "fictional-preview",
      title: "Another way to practise",
      access: "preview" as const,
      preview_end_ms: 3000,
    };
    const locked = {
      ...fictionalClip,
      topic_id: "fictional-locked",
      title: "Full coaching lesson",
      access: "locked" as const,
    };
    await act(async () =>
      root.render(
        <CoachingMedia
          clips={[fictionalClip, preview, locked]}
          headingLevel={4}
        />,
      ),
    );
    const disclosure = host.querySelector<HTMLDetailsElement>(
      "details[data-other-lessons]",
    )!;
    expect(disclosure.open).toBe(false);
    expect(disclosure.querySelector("summary")?.textContent).toBe(
      "More lessons · 2",
    );
    expect(
      [...disclosure.querySelectorAll("article")].map((card) => [
        card.querySelector("h4")?.textContent,
        card.getAttribute("data-access"),
      ]),
    ).toEqual([
      [preview.title, "preview"],
      [locked.title, "locked"],
    ]);
    expect(disclosure.textContent).toContain("Free preview · 0:02");
    expect(disclosure.textContent).toContain("Get the full coaching");
    expect(host.querySelector("audio")).toBeNull();
    expect(disclosure.querySelector("[data-recommended]")).toBeNull();
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    expect(host.querySelector("details[data-other-lessons]")).toBeNull();
    await act(async () => root.render(<CoachingMedia clips={[]} />));
    expect(host.textContent).toBe("");
  });
  it("reveals a requested secondary clip and folding pauses only that group", async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const second = { ...fictionalClip, topic_id: "fictional-secondary" };
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip, second]} />),
    );
    const disclosure = host.querySelector<HTMLDetailsElement>(
      "details[data-other-lessons]",
    )!;
    await act(async () => requestClip(second));
    expect(disclosure.open).toBe(true);
    expect(document.activeElement).toBe(disclosure.querySelector("button"));
    const audio = disclosure.querySelector("audio")!;
    expect(audio.getAttribute("src")).toBe(clipSource(second));
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    const pause = vi.spyOn(audio, "pause");
    const nested = disclosure.querySelector("details")!;
    await act(async () =>
      nested.dispatchEvent(new Event("toggle", { bubbles: true })),
    );
    expect(pause).not.toHaveBeenCalled();
    await act(async () => {
      disclosure.open = false;
      disclosure.dispatchEvent(new Event("toggle"));
    });
    expect(pause).toHaveBeenCalledOnce();
    expect(disclosure.textContent).toContain("Resume clip");
    await act(async () => requestClip(fictionalClip));
    const recommended = host.querySelector("[data-recommended]")!;
    const firstAudio = recommended.querySelector("audio")!;
    await act(async () =>
      firstAudio.dispatchEvent(new Event("loadedmetadata")),
    );
    const firstPause = vi.spyOn(firstAudio, "pause");
    firstPause.mockClear();
    await act(async () => disclosure.dispatchEvent(new Event("toggle")));
    expect(firstPause).not.toHaveBeenCalled();
    expect(recommended.textContent).toContain("Pause");
  });
  it("'Hear Dipak's take' focuses the recommended playback control and plays only once", async () => {
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
    hear.focus();
    await act(async () => hear.click());
    expect(scroll).toHaveBeenCalled();
    const playback = host.querySelector("[data-recommended] button")!;
    expect(document.activeElement).toBe(playback);
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(audio.play).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(playback);
    hear.focus();
    await act(async () => hear.click());
    expect(document.activeElement).toBe(playback);
    expect(audio.play).toHaveBeenCalledOnce();
    expect(host.querySelector("audio")).toBe(audio);
    // A request for an absent clip cannot move focus or start another source.
    hear.focus();
    await act(async () =>
      requestClip({ ...fictionalClip, topic_id: "not-on-this-page" }),
    );
    expect(document.activeElement).toBe(hear);
    expect(audio.play).toHaveBeenCalledOnce();
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
  it("times out missing narration metadata and retries without changing its allowed window", async () => {
    vi.useFakeTimers();
    const preview = {
      ...fictionalClip,
      access: "preview" as const,
      preview_end_ms: 3000,
    };
    await act(async () => root.render(<CoachingMedia clips={[preview]} />));
    await act(async () => button("Play coaching clip").click());
    const first = host.querySelector("audio")!;
    const source = first.getAttribute("src");
    await act(async () => vi.advanceTimersByTime(14_999));
    expect(button("Loading clip…").getAttribute("aria-disabled")).toBe("true");
    await act(async () => vi.advanceTimersByTime(1));
    expect(button("Try clip again").disabled).toBe(false);
    expect(host.querySelector("audio")).toBeNull();
    expect(host.textContent).toContain(preview.reason);
    expect(host.textContent).toContain(preview.transcript_excerpt);
    expect(host.textContent).toContain("Narration is unavailable");
    await act(async () => button("Try clip again").click());
    const retry = host.querySelector("audio")!;
    expect(retry).not.toBe(first);
    expect(retry.getAttribute("src")).toBe(source);
    await act(async () => retry.dispatchEvent(new Event("loadedmetadata")));
    expect(retry.currentTime).toBe(preview.start_ms / 1000);
    await act(async () => vi.advanceTimersByTime(16_000));
    expect(button("Pause")).toBeTruthy();
    expect(host.querySelector('[role="status"]')).toBeNull();
    retry.currentTime = preview.preview_end_ms / 1000;
    await act(async () => retry.dispatchEvent(new Event("timeupdate")));
    expect(button("Preview finished").disabled).toBe(true);
    expect(host.textContent).toContain("That’s the free preview");
  });
  it.each(["resolve", "reject"] as const)(
    "ignores a timed-out narration promise that later %ss during retry",
    async (outcome) => {
      vi.useFakeTimers();
      let settle!: () => void;
      vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
        () =>
          new Promise<void>((resolve, reject) => {
            settle =
              outcome === "resolve"
                ? resolve
                : () => reject(new Error("Late failure"));
          }),
      );
      await act(async () =>
        root.render(<CoachingMedia clips={[fictionalClip]} />),
      );
      await act(async () => button("Play coaching clip").click());
      const first = host.querySelector("audio")!;
      await act(async () => first.dispatchEvent(new Event("loadedmetadata")));
      await act(async () => vi.advanceTimersByTime(15_000));
      expect(button("Try clip again")).toBeTruthy();
      await act(async () => button("Try clip again").click());
      await act(async () => settle());
      expect(button("Loading clip…").getAttribute("aria-disabled")).toBe(
        "true",
      );
      await act(async () =>
        host.querySelector("audio")!.dispatchEvent(new Event("loadedmetadata")),
      );
      expect(button("Pause")).toBeTruthy();
    },
  );
  it.each(["timeout", "error"] as const)(
    "keeps narration retry focused after %s and leaves another control focused",
    async (failure) => {
      vi.useFakeTimers();
      HTMLElement.prototype.scrollIntoView = vi.fn();
      await act(async () =>
        root.render(<CoachingMedia clips={[fictionalClip]} />),
      );
      const play = button("Play coaching clip");
      play.focus();
      await act(async () => play.click());
      const audio = host.querySelector("audio")!;
      expect(play.disabled).toBe(false);
      expect(play.getAttribute("aria-disabled")).toBe("true");
      expect(document.activeElement).toBe(play);
      await act(async () => play.click());
      await act(async () => requestClip(fictionalClip));
      expect(host.querySelector("audio")).toBe(audio);
      expect(audio.play).not.toHaveBeenCalled();
      const fail = async () => {
        if (failure === "timeout")
          await act(async () => vi.advanceTimersByTime(15_000));
        else
          await act(async () =>
            host.querySelector("audio")!.dispatchEvent(new Event("error")),
          );
      };
      await fail();
      expect(button("Try clip again")).toBe(play);
      expect(play.getAttribute("aria-disabled")).toBeNull();
      expect(document.activeElement).toBe(play);
      const next = button("Next slide");
      await act(async () => play.click());
      next.focus();
      await fail();
      expect(document.activeElement).toBe(next);
    },
  );
  it("clears a narration startup deadline when another player starts or the card unmounts", async () => {
    vi.useFakeTimers();
    await act(async () =>
      root.render(<CoachingMedia clips={[fictionalClip]} />),
    );
    await act(async () => button("Play coaching clip").click());
    await act(async () =>
      window.dispatchEvent(
        new CustomEvent("sx-coaching-play", { detail: "another-player" }),
      ),
    );
    await act(async () => vi.advanceTimersByTime(16_000));
    expect(button("Resume clip")).toBeTruthy();
    expect(host.querySelector('[role="status"]')).toBeNull();
    vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
      () => new Promise<void>(() => {}),
    );
    await act(async () => button("Resume clip").click());
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.render(null));
    expect(vi.getTimerCount()).toBe(0);
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
  it.each(["another player", "folding"])(
    "keeps the exact narration position when interrupted by %s before the next timeupdate",
    async (interruption) => {
      const secondary = {
        ...fictionalClip,
        topic_id: "fictional-interrupted",
      };
      await act(async () =>
        root.render(<CoachingMedia clips={[fictionalClip, secondary]} />),
      );
      const disclosure = host.querySelector<HTMLDetailsElement>(
        "details[data-other-lessons]",
      )!;
      disclosure.open = true;
      const card = disclosure.querySelector("article")!;
      await act(async () =>
        card.querySelector<HTMLButtonElement>("button")!.click(),
      );
      const audio = card.querySelector("audio")!;
      await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
      // A switch/fold can arrive between the browser's timeupdate events and
      // before the periodic two-second device checkpoint.
      audio.currentTime = secondary.start_ms / 1000 + 1.25;
      vi.spyOn(audio, "pause").mockImplementation(() => {
        // Native playback can advance between a position read and pause().
        audio.currentTime += 0.001;
      });
      expect(window.localStorage.length).toBe(0);
      await act(async () => {
        if (interruption === "folding") {
          disclosure.open = false;
          disclosure.dispatchEvent(new Event("toggle"));
        } else {
          window.dispatchEvent(
            new CustomEvent("sx-coaching-play", { detail: "call-moment" }),
          );
        }
      });
      expect(audio.pause).toHaveBeenCalled();
      expect(card.textContent).toContain("Resume clip");
      const pausedAt = audio.currentTime;
      await act(async () => root.unmount());
      root = createRoot(host);
      await act(async () => root.render(<CoachingMedia clips={[secondary]} />));
      expect(host.querySelector("audio")).toBeNull();
      expect(button("Resume clip")).toBeTruthy();
      await act(async () => button("Resume clip").click());
      const resumed = host.querySelector("audio")!;
      expect(resumed.getAttribute("src")).toBe(clipSource(secondary));
      await act(async () => resumed.dispatchEvent(new Event("loadedmetadata")));
      expect(resumed.currentTime).toBe(pausedAt);
    },
  );
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
