// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AnalysisSettingsHistory } from "./analysis-settings-history";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const revision = (value: number) => ({
  revision: value,
  settings: {
    c4_max_requests: value,
    c4_max_completion_tokens: 1400,
    c5_max_completion_tokens: 3200,
    c5_output_profile: "detailed",
  },
  bounds: {
    c4_max_requests: { min: 1, max: 64 },
    c4_max_completion_tokens: { min: 256, max: 4000 },
    c5_max_completion_tokens: { min: 256, max: 8000 },
    c5_output_profile: { values: ["standard", "detailed"] },
  },
  created_at: "2026-09-23T00:00:00Z",
  message: "New plans only.",
});
const json = (value: unknown) => new Response(JSON.stringify(value));
let host: HTMLDivElement;
let root: Root;
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  )!;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("loads on demand and follows the immutable revision cursor without a mutation", async () => {
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    expect(init.method).toBeUndefined();
    return url.includes("before_revision=2")
      ? json({ items: [revision(1)], next_before_revision: null })
      : json({ items: [revision(3), revision(2)], next_before_revision: 2 });
  });
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(createElement(AnalysisSettingsHistory, { revision: 3 })),
  );
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => button("View revision").click());
  expect(host.textContent).toContain("Revision 3");
  await act(async () => button("Load older").click());
  expect(
    [...host.querySelectorAll("li strong")].map((item) => item.textContent),
  ).toEqual(["Revision 3", "Revision 2", "Revision 1"]);
  expect(button("Load older")).toBeUndefined();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("keeps v5 and older revisions readable in the same history", async () => {
  const latest = revision(5);
  const fetcher = vi.fn(async () =>
    json({
      items: [
        {
          ...latest,
          settings: {
            ...latest.settings,
            c5_coaching_prompt_revision: "coaching-v5",
            report_language_default: "mr-Deva+en",
          },
          bounds: {
            ...latest.bounds,
            c5_coaching_prompt_revision: {
              values: ["coaching-v3", "coaching-v4", "coaching-v5"],
            },
            report_language_default: {
              values: ["en", "hi-Deva+en", "mr-Deva+en"],
            },
          },
        },
        revision(4),
      ],
      next_before_revision: null,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(createElement(AnalysisSettingsHistory, { revision: 5 })),
  );
  await act(async () => button("View revision").click());
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelectorAll("li")).toHaveLength(2);
  expect(host.textContent).toContain("coaching-v5");
  expect(host.textContent).toContain("mr-Deva+en");
  expect(host.textContent).toContain("Revision 4");
});

it("rejects a repeated cursor page and retries without losing verified history", async () => {
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      calls += 1;
      return json(
        calls === 1
          ? { items: [revision(3)], next_before_revision: 3 }
          : calls === 2
            ? { items: [revision(3)], next_before_revision: 3 }
            : { items: [revision(2)], next_before_revision: null },
      );
    }),
  );
  await act(async () =>
    root.render(createElement(AnalysisSettingsHistory, { revision: 3 })),
  );
  await act(async () => button("View revision").click());
  await act(async () => button("Load older").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be verified",
  );
  expect(host.querySelectorAll("li")).toHaveLength(1);
  await act(async () => button("Retry loading").click());
  expect(host.querySelectorAll("li")).toHaveLength(2);
});

it("aborts an old request and clears its history after a newly saved revision", async () => {
  let signal: AbortSignal | undefined;
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal as AbortSignal;
      return new Promise<Response>((done) => {
        resolve = done;
      });
    }),
  );
  await act(async () =>
    root.render(createElement(AnalysisSettingsHistory, { revision: 3 })),
  );
  await act(async () => button("View revision").click());
  await act(async () =>
    root.render(createElement(AnalysisSettingsHistory, { revision: 4 })),
  );
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    resolve(json({ items: [revision(3)], next_before_revision: null })),
  );
  expect(host.textContent).not.toContain("Revision 3");
  expect(button("View revision").getAttribute("aria-expanded")).toBe("false");
});
