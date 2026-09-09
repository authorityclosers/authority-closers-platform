// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VideoPlaybackSurface } from "./video-playback-surface";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
let activate: ReturnType<typeof vi.fn<() => void>>;
beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  activate = vi.fn();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
async function render(
  overrides: Partial<Parameters<typeof VideoPlaybackSurface>[0]> = {},
) {
  await act(async () =>
    root.render(
      <VideoPlaybackSurface
        isPlaying={false}
        hasEnded={false}
        blocked={false}
        onActivate={activate}
        {...overrides}
      />,
    ),
  );
  return container.querySelector("button")!;
}
async function pointer(button: HTMLButtonElement, pointerType: string) {
  await act(async () => {
    button.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerType,
        isPrimary: true,
      }),
    );
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
  });
}

describe("direct video surface", () => {
  it("uses one native labelled button for start, pause and replay", async () => {
    expect((await render()).getAttribute("aria-label")).toBe("Start video");
    expect((await render({ isPlaying: true })).getAttribute("aria-label")).toBe(
      "Pause video",
    );
    expect(
      container.querySelector(".momentum-video-player__center-play"),
    ).toBeNull();
    expect((await render({ hasEnded: true })).getAttribute("aria-label")).toBe(
      "Replay video",
    );
  });

  it.each(["touch", "pen", "mouse"])(
    "activates %s synchronously, with no deferred gesture",
    async (type) => {
      await pointer(await render(), type);
      expect(activate).toHaveBeenCalledTimes(1);
      await act(async () => vi.advanceTimersByTime(1000));
      expect(activate).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("activates keyboard/assistive clicks immediately", async () => {
    const button = await render();
    await act(async () => button.click());
    expect(activate).toHaveBeenCalledTimes(1);
  });

  it.each(["touch", "mouse"])(
    "only dismisses a panel on %s, even when pointerdown closes it before click",
    async (type) => {
      const button = await render({ blocked: true });
      await act(async () =>
        button.dispatchEvent(
          new PointerEvent("pointerdown", {
            bubbles: true,
            pointerType: type,
            isPrimary: true,
          }),
        ),
      );
      await render({ blocked: false });
      await act(async () =>
        button.dispatchEvent(
          new MouseEvent("click", { bubbles: true, detail: 1 }),
        ),
      );
      expect(activate).not.toHaveBeenCalled();
      await pointer(button, type);
      expect(activate).toHaveBeenCalledTimes(1);
    },
  );

  it("does not activate after a cancelled scroll/pointer gesture", async () => {
    const button = await render();
    await act(async () => {
      button.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          pointerType: "touch",
          isPrimary: true,
        }),
      );
      button.dispatchEvent(
        new PointerEvent("pointercancel", { bubbles: true }),
      );
      button.dispatchEvent(
        new MouseEvent("click", { bubbles: true, detail: 1 }),
      );
    });
    expect(activate).not.toHaveBeenCalled();
  });

  it("does not activate a secondary pointer", async () => {
    const button = await render();
    await act(async () => {
      button.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          pointerType: "touch",
          isPrimary: false,
        }),
      );
      button.dispatchEvent(
        new MouseEvent("click", { bubbles: true, detail: 1 }),
      );
    });
    expect(activate).not.toHaveBeenCalled();
  });

  it("refuses all activation while playback or a panel blocks it", async () => {
    const button = await render({ blocked: true });
    await pointer(button, "touch");
    await act(async () => button.click());
    expect(activate).not.toHaveBeenCalled();
  });
});
