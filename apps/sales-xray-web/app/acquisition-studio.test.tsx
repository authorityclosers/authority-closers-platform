import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Page from "./page";
import { remainingAllowanceLabel } from "./acquisition-studio";
import {
  allowance,
  entry,
  envelope,
  plan,
  policy,
  progress,
  submissionId,
  recordingId,
  transcript,
} from "../tests/acquisition-fixture";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("./upload-check", () => ({
  UploadCheck: ({ onToken }: { onToken: (token: string) => void }) => (
    <button onClick={() => onToken("synthetic-one-use-challenge")}>
      Complete upload check
    </button>
  ),
}));
let root: Root, container: HTMLDivElement;
let calls: Array<{ path: string; init: RequestInit }>;
let existing: boolean,
  accepted: boolean,
  claimed: boolean,
  failedUpload: boolean,
  sessionUnauthorized: boolean,
  processingMode: "running" | "held" | null,
  lookupUnavailable: boolean,
  deletionDenied: boolean;
let reportBody: unknown;
let progressOverride: unknown;
let planFailure: { status: number; body: unknown } | null;
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
const flush = async () => {
  await act(async () => {
    for (let n = 0; n < 15; n++) await Promise.resolve();
  });
};
function button(text: string) {
  const found = [...container.querySelectorAll("button")].find((element) =>
    element.textContent?.includes(text),
  );
  expect(found, text).toBeDefined();
  return found!;
}
async function click(text: string) {
  await act(async () => button(text).click());
  await flush();
}
async function mount() {
  await act(async () => root.render(<Page />));
  await flush();
}
async function select() {
  const input =
    container.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["synthetic"], "Sales call.wav", { type: "audio/wav" });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new ArrayBuffer(10),
  });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  await flush();
}
async function consent() {
  await act(async () =>
    container
      .querySelector<HTMLInputElement>('input[type="checkbox"]')!
      .click(),
  );
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  existing = false;
  accepted = false;
  claimed = false;
  failedUpload = false;
  sessionUnauthorized = false;
  processingMode = null;
  lookupUnavailable = false;
  deletionDenied = false;
  reportBody = envelope;
  progressOverride = undefined;
  planFailure = null;
  localStorage.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-only");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.stubGlobal("crypto", {
    randomUUID: () => submissionId,
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path === "/v1/me/workspaces")
        return response({
          person_id: "person-1",
          session_id: "session-1",
          selected_tenant_id: "tenant-1",
          workspaces: [{ tenant_id: "tenant-1", name: "Synthetic Academy" }],
        });
      if (path.endsWith("/entry")) return response(entry);
      if (path.endsWith("/upload-policy")) return response(policy);
      if (path.endsWith("/session")) {
        if (init.method === "POST") {
          existing = true;
          return response({ state: "guest", allowance }, 201);
        }
        if (sessionUnauthorized) return response({}, 401);
        return existing
          ? response({
              state: claimed ? "claim_required" : "guest",
              allowance,
              claim_available: claimed,
            })
          : response({}, 401);
      }
      if (path.endsWith("/source") && init.method === "PUT")
        return failedUpload
          ? response({}, 503)
          : response(
              {
                ...progress,
                duration_ms: 5000,
                allowance: {
                  ...allowance,
                  committed_seconds: 5,
                  available_seconds: 5995,
                },
              },
              202,
            );
      if (path.endsWith("/plan/quote")) return response(plan, 201);
      if (path.endsWith("/plan")) {
        if (planFailure) return response(planFailure.body, planFailure.status);
        accepted = true;
        return response(
          { ...plan, accepted: true, state: "active", current_stage: "C2" },
          202,
        );
      }
      if (path.endsWith("/report")) return response(reportBody);
      if (path.endsWith("/transcript")) return response(transcript);
      if (path.endsWith("/claim")) {
        claimed = false;
        return response({ state: "claimed", allowance });
      }
      if (
        path.endsWith(`/submissions/${submissionId}`) &&
        init.method !== "DELETE" &&
        progressOverride
      )
        return response(progressOverride);
      if (path.endsWith(`/submissions/${submissionId}`))
        return init.method === "DELETE"
          ? deletionDenied
            ? response({}, 404)
            : response({ id: recordingId, state: "deleting" }, 202)
          : lookupUnavailable
            ? response({}, 404)
            : response(
                processingMode === "held"
                  ? {
                      ...progress,
                      state: "held",
                      local_state: "failed",
                      has_report: false,
                      current_stage: "C4",
                      failure_code: "stage_uncertain",
                      stages: [
                        { stage: "C2", state: "completed" },
                        { stage: "C4", state: "completed" },
                        { stage: "C4", state: "uncertain" },
                      ],
                    }
                  : processingMode === "running"
                    ? {
                        ...progress,
                        state: "active",
                        local_state: "completed",
                        automatic_progression: true,
                        has_report: false,
                        stages: [
                          { stage: "C2", state: "running" },
                          { stage: "C4", state: "queued" },
                        ],
                      }
                    : {
                        ...progress,
                        has_report: accepted,
                        state: accepted ? "report_ready" : "ready",
                      },
              );
      throw new Error("Unexpected test request");
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

