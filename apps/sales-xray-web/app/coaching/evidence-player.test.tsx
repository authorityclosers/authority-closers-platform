import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fictionalCoaching } from "./coaching.fixture";
import { EvidencePlayer } from "./evidence-player";

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
});
