import { act } from "react";
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
  it("folds moments after the first until the learner asks for all", async () => {
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
    await act(async () => more.click());
    expect(list.hasAttribute("data-expanded")).toBe(true);
    expect(host.textContent).not.toContain("Show all 4 moments");
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