it("the actual page requires both consents, then shows the fourteen-point report", async () => {
  await mount();
  expect(
    container.querySelector('[aria-label="Sales Xray navigation"]'),
  ).not.toBeNull();
  expect(container.querySelector('a[href="/calls"]')).not.toBeNull();
  expect(container.textContent).toContain("Account & saved calls");
  expect(container.querySelectorAll("main")).toHaveLength(1);
  await select();
  expect(button("Upload my call").disabled).toBe(true);
  await consent();
  expect(button("Upload my call").disabled).toBe(true);
  await click("Complete upload check");
  await click("Upload my call");
  expect(calls.filter((call) => call.init.method === "PUT")).toHaveLength(1);
  expect(button("Analyse my call").disabled).toBe(true);
  expect(calls.some((call) => call.path.endsWith("/plan"))).toBe(false);
  await consent();
  await click("Analyse my call");
  await flush();
  expect(
    container.querySelector('[aria-label="Sales call report"]'),
  ).not.toBeNull();
  expect(container.querySelectorAll("main")).toHaveLength(1);
  expect(container.querySelector(".studio-steps")?.textContent).toContain(
    "Report ready",
  );
  expect(
    container.querySelector('[aria-label="Current analysis step"] strong')
      ?.textContent,
  ).toBe("Report ready");
  expect(container.textContent).toContain(envelope.report.content.summary);
  expect(container.textContent).toContain("Remaining analysis time · 99m 55s");
  expect(container.textContent).not.toContain("free audio minutes");
  expect(container.textContent).not.toContain(
    "AI draft · not yet reviewed by Dipak",
  );
  expect(container.querySelectorAll(".studio-report-metric")).toHaveLength(0);
  expect(container.textContent).not.toContain("Call length");
  expect(container.textContent).toContain(
    "Review status: draft; Dipak has not adjudicated this report.",
  );
  expect(container.textContent).toContain(`Source: ${envelope.source_label}.`);
  const details = container.querySelector<HTMLDetailsElement>(
    ".studio-report-details",
  );
  expect(details).not.toBeNull();
  expect(details?.open).toBe(false);
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(3);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
  for (const call of calls) {
    expect(call.init.credentials).toBe("same-origin");
    expect(call.init.redirect).toBe("error");
  }
  await click("Transcript & moments");
  expect(container.textContent).toContain("कल timing discuss करूया.");
});

it.each([
  [
    403,
    { detail: "This recording's approved provider allowance is used." },
    "approved analysis allowance has been used",
  ],
  [
    403,
    { detail: "private-provider-context" },
    "Analysis approval is unavailable",
  ],
  [401, { detail: "private-provider-context" }, "Sign in again"],
])(
  "preserves the uploaded call after plan denial %s %# and offers the right recovery",
  async (status, body, expected) => {
    planFailure = { status, body };
    await mount();
    await select();
    await consent();
    await click("Complete upload check");
    await click("Upload my call");
    await consent();
    await click("Analyse my call");
    const alert = container.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain(expected);
    expect(alert.textContent).not.toContain("private-provider-context");
    expect(alert.querySelector('a[href="/login"]') !== null).toBe(
      status === 401,
    );
    if (status === 403) expect(alert.textContent).not.toContain("Sign in");
    expect(container.textContent).toContain(
      "Remaining analysis time · 99m 55s",
    );
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
    expect(container.querySelector("audio")?.getAttribute("src")).toContain(
      submissionId,
    );
    expect(
      container.querySelector('[aria-label="Sales call report"]'),
    ).toBeNull();
    const mutations = () =>
      calls.filter(({ init }) =>
        ["POST", "PUT", "DELETE"].includes(init.method ?? ""),
      );
    const before = mutations().length;
    await act(async () => vi.advanceTimersByTimeAsync(12000));
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      expected,
    );
    await click("Check again");
    expect(mutations()).toHaveLength(before);
    expect(calls.filter(({ path }) => path.endsWith("/plan"))).toHaveLength(1);
    expect(calls.filter(({ init }) => init.method === "PUT")).toHaveLength(1);
    expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
  },
);

