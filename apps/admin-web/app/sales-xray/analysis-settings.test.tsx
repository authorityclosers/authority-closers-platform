// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AnalysisSettingsPanel } from "./analysis-settings";
import { responseSchema, settingsSchema } from "./analysis-settings-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const state = {
  revision: 0,
  settings: {
    c4_max_requests: 64,
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
  created_at: null,
  message: "These limits apply to new plans.",
};

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

const current = {
  ...state,
  revision: 5,
  settings: {
    ...state.settings,
    c5_coaching_prompt_revision: "coaching-v5",
    report_language_default: "en",
  },
  bounds: {
    ...state.bounds,
    c5_coaching_prompt_revision: {
      values: ["coaching-v3", "coaching-v4", "coaching-v5"],
    },
    report_language_default: { values: ["en", "hi-Deva+en", "mr-Deva+en"] },
  },
};

let host: HTMLDivElement;
let root: Root;

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

it("loads the bounded controls and saves a real future-plan revision", async () => {
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") {
      return json({
        ...state,
        revision: 1,
        settings: JSON.parse(init.body as string).settings,
      });
    }
    return json(state);
  });
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(createElement(AnalysisSettingsPanel)));
  expect(host.textContent).toContain(
    "Until you save an Admin revision, new plans remain governed",
  );
  const profile = host.querySelector<HTMLSelectElement>(
    '[aria-label="C5 output profile"]',
  );
  expect(profile).toBeTruthy();
  // An older server does not advertise the new engine/language capability.
  expect(
    host.querySelectorAll('[aria-label="Report engine"] option'),
  ).toHaveLength(1);
  await act(async () => {
    profile!.value = "standard";
    profile!.dispatchEvent(new Event("change", { bubbles: true }));
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) =>
        button.textContent?.includes("Save future plan limits"),
      )!
      .click();
  });
  const post = fetcher.mock.calls.find(([, init]) => init.method === "POST");
  expect(post).toBeTruthy();
  expect(JSON.parse(post![1].body as string)).toMatchObject({
    expected_revision: 0,
    settings: { c5_output_profile: "standard" },
  });
  expect(new Headers(post![1].headers).get("Idempotency-Key")).toBeTruthy();
  expect(host.textContent).toContain("revision 1");
});

it("requires the versioned engine for Marathi and sends the exact selected settings", async () => {
  const available = {
    ...state,
    bounds: {
      ...state.bounds,
      c5_coaching_prompt_revision: { values: ["coaching-v3", "coaching-v4"] },
      report_language_default: { values: ["en", "hi-Deva+en", "mr-Deva+en"] },
    },
  };
  const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
    json(
      init.method === "POST"
        ? {
            ...available,
            revision: 1,
            settings: JSON.parse(init.body as string).settings,
          }
        : available,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(createElement(AnalysisSettingsPanel)));
  const change = async (label: string, value: string) =>
    act(async () => {
      const field = host.querySelector<HTMLSelectElement>(
        `[aria-label="${label}"]`,
      )!;
      field.value = value;
      field.dispatchEvent(new Event("change", { bubbles: true }));
    });
  const save = async () =>
    act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) =>
          button.textContent?.includes("Save future plan limits"),
        )!
        .click();
    });
  await change("Default report language", "mr-Deva+en");
  await save();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "require the qualitative v0.2 engine",
  );
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method === "POST"),
  ).toHaveLength(0);
  await change("Report engine", "coaching-v4");
  await save();
  const writes = fetcher.mock.calls.filter(
    ([, init]) => init.method === "POST",
  );
  expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0][1].body as string)).toMatchObject({
    expected_revision: 0,
    settings: {
      c5_coaching_prompt_revision: "coaching-v4",
      report_language_default: "mr-Deva+en",
    },
  });
  expect(host.textContent).toContain("revision 1");
});

it.each(["en", "hi-Deva+en", "mr-Deva+en"])(
  "loads and saves the server's v5 revision with %s without dropping its engine",
  async (language) => {
    const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
      json(
        init.method === "POST"
          ? {
              ...current,
              revision: 6,
              settings: JSON.parse(init.body as string).settings,
            }
          : current,
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    await act(async () => root.render(createElement(AnalysisSettingsPanel)));
    expect(host.textContent).not.toContain("could not be verified");
    const engine = host.querySelector<HTMLSelectElement>(
      '[aria-label="Report engine"]',
    )!;
    expect(engine.value).toBe("coaching-v5");
    expect(engine.selectedOptions[0].textContent).toBe(
      "Qualitative coaching · v5",
    );
    await act(async () => {
      const field = host.querySelector<HTMLSelectElement>(
        '[aria-label="Default report language"]',
      )!;
      field.value = language;
      field.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      [...host.querySelectorAll("button")]
        .find((button) =>
          button.textContent?.includes("Save future plan limits"),
        )!
        .click();
    });
    const writes = fetcher.mock.calls.filter(
      ([, init]) => init.method === "POST",
    );
    expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0][1].body as string)).toMatchObject({
      expected_revision: 5,
      settings: {
        c5_coaching_prompt_revision: "coaching-v5",
        report_language_default: language,
      },
    });
    expect(host.textContent).toContain("revision 6");
  },
);

it("still rejects unrecognized engines and out-of-bound settings", () => {
  expect(responseSchema.safeParse(current).success).toBe(true);
  expect(
    responseSchema.safeParse({
      ...current,
      settings: {
        ...current.settings,
        c5_coaching_prompt_revision: "coaching-v6",
      },
    }).success,
  ).toBe(false);
  expect(
    responseSchema.safeParse({
      ...current,
      bounds: {
        ...current.bounds,
        c5_coaching_prompt_revision: { values: ["coaching-v5", "coaching-v6"] },
      },
    }).success,
  ).toBe(false);
  expect(
    settingsSchema.safeParse({
      ...current.settings,
      c5_max_completion_tokens: 8001,
    }).success,
  ).toBe(false);
  expect(
    settingsSchema.safeParse({
      ...current.settings,
      c5_coaching_prompt_revision: "coaching-v3",
      report_language_default: "hi-Deva+en",
    }).success,
  ).toBe(false);
});
