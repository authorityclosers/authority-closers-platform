import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilmSurface } from "./film-surface";
import { QuoteChip } from "./quote-chip";
import {
  containsDevanagari,
  reportProseAttributes,
  sourceTextAttributes,
} from "./script";
import { StatusChip } from "./status-chip";
import { Stepper } from "./stepper";
import { formatClock, isUnderOneSecond } from "./time";
import { Toast } from "./toast";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const here = dirname(fileURLToPath(import.meta.url));
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function markup(node: React.ReactNode) {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(node);
  return container;
}

describe("time and script helpers", () => {
  it("formats readable clocks without milliseconds", () => {
    expect(formatClock(0)).toBe("00:00");
    expect(formatClock(198_999)).toBe("03:18");
    expect(formatClock(3_599_999)).toBe("59:59");
    expect(formatClock(3_600_000)).toBe("1:00:00");
    expect(formatClock(3_725_400)).toBe("1:02:05");
    expect(formatClock(Number.NaN)).toBe("00:00");
    expect(isUnderOneSecond(1_000, 1_900)).toBe(true);
    expect(isUnderOneSecond(1_000, 2_000)).toBe(false);
  });

  it("tags Devanagari source text by script, never by the requested report language", () => {
    expect(containsDevanagari("बजट थोड़ा ऊपर")).toBe(true);
    expect(sourceTextAttributes("कल timing discuss करूया.")).toEqual({
      lang: "und-Deva",
      "data-script": "deva",
    });
    expect(sourceTextAttributes("Theek hai, aap batana phir.")).toEqual({});
    expect(reportProseAttributes("अगली कॉल में पूछें", "hi-Deva+en")).toEqual({
      lang: "hi",
      "data-script": "deva",
    });
    expect(reportProseAttributes("Ask one question.", "en")).toEqual({
      lang: "en",
    });
    expect(reportProseAttributes("Ask one question.", null)).toEqual({});
  });
});

describe("QuoteChip", () => {
  const quote = "पज़ेशन कब तक मिलेगा actually? बच्चों का स्कूल June से है।";

  it("names the moment, keeps the full original quote and plays on click", async () => {
    const onPlay = vi.fn();
    await act(async () =>
      root.render(
        <QuoteChip
          startMs={587_000}
          quote={quote}
          kind="missed"
          onPlay={onPlay}
        />,
      ),
    );
    const button = host.querySelector("button")!;
    expect(button.getAttribute("aria-label")).toBe(
      `Play missed opening moment at 09:47: ${quote}`,
    );
    const text = host.querySelector("q")!;
    expect(text.textContent).toBe(quote);
    expect(text.getAttribute("lang")).toBe("und-Deva");
    expect(text.getAttribute("data-script")).toBe("deva");
    await act(async () => button.click());
    expect(onPlay).toHaveBeenCalledOnce();
  });

  it("shows playing and replay states without a numeric progress value", () => {
    const playing = markup(
      <QuoteChip
        startMs={0}
        quote="Sure."
        kind="strength"
        state="playing"
        onPlay={() => {}}
      />,
    );
    expect(playing.querySelector("[data-equaliser]")).not.toBeNull();
    const ended = markup(
      <QuoteChip
        startMs={0}
        quote="Sure."
        kind="strength"
        state="ended"
        onPlay={() => {}}
      />,
    );
    expect(ended.querySelector('[data-glyph="retry"]')).not.toBeNull();
    expect(ended.textContent).not.toMatch(/%/);
  });

  it("never clamps or ellipsises the quote", () => {
    const css = readFileSync(join(here, "quote-chip.module.css"), "utf8");
    expect(css).not.toMatch(/line-clamp|text-overflow:\s*ellipsis/);
  });
});

describe("status, steps and announcements", () => {
  it("labels status in words, with a decorative activity dot", () => {
    const chip = markup(
      <StatusChip tone="analysing" live>
        Analysing
      </StatusChip>,
    ).firstElementChild!;
    expect(chip.getAttribute("data-tone")).toBe("analysing");
    expect(chip.textContent).toBe("Analysing");
    expect(chip.querySelector("[data-live]")?.getAttribute("aria-hidden")).toBe(
      "true",
    );
  });

  it("marks the current step and names completed steps", () => {
    const steps = markup(
      <Stepper
        steps={["Choose call", "Confirm", "Analyse", "Report"]}
        current={1}
      />,
    );
    const items = [...steps.querySelectorAll("li")];
    expect(steps.querySelector("ol")?.getAttribute("aria-label")).toBe("Steps");
    expect(items[0].textContent).toBe("Completed: Choose call");
    expect(items[1].getAttribute("aria-current")).toBe("step");
    expect(
      items.filter((item) => item.hasAttribute("aria-current")),
    ).toHaveLength(1);
    expect(items[3].textContent).toBe("4Report");
  });

  it("keeps one polite live region mounted and fills it only when open", async () => {
    const onDismiss = vi.fn();
    await act(async () =>
      root.render(
        <Toast
          open={false}
          title="Your report is ready"
          onDismiss={onDismiss}
        />,
      ),
    );
    const region = host.querySelector('[role="status"]')!;
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.textContent).toBe("");
    await act(async () =>
      root.render(
        <Toast
          open
          title="Your report is ready"
          lens="done"
          onDismiss={onDismiss}
        />,
      ),
    );
    expect(host.querySelectorAll('[role="status"]')).toHaveLength(1);
    expect(region.textContent).toContain("Your report is ready");
    expect(region.querySelector('[data-lens-state="done"]')).not.toBeNull();
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Dismiss: Your report is ready"]',
        )!
        .click(),
    );
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});

describe("FilmSurface", () => {
  it("adds ambient scanline only to drop and panel surfaces", () => {
    const drop = markup(
      <FilmSurface as="label" htmlFor="call-file" variant="drop" scanline>
        Drop your call recording here
      </FilmSurface>,
    ).firstElementChild!;
    expect(drop.tagName.toLowerCase()).toBe("label");
    expect(drop.getAttribute("for")).toBe("call-file");
    expect(drop.getAttribute("data-film-variant")).toBe("drop");
    expect(
      drop.querySelector("[data-film-scanline]")?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(drop.querySelector("[data-film-corners]")).not.toBeNull();

    const player = markup(
      <FilmSurface
        as="section"
        variant="player"
        scanline
        aria-label="Call player"
      >
        Player
      </FilmSurface>,
    ).firstElementChild!;
    expect(player.getAttribute("aria-label")).toBe("Call player");
    expect(player.querySelector("[data-film-scanline]")).toBeNull();
    expect(player.querySelector("[data-film-corners]")).toBeNull();
  });
});