it("shows the advertised trial allowance for a clean visitor", async () => {
  await mount();
  expect(container.textContent).toContain("Up to 100m trial allowance");
  expect(container.textContent).not.toContain("unavailable until your session");
});

it("rejects an audio file above the provider limit before creating a session", async () => {
  await mount();
  const input =
    container.querySelector<HTMLInputElement>('input[type="file"]')!;
  const oversized = new File(["synthetic"], "Oversized call.wav", {
    type: "audio/wav",
  });
  Object.defineProperty(oversized, "size", {
    configurable: true,
    value: 32 * 1024 ** 2 + 1,
  });
  Object.defineProperty(input, "files", {
    configurable: true,
    value: [oversized],
  });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  await flush();

  expect(container.textContent).toContain("within the displayed size limit");
  expect(
    calls.some(
      (call) => call.path.endsWith("/session") && call.init.method === "POST",
    ),
  ).toBe(false);
});

it("does not treat the advertised trial allowance as confirmed for a saved selector after 401", async () => {
  sessionUnauthorized = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(container.textContent).toContain(
    "Remaining analysis time · unavailable until your session is confirmed",
  );
  expect(container.textContent).not.toContain("Up to 100m trial allowance");
});

it.each([
  [0, "Remaining analysis time · 0m 00s · exhausted"],
  [45, "Remaining analysis time · 0m 45s"],
])("formats a confirmed %s-second allowance", (seconds, expected) => {
  const confirmed = {
    allowance_seconds: allowance.allowance_seconds,
    committed_seconds: allowance.allowance_seconds - seconds,
    available_seconds: seconds,
  };
  expect(
    remainingAllowanceLabel(confirmed, allowance.allowance_seconds, false),
  ).toBe(expected);
});

it("shows the live processing stages without inventing a percentage", async () => {
  existing = true;
  processingMode = "running";
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(container.querySelector('[role="status"] h3')?.textContent).toBe(
    "Transcribing your call",
  );
  expect(
    container.querySelector('[aria-label="Processing stages"]'),
  ).not.toBeNull();
  expect(container.querySelector('[data-stage="C2"] small')?.textContent).toBe(
    "In progress",
  );
  expect(container.querySelector('[data-stage="C4"] small')?.textContent).toBe(
    "Queued",
  );
  expect(container.querySelector('[data-stage="C5"] small')?.textContent).toBe(
    "Not started",
  );
  expect(container.textContent).not.toMatch(/\b\d+%\b/);
  expect(container.textContent).not.toMatch(/\b\d+\s*\/\s*\d+\b/);
});

it("shows saved completed work when an uncertain stage pauses processing", async () => {
  existing = true;
  processingMode = "held";
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(container.textContent).toContain(
    "We paused while checking the conversation",
  );
  expect(container.textContent).not.toContain("YOUR NEXT CALL CAN BE BETTER");
  expect(container.textContent).not.toContain("WHAT YOU’LL GET");
  expect(container.textContent).toContain(
    "This stage needs checking before analysis can continue",
  );
  expect(container.textContent).toContain(
    "Some conversation analysis is saved with this call",
  );
  expect(container.textContent).toContain(
    "The completed transcript stays attached",
  );
  expect(container.querySelector('[data-stage="C2"] small')?.textContent).toBe(
    "Complete",
  );
  expect(container.querySelector('[data-stage="C4"] small')?.textContent).toBe(
    "Paused · needs attention",
  );
  expect(container.querySelector('[data-stage="C5"] small')?.textContent).toBe(
    "Not started",
  );
  expect(container.textContent).not.toContain("fresh plan");
  expect(container.textContent).not.toContain("Upload the recording again");
  expect(container.querySelector('[data-paused="true"]')).not.toBeNull();
});

it.each(["failed", "cancelled"])(
  "keeps a %s source check static and never claims a transcript",
  async (state) => {
    existing = true;
    localStorage.setItem("ac.xray.submission.v1", submissionId);
    progressOverride = {
      ...progress,
      state,
      local_state: state,
      has_report: false,
      stages: [],
    };
    await mount();
    expect(container.querySelector('[role="status"] h3')?.textContent).toBe(
      "Your call needs attention",
    );
    expect(container.querySelector('svg[data-paused="true"]')).not.toBeNull();
    expect(container.textContent).toContain(
      "A completed transcript has not been confirmed yet",
    );
    expect(container.textContent).not.toContain(
      "The completed transcript stays attached",
    );
  },
);

