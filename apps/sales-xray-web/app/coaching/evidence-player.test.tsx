import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fictionalCoaching } from "./coaching.fixture";
import { clipLength, EvidencePlayer, MomentList } from "./evidence-player";

let root: Root, host: HTMLDivElement;
const evidence = fictionalCoaching.evidence[0];
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
  vi.useRealTimers();
});
describe("Evidence playback", () => {
  it("unfolds the full quote without changing its source or starting playback", async () => {
    const quote = "One fictional seller's full monologue. ".repeat(24);
    const long = Object.freeze({ ...evidence, quote });
    const onPlay = vi.fn();
    await act(async () =>
      root.render(<EvidencePlayer evidence={long} onPlay={onPlay} />),
    );
    const words = host.querySelector("blockquote")!;
    const toggle = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (button) => button.textContent === "Read full quote",
    )!;
    expect(words.textContent).toBe(quote);
    expect(words.hasAttribute("data-folded")).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.getAttribute("aria-controls")).toBe(words.id);
    await act(async () => toggle.click());
    expect(words.hasAttribute("data-folded")).toBe(false);
    expect(words.textContent).toBe(quote);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.textContent).toBe("Show less");
    expect(onPlay).not.toHaveBeenCalled();
    expect(host.querySelector("audio")).toBeNull();
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>('button[aria-label^="Play moment"]')!
        .click(),
    );
    expect(onPlay).toHaveBeenCalledWith(long, "Coaching for this call");
    await act(async () => toggle.click());
    expect(words.hasAttribute("data-folded")).toBe(true);
    expect(words.textContent).toBe(quote);
    // A later retained/withheld read replaces the words even after expansion.
    await act(async () =>
      root.render(
        <EvidencePlayer
          evidence={{ ...long, quote: "[Withheld]" }}
          onPlay={onPlay}
        />,
      ),
    );
    expect(host.textContent).not.toContain(quote);
    expect(host.querySelector("blockquote")?.textContent).toBe("[Withheld]");
  });
  it("loads only on click, seeks to the bound timestamp and pauses at the excerpt end", async () => {
    await act(async () => root.render(<EvidencePlayer evidence={evidence} />));
    expect(host.querySelector("audio")).toBeNull();
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    const audio = host.querySelector("audio")!;
    expect(audio.getAttribute("src")).toBe(
      `/v1/conversation/acquisition/submissions/${evidence.submission_id}/source`,
    );
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(audio.currentTime).toBe(evidence.start_ms / 1000);
    expect(audio.play).toHaveBeenCalledOnce();
    audio.currentTime = evidence.end_ms / 1000;
    await act(async () => audio.dispatchEvent(new Event("timeupdate")));
    expect(audio.pause).toHaveBeenCalledOnce();
  });
  it("names the clip length and shows how far into the clip playback is", async () => {
    const clip = { ...evidence, start_ms: 60_000, end_ms: 75_000 };
    await act(async () => root.render(<EvidencePlayer evidence={clip} />));
    expect(host.textContent).toContain("1:00–1:15 · 15 s clip");
    const button = host.querySelector<HTMLButtonElement>("button")!;
    await act(async () => button.click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(button.dataset.state).toBe("playing");
    audio.currentTime = 66;
    await act(async () => audio.dispatchEvent(new Event("timeupdate")));
    expect(button.style.getPropertyValue("--clip")).toBe("40%");
    expect(clipLength(65_000)).toBe("1 min 5 s");
    expect(clipLength(120_000)).toBe("2 min");
    expect(clipLength(200)).toBe("1 s");
  });
  it.each(["playing", "loading"] as const)(
    "returns from %s to one-click replay when the recording ends before the excerpt",
    async (state) => {
      vi.useFakeTimers();
      let resolvePlay: () => void = () => {};
      if (state === "loading")
        vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
          () => new Promise<void>((resolve) => (resolvePlay = resolve)),
        );
      await act(async () =>
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      const play = host.querySelector<HTMLButtonElement>("button")!;
      await act(async () => play.click());
      const audio = host.querySelector("audio")!;
      const source = audio.getAttribute("src");
      await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
      expect(play.dataset.state).toBe(state);
      audio.currentTime = evidence.end_ms / 1000 - 1;
      await act(async () => audio.dispatchEvent(new Event("ended")));
      await act(async () => resolvePlay());
      expect(play.dataset.state).toBe("idle");
      expect(play.disabled).toBe(false);
      expect(play.getAttribute("aria-label")).toMatch(/^Play moment /);
      expect(vi.getTimerCount()).toBe(0);
      expect(host.querySelector("blockquote")?.textContent).toBe(
        evidence.quote,
      );
      expect(audio.getAttribute("src")).toBe(source);
      await act(async () => play.click());
      expect(host.querySelector("audio")).toBe(audio);
      expect(audio.currentTime).toBe(evidence.start_ms / 1000);
      expect(audio.play).toHaveBeenCalledTimes(2);
      expect(play.dataset.state).toBe("playing");
    },
  );
  it("offers a retry after a source failure and leaves the transcript inspectable", async () => {
    await act(async () => root.render(<EvidencePlayer evidence={evidence} />));
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    const first = host.querySelector("audio")!;
    await act(async () => first.dispatchEvent(new Event("error")));
    expect(host.textContent).toContain("Try audio again");
    expect(host.textContent).toContain(evidence.quote);
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(host.querySelector("audio")).not.toBe(first);
  });
  it("times out missing metadata, keeps the source words and retries the same moment", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<EvidencePlayer evidence={evidence} />));
    const play = host.querySelector<HTMLButtonElement>("button")!;
    await act(async () => play.click());
    const first = host.querySelector("audio")!;
    const source = first.getAttribute("src");
    await act(async () => vi.advanceTimersByTime(14_999));
    expect(play.getAttribute("aria-disabled")).toBe("true");
    await act(async () => vi.advanceTimersByTime(1));
    expect(play.disabled).toBe(false);
    expect(play.getAttribute("aria-label")).toMatch(/^Try audio again /);
    expect(host.textContent).toContain(evidence.quote);
    expect(host.textContent).toContain("the quote stays here");
    expect(host.querySelector("audio")).toBeNull();
    expect(first.pause).toHaveBeenCalled();
    await act(async () => play.click());
    const retry = host.querySelector("audio")!;
    expect(retry).not.toBe(first);
    expect(retry.getAttribute("src")).toBe(source);
    await act(async () => retry.dispatchEvent(new Event("loadedmetadata")));
    expect(retry.currentTime).toBe(evidence.start_ms / 1000);
    await act(async () => vi.advanceTimersByTime(16_000));
    expect(play.dataset.state).toBe("playing");
    expect(host.querySelector('[role="status"]')).toBeNull();
  });
  it.each(["resolve", "reject"] as const)(
    "ignores a timed-out play promise that later %ss during a fresh retry",
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
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      const play = host.querySelector<HTMLButtonElement>("button")!;
      await act(async () => play.click());
      const first = host.querySelector("audio")!;
      await act(async () => first.dispatchEvent(new Event("loadedmetadata")));
      await act(async () => vi.advanceTimersByTime(15_000));
      expect(play.dataset.state).toBe("failed");
      await act(async () => play.click());
      await act(async () => settle());
      expect(play.dataset.state).toBe("loading");
      const retry = host.querySelector("audio")!;
      await act(async () => retry.dispatchEvent(new Event("loadedmetadata")));
      expect(play.dataset.state).toBe("playing");
    },
  );
  it.each(["switch", "timeout", "leaving"] as const)(
    "stops a late successful moment start after %s",
    async (interruption) => {
      vi.useFakeTimers();
      let finish!: () => void;
      vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
        () => new Promise<void>((resolve) => (finish = resolve)),
      );
      await act(async () =>
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      const play = host.querySelector<HTMLButtonElement>("button")!;
      await act(async () => play.click());
      const first = host.querySelector("audio")!;
      await act(async () => first.dispatchEvent(new Event("loadedmetadata")));
      if (interruption === "leaving") await act(async () => root.render(null));
      else if (interruption === "timeout") {
        await act(async () => vi.advanceTimersByTime(15_000));
        await act(async () => play.click());
        await act(async () =>
          host
            .querySelector("audio")!
            .dispatchEvent(new Event("loadedmetadata")),
        );
      } else
        await act(async () =>
          window.dispatchEvent(
            new CustomEvent("sx-coaching-play", { detail: "another-player" }),
          ),
        );
      const state = play.dataset.state;
      const words = host.textContent;
      const pause = vi.spyOn(first, "pause").mockClear();
      await act(async () => finish());
      expect(pause).toHaveBeenCalledOnce();
      expect(play.dataset.state).toBe(state);
      expect(host.textContent).toBe(words);
      if (interruption === "timeout") expect(state).toBe("playing");
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it("a late moment result leaves a newer replay on the same audio playing", async () => {
    let finish!: () => void;
    vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
      () => new Promise<void>((resolve) => (finish = resolve)),
    );
    await act(async () => root.render(<EvidencePlayer evidence={evidence} />));
    const play = host.querySelector<HTMLButtonElement>("button")!;
    await act(async () => play.click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    await act(async () =>
      window.dispatchEvent(
        new CustomEvent("sx-coaching-play", { detail: "another-player" }),
      ),
    );
    await act(async () => play.click());
    expect(host.querySelector("audio")).toBe(audio);
    expect(play.dataset.state).toBe("playing");
    const pause = vi.spyOn(audio, "pause").mockClear();
    await act(async () => finish());
    expect(pause).not.toHaveBeenCalled();
    expect(play.dataset.state).toBe("playing");
  });
  it.each(["timeout", "error"] as const)(
    "keeps keyboard focus on retry after %s, without blocking focus elsewhere",
    async (failure) => {
      vi.useFakeTimers();
      await act(async () =>
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      const play = host.querySelector<HTMLButtonElement>("button")!;
      play.focus();
      await act(async () => play.click());
      const audio = host.querySelector("audio")!;
      expect(play.disabled).toBe(false);
      expect(play.getAttribute("aria-disabled")).toBe("true");
      expect(document.activeElement).toBe(play);
      // A second activation while loading keeps the source and deadline.
      await act(async () => play.click());
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
      expect(play.getAttribute("aria-disabled")).toBeNull();
      expect(play.getAttribute("aria-label")).toMatch(/^Try audio again /);
      expect(document.activeElement).toBe(play);
      const call = host.querySelector<HTMLAnchorElement>("a")!;
      await act(async () => play.click());
      call.focus();
      await fail();
      expect(document.activeElement).toBe(call);
    },
  );
  it("clears the startup deadline on switch and unmount", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<EvidencePlayer evidence={evidence} />));
    const play = host.querySelector<HTMLButtonElement>("button")!;
    await act(async () => play.click());
    await act(async () =>
      window.dispatchEvent(
        new CustomEvent("sx-coaching-play", { detail: "another-player" }),
      ),
    );
    await act(async () => vi.advanceTimersByTime(16_000));
    expect(play.dataset.state).toBe("idle");
    expect(host.querySelector('[role="status"]')).toBeNull();
    vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
      () => new Promise<void>(() => {}),
    );
    await act(async () => play.click());
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.render(null));
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["playing", "loading"] as const)(
    "pauses a %s call moment before its view removes the audio",
    async (state) => {
      vi.useFakeTimers();
      let resolvePlay = () => {};
      if (state === "loading")
        vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(
          () => new Promise<void>((resolve) => (resolvePlay = resolve)),
        );
      await act(async () =>
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      const play = host.querySelector<HTMLButtonElement>("button")!;
      await act(async () => play.click());
      const audio = host.querySelector("audio")!;
      await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
      expect(play.dataset.state).toBe(state);
      await act(async () => root.render(null));
      expect(audio.pause).toHaveBeenCalledOnce();
      expect(host.querySelector("audio")).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
      // A late startup completion cannot bring the detached player back.
      await act(async () => resolvePlay());
      expect(host.textContent).toBe("");
      await act(async () =>
        root.render(<EvidencePlayer evidence={evidence} />),
      );
      expect(host.querySelector("audio")).toBeNull();
      expect(host.querySelector("blockquote")?.textContent).toBe(
        evidence.quote,
      );
      await act(async () =>
        host.querySelector<HTMLButtonElement>("button")!.click(),
      );
      const next = host.querySelector("audio")!;
      await act(async () => next.dispatchEvent(new Event("loadedmetadata")));
      expect(next.currentTime).toBe(evidence.start_ms / 1000);
      expect(next.getAttribute("src")).toBe(audio.getAttribute("src"));
    },
  );
  it("keeps Strict Mode startup active and pauses the moment when its view closes", async () => {
    await act(async () =>
      root.render(
        <StrictMode>
          <EvidencePlayer evidence={evidence} />
        </StrictMode>,
      ),
    );
    const play = host.querySelector<HTMLButtonElement>("button")!;
    await act(async () => play.click());
    const audio = host.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(play.dataset.state).toBe("playing");
    expect(audio.play).toHaveBeenCalledOnce();
    expect(audio.pause).not.toHaveBeenCalled();
    await act(async () => root.render(null));
    expect(audio.pause).toHaveBeenCalledOnce();
  });
  it("stops the previous moment when another evidence card starts", async () => {
    await act(async () =>
      root.render(
        <>
          <EvidencePlayer evidence={evidence} />
          <EvidencePlayer evidence={fictionalCoaching.evidence[1]} />
        </>,
      ),
    );
    const buttons = host.querySelectorAll<HTMLButtonElement>("button");
    await act(async () => buttons[0].click());
    const first = host.querySelector("audio")!;
    await act(async () => first.dispatchEvent(new Event("loadedmetadata")));
    await act(async () => buttons[1].click());
    expect(first.pause).toHaveBeenCalledOnce();
  });
  it("opens and folds the moments without losing sources, pauses their clip and returns focus", async () => {
    const four = [0, 1, 2, 3].map((index) => ({
      ...evidence,
      segment_id: `segment-${index}`,
      start_ms: 1000 + index * 5000,
      end_ms: 4000 + index * 5000,
    }));
    await act(async () => root.render(<MomentList evidence={four} />));
    const list = host.querySelector("ul")!;
    expect(list.querySelectorAll("li")).toHaveLength(4);
    expect(list.querySelectorAll("li[data-extra]")).toHaveLength(3);
    expect(list.hasAttribute("data-expanded")).toBe(false);
    const more = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Show all 4 moments",
    )!;
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(more.getAttribute("aria-controls")).toBe(list.id);
    const sources = [...list.querySelectorAll("li")].map((row) => ({
      quote: row.querySelector("blockquote")!.textContent,
      time: row.querySelector("button")!.getAttribute("aria-label"),
      href: row.querySelector("a")!.getAttribute("href"),
    }));
    await act(async () => more.click());
    expect(list.hasAttribute("data-expanded")).toBe(true);
    expect(host.textContent).not.toContain("Show all 4 moments");
    expect(more.textContent).toBe("Show fewer moments");
    expect(more.getAttribute("aria-expanded")).toBe("true");
    const extra = list
      .querySelectorAll("li")[3]
      .querySelector<HTMLButtonElement>('button[aria-label^="Play moment"]')!;
    await act(async () => extra.click());
    const audio = list.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    expect(extra.getAttribute("aria-label")).toMatch(/^Pause moment /);
    vi.mocked(audio.pause).mockClear();
    await act(async () => more.click());
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(extra.getAttribute("aria-label")).toMatch(/^Play moment /);
    expect(list.hasAttribute("data-expanded")).toBe(false);
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(more.textContent).toBe("Show all 4 moments");
    expect(document.activeElement).toBe(list);
    expect(
      [...list.querySelectorAll("li")].map((row) => ({
        quote: row.querySelector("blockquote")!.textContent,
        time: row.querySelector("button")!.getAttribute("aria-label"),
        href: row.querySelector("a")!.getAttribute("href"),
      })),
    ).toEqual(sources);
    await act(async () => more.click());
    expect(list.hasAttribute("data-expanded")).toBe(true);
    expect(list.querySelectorAll("li")).toHaveLength(4);
  });
  it("folding one list leaves another list's playing clip alone", async () => {
    await act(async () =>
      root.render(
        <>
          <MomentList evidence={fictionalCoaching.evidence} label="First" />
          <MomentList evidence={fictionalCoaching.evidence} label="Second" />
        </>,
      ),
    );
    const first = host.querySelector<HTMLUListElement>(
      'ul[aria-label="First"]',
    )!;
    const second = host.querySelector<HTMLUListElement>(
      'ul[aria-label="Second"]',
    )!;
    const fold = first.nextElementSibling as HTMLButtonElement;
    await act(async () => fold.click());
    await act(async () =>
      second
        .querySelector<HTMLButtonElement>('button[aria-label^="Play moment"]')!
        .click(),
    );
    const audio = second.querySelector("audio")!;
    await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
    vi.mocked(audio.pause).mockClear();
    await act(async () => fold.click());
    expect(audio.pause).not.toHaveBeenCalled();
    expect(
      second.querySelector('button[aria-label^="Pause moment"]'),
    ).not.toBeNull();
  });
  it("needs no fold for one moment", async () => {
    await act(async () =>
      root.render(
        <MomentList evidence={fictionalCoaching.evidence.slice(0, 1)} />,
      ),
    );
    expect(host.textContent).not.toContain("Show all");
  });
});
