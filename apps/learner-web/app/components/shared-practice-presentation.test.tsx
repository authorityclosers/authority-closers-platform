// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { URL as NodeURL } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import {
  PRACTICE_COMPANIONS,
  PracticeCompanion,
  normalizePracticeCompanion,
  RewardReveal,
  type PracticeCompanionMood,
} from "@ac/ui";
import companionStyles from "../../../../packages/typescript/ui/src/practice-companion.module.css";
import rewardStyles from "../../../../packages/typescript/ui/src/reward-reveal.module.css";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PracticeCompanionStage } from "./practice-companion-stage";

const mounted: Element[] = [];
const reactRoots: Root[] = [];
const originalMotion = document.documentElement.getAttribute("data-motion");
const originalReduced = document.documentElement.getAttribute(
  "data-reduced-motion",
);
const originalCharacterMotion = localStorage.getItem(
  "ac-practice-companion-motion",
);
const restoreAttribute = (name: string, value: string | null) => {
  if (value === null) document.documentElement.removeAttribute(name);
  else document.documentElement.setAttribute(name, value);
};
afterEach(async () => {
  for (const root of reactRoots.splice(0)) await act(() => root.unmount());
  for (const element of mounted.splice(0)) element.remove();
  restoreAttribute("data-motion", originalMotion);
  restoreAttribute("data-reduced-motion", originalReduced);
  if (originalCharacterMotion === null)
    localStorage.removeItem("ac-practice-companion-motion");
  else
    localStorage.setItem(
      "ac-practice-companion-motion",
      originalCharacterMotion,
    );
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function render(content: ReactNode) {
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(content);
  document.body.append(root);
  mounted.push(root);
  return root;
}

/** Select a media environment, then let the DOM's actual CSS cascade resolve
 * matching selectors, specificity and !important against the rendered markup.
 * This is a source-level cascade contract, not a browser animation simulation. */
function stylesFor(
  filename: string,
  classes: Record<string, string>,
  reduced = false,
) {
  const css = readFileSync(
    new NodeURL(
      `../../../../packages/typescript/ui/src/${filename}`,
      import.meta.url,
    ),
    "utf8",
  );
  const parsed = new CSSStyleSheet();
  parsed.replaceSync(css.replace(/:global\(([^)]+)\)/g, "$1"));
  const selected = (rules: CSSRuleList): string[] =>
    Array.from(rules).flatMap((rule) => {
      if (rule instanceof CSSMediaRule) {
        return rule.conditionText.replace(/\s+/g, "") ===
          "(prefers-reduced-motion:reduce)" && reduced
          ? selected(rule.cssRules)
          : [];
      }
      return [rule.cssText];
    });
  let compiled = selected(parsed.cssRules).join("\n");
  // Vitest's CSS-module export can be a lazy proxy, so enumerate the parsed
  // source selectors rather than assuming Object.entries exposes its keys.
  const classNames = new Set(
    Array.from(css.matchAll(/\.([A-Za-z_][\w-]*)/g), (match) => match[1]),
  );
  for (const name of classNames) {
    const generated = classes[name];
    if (!generated) continue;
    compiled = compiled.replace(
      new RegExp(`\\.${name}(?=[\\s.#[:>+~,{]|$)`, "g"),
      `.${generated}`,
    );
  }
  const style = document.createElement("style");
  style.textContent = compiled;
  document.head.append(style);
  mounted.push(style);
}
const animations = (root: Element) =>
  [root, ...root.querySelectorAll("*")]
    .map((element) => getComputedStyle(element).getPropertyValue("animation"))
    .filter((animation) => animation && animation !== "none");

describe("PracticeCompanion shared presentation", () => {
  it("provides unique named presets and preserves each registered choice", () => {
    expect(PRACTICE_COMPANIONS.map((entry) => entry.id)).toEqual([
      "echo",
      "scout",
      "page",
    ]);
    expect(new Set(PRACTICE_COMPANIONS.map((entry) => entry.id)).size).toBe(
      PRACTICE_COMPANIONS.length,
    );
    const geometry = new Set<string>();
    for (const entry of PRACTICE_COMPANIONS) {
      expect(entry.name.trim()).not.toBe("");
      expect(entry.description.trim()).not.toBe("");
      expect(normalizePracticeCompanion(entry.id)).toBe(entry.id);
      const svg = render(
        <PracticeCompanion variant={entry.id} />,
      ).querySelector("svg")!;
      expect(svg.dataset.companion).toBe(entry.id);
      geometry.add(
        Array.from(svg.querySelectorAll("path,rect"))
          .map((element) =>
            JSON.stringify(
              Array.from(element.attributes)
                .filter((attribute) => attribute.name !== "class")
                .map((attribute) => [attribute.name, attribute.value]),
            ),
          )
          .join("|"),
      );
    }
    expect(geometry.size).toBe(PRACTICE_COMPANIONS.length);
  });

  it.each([
    undefined,
    null,
    "",
    "ECHO",
    "unknown",
    "__proto__",
    0,
    false,
    {},
    ["scout"],
  ])("falls back to Echo for unrecognized persisted input %j", (value) =>
    expect(normalizePracticeCompanion(value)).toBe("echo"),
  );

  it("is decorative by default and exposes only an explicit accessible label", () => {
    const decorative = render(<PracticeCompanion />).querySelector("svg")!;
    expect(decorative.getAttribute("aria-hidden")).toBe("true");
    expect(decorative.hasAttribute("aria-label")).toBe(false);
    expect(decorative.hasAttribute("role")).toBe(false);
    expect(decorative.getAttribute("focusable")).toBe("false");
    const labelled = render(
      <PracticeCompanion label="Echo is ready to practise" />,
    ).querySelector("svg")!;
    expect(labelled.getAttribute("role")).toBe("img");
    expect(labelled.getAttribute("aria-label")).toBe(
      "Echo is ready to practise",
    );
    expect(labelled.hasAttribute("aria-hidden")).toBe(false);
    expect(labelled.getAttribute("focusable")).toBe("false");
  });

  it.each([
    "ready",
    "encourage",
    "celebrate",
    "pause",
  ] as PracticeCompanionMood[])(
    "renders %s as inert vector presentation without claiming rewards",
    (mood) => {
      const root = render(<PracticeCompanion mood={mood} size={90} />);
      const svg = root.querySelector("svg")!;
      expect(svg.dataset.mood).toBe(mood);
      expect(svg.getAttribute("viewBox")).toBe("0 0 180 160");
      expect(Number(svg.getAttribute("width"))).toBe(90);
      expect(Number(svg.getAttribute("height"))).toBe(80);
      expect(
        root.querySelectorAll("script,image,use,foreignObject,a,[tabindex]"),
      ).toHaveLength(0);
      expect(root.textContent).toBe("");
    },
  );

  it("bounds default entrance and mood animations without infinite loops", () => {
    stylesFor("practice-companion.module.css", companionStyles);
    for (const mood of ["ready", "encourage", "celebrate", "pause"] as const) {
      const active = animations(render(<PracticeCompanion mood={mood} />));
      expect(active.length).toBeGreaterThan(0);
      for (const value of active) expect(value).not.toContain("infinite");
    }
  });
  it("requires explicit alive motion for continuous layers and pauses them in server markup", () => {
    stylesFor("practice-companion.module.css", companionStyles);
    const root = render(<PracticeCompanion motion="alive" />);
    expect(root.querySelector("svg")?.dataset.play).toBe("paused");
    expect(animations(root).some((value) => value.includes("infinite"))).toBe(
      true,
    );
    for (const element of root.querySelectorAll("svg *")) {
      expect(
        getComputedStyle(element).getPropertyValue("animation-play-state"),
      ).toBe("paused");
    }
  });
  it("removes every animation and transition for explicit motion off", () => {
    stylesFor("practice-companion.module.css", companionStyles);
    for (const mood of ["ready", "encourage", "celebrate", "pause"] as const) {
      const root = render(<PracticeCompanion motion="off" mood={mood} />);
      expect(animations(root)).toHaveLength(0);
      for (const element of root.querySelectorAll("svg *")) {
        expect(getComputedStyle(element).getPropertyValue("transition")).toBe(
          "none",
        );
      }
    }
  });
});

/** Browser lifecycle signals are controlled here; assertions observe the actual
 * mounted component's play gate and gaze styles, not private React state. */
function motionEnvironment() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  let reduced = false;
  const media = new EventTarget();
  Object.defineProperty(media, "matches", { get: () => reduced });
  const mediaRemove = vi.spyOn(media, "removeEventListener");
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  const intersections: {
    callback: IntersectionObserverCallback;
    observe: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }[] = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
      constructor(callback: IntersectionObserverCallback) {
        intersections.push({
          callback,
          observe: this.observe,
          disconnect: this.disconnect,
        });
      }
    },
  );
  let nextFrame = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const requestFrame = vi.fn((callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  });
  const cancelFrame = vi.fn((frame: number) => {
    frames.delete(frame);
  });
  vi.stubGlobal("requestAnimationFrame", requestFrame);
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  return {
    intersections,
    frames,
    requestFrame,
    cancelFrame,
    mediaRemove,
    intersect(value: boolean) {
      const latest = intersections.at(-1)!;
      latest.callback(
        [{ isIntersecting: value } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    },
    reduced(value: boolean) {
      reduced = value;
      media.dispatchEvent(new Event("change"));
    },
    visibility(value: DocumentVisibilityState) {
      visibility.mockReturnValue(value);
      document.dispatchEvent(new Event("visibilitychange"));
    },
    flushFrames() {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback(0);
    },
  };
}
async function mountCompanion(content: ReactNode) {
  const host = document.createElement("div");
  document.body.append(host);
  mounted.push(host);
  const root = createRoot(host);
  reactRoots.push(root);
  await act(() => root.render(content));
  return { host, root, svg: host.querySelector("svg")! };
}
function pointer(clientX: number, clientY: number, pointerType = "mouse") {
  document.dispatchEvent(
    new PointerEvent("pointermove", { clientX, clientY, pointerType }),
  );
}
describe("PracticeCompanion mounted motion lifecycle", () => {
  it("uses finite once motion without rendering a character pause control", async () => {
    const env = motionEnvironment();
    localStorage.setItem("ac-practice-companion-motion", "on");
    const { host } = await mountCompanion(
      <>
        <PracticeCompanionStage variant="echo" mood="ready" />
        <PracticeCompanionStage variant="page" mood="pause" />
      </>,
    );
    for (const observer of env.intersections)
      observer.callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    expect(host.querySelector("button")).toBeNull();
    for (const svg of host.querySelectorAll("svg[data-companion]")) {
      expect((svg as SVGSVGElement).dataset.motion).toBe("once");
    }
    expect(localStorage.getItem("ac-practice-companion-motion")).toBe("on");
  });
  it("honors saved and operating-system reduced motion without an override", async () => {
    const env = motionEnvironment();
    localStorage.setItem("ac-practice-companion-motion", "off");
    const { host, svg } = await mountCompanion(
      <PracticeCompanionStage variant="scout" mood="ready" />,
    );
    env.intersect(true);
    expect(svg.dataset.motion).toBe("off");
    expect(svg.dataset.play).toBe("paused");
    expect(host.querySelector("button")).toBeNull();
    env.reduced(true);
    env.intersect(true);
    expect(svg.dataset.motion).toBe("off");
    expect(svg.dataset.play).toBe("paused");
    env.reduced(false);
    expect(svg.dataset.play).toBe("paused");
  });
  it("waits for intersection and pauses whenever hidden or outside the viewport", async () => {
    const env = motionEnvironment();
    const { svg } = await mountCompanion(<PracticeCompanion motion="alive" />);
    expect(env.intersections[0].observe).toHaveBeenCalledWith(svg);
    expect(svg.dataset.play).toBe("paused");
    env.intersect(true);
    expect(svg.dataset.play).toBe("running");
    env.visibility("hidden");
    expect(svg.dataset.play).toBe("paused");
    env.visibility("visible");
    expect(svg.dataset.play).toBe("running");
    env.intersect(false);
    expect(svg.dataset.play).toBe("paused");
    env.visibility("visible");
    expect(svg.dataset.play).toBe("paused");
  });
  it("responds to OS reduced motion without allowing a visibility event to bypass it", async () => {
    const env = motionEnvironment();
    const { svg } = await mountCompanion(<PracticeCompanion motion="alive" />);
    env.intersect(true);
    env.reduced(true);
    expect(svg.dataset.play).toBe("paused");
    env.visibility("visible");
    expect(svg.dataset.play).toBe("paused");
    env.reduced(false);
    expect(svg.dataset.play).toBe("running");
  });
  it.each(["data-reduced-motion", "data-motion"])(
    "observes live %s preferences and restores only when eligible",
    async (attribute) => {
      const env = motionEnvironment();
      const { svg } = await mountCompanion(
        <PracticeCompanion motion="alive" />,
      );
      env.intersect(true);
      document.documentElement.setAttribute(
        attribute,
        attribute === "data-motion" ? "reduced" : "true",
      );
      await vi.waitFor(() => expect(svg.dataset.play).toBe("paused"));
      document.documentElement.removeAttribute(attribute);
      await vi.waitFor(() => expect(svg.dataset.play).toBe("running"));
      env.intersect(false);
      document.documentElement.setAttribute(
        attribute,
        attribute === "data-motion" ? "reduced" : "true",
      );
      document.documentElement.removeAttribute(attribute);
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(svg.dataset.play).toBe("paused");
    },
  );
  it("honors active=false and motion=off across prop changes without stale queued gaze", async () => {
    const env = motionEnvironment();
    const { svg, root } = await mountCompanion(
      <PracticeCompanion motion="alive" />,
    );
    env.intersect(true);
    pointer(800, 800);
    expect(env.frames.size).toBe(1);
    await act(() =>
      root.render(<PracticeCompanion motion="alive" active={false} />),
    );
    env.intersect(true);
    expect(svg.dataset.play).toBe("paused");
    expect(env.frames.size).toBe(0);
    pointer(800, 800);
    expect(env.frames.size).toBe(0);
    await act(() => root.render(<PracticeCompanion motion="off" />));
    env.intersect(true);
    expect(svg.dataset.play).toBe("paused");
    await act(() => root.render(<PracticeCompanion motion="alive" />));
    env.intersect(true);
    expect(svg.dataset.play).toBe("running");
  });
  it("coalesces pointer motion, clamps gaze, ignores touch, and resets on pointer leave", async () => {
    const env = motionEnvironment();
    const { svg } = await mountCompanion(<PracticeCompanion motion="alive" />);
    env.intersect(true);
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(
      new DOMRect(0, 0, 180, 160),
    );
    pointer(5000, 5000, "touch");
    expect(env.frames.size).toBe(0);
    pointer(5000, 5000);
    pointer(-5000, -5000);
    expect(env.requestFrame).toHaveBeenCalledOnce();
    env.flushFrames();
    expect(svg.style.getPropertyValue("--gaze-x")).toBe("-2.8px");
    expect(svg.style.getPropertyValue("--gaze-y")).toBe("-1.8px");
    expect(env.frames.size).toBe(0); // No self-scheduling per-frame animation loop.
    pointer(5000, 5000);
    document.dispatchEvent(new Event("pointerleave"));
    expect(env.frames.size).toBe(0);
    expect(svg.style.getPropertyValue("--gaze-x")).toBe("0px");
    expect(svg.style.getPropertyValue("--gaze-y")).toBe("0px");
  });
  it("does not schedule gaze for once motion or while paused", async () => {
    const env = motionEnvironment();
    const { root } = await mountCompanion(<PracticeCompanion />);
    env.intersect(true);
    pointer(500, 500);
    expect(env.requestFrame).not.toHaveBeenCalled();
    await act(() => root.render(<PracticeCompanion motion="alive" />));
    env.intersect(true);
    env.reduced(true);
    pointer(500, 500);
    expect(env.requestFrame).not.toHaveBeenCalled();
  });
  it("cancels pending frames and disconnects observers and event subscriptions on unmount", async () => {
    const env = motionEnvironment();
    const remove = vi.spyOn(document, "removeEventListener");
    const disconnect = vi.spyOn(MutationObserver.prototype, "disconnect");
    const { svg, root } = await mountCompanion(
      <PracticeCompanion motion="alive" />,
    );
    env.intersect(true);
    pointer(500, 500);
    expect(env.frames.size).toBe(1);
    await act(() => root.unmount());
    reactRoots.splice(reactRoots.indexOf(root), 1);
    expect(env.frames.size).toBe(0);
    expect(env.intersections[0].disconnect).toHaveBeenCalledOnce();
    expect(disconnect).toHaveBeenCalled();
    expect(env.mediaRemove).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
    for (const event of ["pointermove", "pointerleave", "visibilitychange"])
      expect(remove).toHaveBeenCalledWith(event, expect.any(Function));
    expect(svg.dataset.play).toBe("paused");
    pointer(500, 500);
    expect(env.frames.size).toBe(0);
  });
});

describe("RewardReveal presentation without reward authority", () => {
  it.each([true, false])(
    "earned=%s chooses the glyph but is static by default",
    (earned) => {
      stylesFor("reward-reveal.module.css", rewardStyles);
      const root = render(<RewardReveal earned={earned} />);
      const stage = root.firstElementChild!;
      expect(stage.getAttribute("aria-hidden")).toBe("true");
      expect(stage.hasAttribute("data-animate")).toBe(false);
      expect(
        root
          .querySelector("[data-learning-symbol]")
          ?.getAttribute("data-learning-symbol"),
      ).toBe(earned ? "credits" : "review");
      expect(root.querySelectorAll("i")).toHaveLength(0);
      expect(animations(root)).toHaveLength(0);
      expect(root.textContent).toBe("");
      expect(
        root.querySelectorAll('[role="status"],[aria-live],button,a'),
      ).toHaveLength(0);
    },
  );

  it("animates only when explicitly requested and leaves the amount to caller text", () => {
    stylesFor("reward-reveal.module.css", rewardStyles);
    const root = render(<RewardReveal earned animate />);
    expect(root.firstElementChild?.getAttribute("data-animate")).toBe("true");
    expect(root.querySelectorAll("i").length).toBeGreaterThan(0);
    const active = animations(root);
    expect(active.length).toBeGreaterThan(0);
    for (const value of active) expect(value).not.toContain("infinite");
    expect(root.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(root.textContent).toBe("");
  });
});

describe("reduced-motion cascade", () => {
  it("detects a less-specific late override rather than assuming last rule wins", () => {
    const style = document.createElement("style");
    style.textContent =
      ".cascade[data-animate] .moving{animation:hop 1s both}.cascade[data-animate] *{animation:none}";
    document.head.append(style);
    mounted.push(style);
    const root = render(
      <div className="cascade" data-animate>
        <span className="moving" />
      </div>,
    );
    expect(
      getComputedStyle(root.querySelector("span")!).getPropertyValue(
        "animation",
      ),
    ).toBe("hop 1s both");
  });

  it.each(["system", "saved-reduced-motion", "saved-motion"] as const)(
    "%s cancels every animated reward and companion layer",
    (preference) => {
      if (preference === "saved-reduced-motion")
        document.documentElement.setAttribute("data-reduced-motion", "true");
      if (preference === "saved-motion")
        document.documentElement.setAttribute("data-motion", "reduced");
      stylesFor(
        "practice-companion.module.css",
        companionStyles,
        preference === "system",
      );
      stylesFor(
        "reward-reveal.module.css",
        rewardStyles,
        preference === "system",
      );
      const reward = render(<RewardReveal earned animate />);
      expect(animations(reward)).toHaveLength(0);
      for (const mood of [
        "ready",
        "encourage",
        "celebrate",
        "pause",
      ] as const) {
        expect(
          animations(render(<PracticeCompanion mood={mood} motion="alive" />)),
        ).toHaveLength(0);
      }
      const coin = reward.querySelector(`.${rewardStyles.coin}`)!;
      expect(getComputedStyle(coin).transform).toBe("none");
      expect(
        reward.querySelector('[data-learning-symbol="credits"]'),
      ).not.toBeNull();
    },
  );
});