it("keeps an uncertain transcription honest about missing completed work", async () => {
  existing = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  progressOverride = {
    ...progress,
    state: "held",
    local_state: "completed",
    has_report: false,
    stages: [{ stage: "C2", state: "uncertain" }],
  };
  await mount();
  expect(container.querySelector('[data-stage="C2"] small')?.textContent).toBe(
    "Paused · needs attention",
  );
  expect(container.textContent).toContain(
    "A completed transcript has not been confirmed yet",
  );
  expect(container.textContent).not.toContain(
    "The completed transcript stays attached",
  );
  expect(
    calls.some(
      (call) => call.path.endsWith("/plan") && call.init.method === "POST",
    ),
  ).toBe(false);
});

it("describes completed C4 chunks as saved work without claiming the entire stage is finished", async () => {
  existing = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  progressOverride = {
    ...progress,
    state: "active",
    local_state: "completed",
    has_report: false,
    automatic_progression: true,
    stages: [
      { stage: "C2", state: "completed" },
      { stage: "C4", state: "uncertain" },
      { stage: "C4", state: "completed" },
    ],
  };
  await mount();
  expect(container.querySelector('[data-stage="C4"] small')?.textContent).toBe(
    "Work saved",
  );
  expect(container.querySelector('svg[data-paused="true"]')).toBeNull();
  expect(container.textContent).toContain(
    "Some conversation analysis is saved with this call",
  );
});

it("retry keeps the same submission and source instead of a second charge", async () => {
  existing = true;
  failedUpload = true;
  await mount();
  await select();
  await consent();
  await click("Upload my call");
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  failedUpload = false;
  await click("Upload my call");
  const puts = calls.filter((call) => call.init.method === "PUT");
  expect(puts).toHaveLength(2);
  expect(puts[0].path).toBe(puts[1].path);
  expect(puts[0].init.headers).toEqual(puts[1].init.headers);
});

it("reload fetches the retained call and refuses a mismatched report", async () => {
  existing = true;
  accepted = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  reportBody = { ...envelope, recording_id: submissionId };
  await mount();
  expect(
    container.querySelector('[aria-label="Sales call report"]'),
  ).toBeNull();
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(calls.some((call) => call.init.method === "PUT")).toBe(false);
});

it("login return offers an explicit claim before reading the saved report", async () => {
  existing = true;
  claimed = true;
  accepted = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(container.textContent).toContain("Save to my account");
  expect(calls.some((call) => call.path.endsWith("/claim"))).toBe(false);
  expect(calls.some((call) => call.path.endsWith("/report"))).toBe(false);
  await click("Save to my account");
  expect(calls.filter((call) => call.path.endsWith("/claim"))).toHaveLength(1);
  expect(
    container.querySelector('[aria-label="Sales call report"]'),
  ).not.toBeNull();
});

it("requires explicit deletion and waits for server acceptance", async () => {
  existing = true;
  accepted = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  await click("Delete this call");
  expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);
  await click("Delete recording and report");
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
  expect(container.textContent).toContain("Deletion requested");
});

it("keeps an explicit deletion-only recovery when a saved call is unavailable", async () => {
  existing = true;
  lookupUnavailable = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(
    container.querySelector('[aria-label="Sales call report"]'),
  ).toBeNull();
  expect(container.textContent).toContain("Saved call unavailable");
  expect(container.textContent).not.toContain(envelope.report.content.summary);
  await click("Delete this call");
  expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);
  await click("Delete recording and report");
  expect(
    calls.some(
      (call) =>
        call.init.method === "DELETE" &&
        call.path.endsWith(`/submissions/${submissionId}`),
    ),
  ).toBe(true);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
  expect(container.textContent).toContain("Deletion requested");
});

it("can forget a saved selector when owner-authorized deletion is denied", async () => {
  existing = true;
  lookupUnavailable = true;
  deletionDenied = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  await click("Delete this call");
  await click("Delete recording and report");
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
  expect(button("Forget this saved call on this device")).toBeDefined();
  await click("Forget this saved call on this device");
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
  expect(container.textContent).toContain("Start with your sales call");
  expect(
    container.querySelector<HTMLInputElement>('input[type="file"]')?.disabled,
  ).toBe(false);
});
