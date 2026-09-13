import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CallStudio } from "./call-studio";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type RequestRecord = { url: string; init: RequestInit };
type JsonResponse = { ok: boolean; body: unknown; status?: number };

const quote = {
  id: "quote-1",
  recording_id: "recording-1",
  source_revision: "source-1",
  recipe_revision: "audioatlas-48000-v1",
  cost_label: "No charge in this test workspace",
  privacy_summary: "Synthetic review data stays within the approved workspace.",
  providers: ["synthetic-review"],
  expires_at: "2099-01-01T00:00:00Z",
  quote_fingerprint: "f".repeat(64),
  privacy_revision: "privacy-1",
  output_kind: "measurements",
};
const processingPlan = {
  id: "plan-1",
  recording_id: "recording-1",
  plan_fingerprint: "ab".repeat(32),
  privacy_revision: "sales-xray-processing-plan-v1",
  accepted: false,
  state: "quoted",
  cost_label: "₹0 · approved allowance",
  max_cost_paise: 0,
  max_entitlement_seconds: 0,
  expires_at_epoch: 4_102_444_800,
  stages: [
    {
      stage: "C2",
      provider: "synthetic-transcriber",
      model: "scribe-v2",
      max_requests: 1,
      privacy_revision: "sales-xray-processing-plan-v1",
      privacy_notice:
        "Synthetic transcript processing stays in the approved workspace.",
    },
    {
      stage: "C4",
      provider: "synthetic-facts",
      model: "facts-v1",
      max_requests: 1,
      privacy_revision: "sales-xray-processing-plan-v1",
      privacy_notice:
        "Synthetic fact extraction stays in the approved workspace.",
    },
    {
      stage: "C5",
      provider: "synthetic-coach",
      model: "coach-v1",
      max_requests: 1,
      privacy_revision: "sales-xray-processing-plan-v1",
      privacy_notice: "Synthetic coaching stays in the approved workspace.",
    },
  ],
  current_stage: null,
  report_ready: false,
  report_run_id: null,
  automatic_progression: true,
  failure_code: null,
};
const citation = { doc: "Doc-1", sections: ["source section"] };
const dimensions = Array.from({ length: 8 }, (_, index) => ({
  dimension_id: `dimension-${index + 1}`,
  label: `Dimension ${index + 1}`,
  status: "unknown",
  observation: "There is not enough evidence for a client-side conclusion.",
  citations: [citation],
}));
const reportSections = Array.from({ length: 9 }, (_, index) => ({
  number: index + 1,
  title: `Report section ${index + 1}`,
  required: "Keep this section grounded in the call.",
  citations: [citation],
}));
const report = {
  summary: "The prospect asked for a clear next step.",
  strengths: [
    {
      title: "You clarified the decision",
      explanation: "The call ended with a concrete next step.",
      evidence: [
        {
          segment_id: "s1",
          start_ms: 1500,
          end_ms: 2200,
          quote: "Let us agree on the next step.",
        },
      ],
    },
  ],
  missed_opportunities: [],
  improvements: [
    {
      title: "Name the objection earlier",
      explanation: "Surface the concern before presenting another feature.",
      evidence: [
        {
          segment_id: "s2",
          start_ms: 2500,
          end_ms: 3200,
          quote: "What would make this useful?",
        },
      ],
    },
  ],
  objection_analysis: [
    {
      title: "The concern was acknowledged",
      explanation: "The seller recognized the question before moving on.",
      evidence: [
        {
          segment_id: "s2",
          start_ms: 2500,
          end_ms: 3200,
          quote: "What would make this useful?",
        },
      ],
    },
  ],
  closing_analysis: [
    {
      title: "A next step was named",
      explanation: "The call ended with a clear follow-up action.",
      evidence: [
        {
          segment_id: "s1",
          start_ms: 1500,
          end_ms: 2200,
          quote: "Let us agree on the next step.",
        },
      ],
    },
  ],
  verdict: "Keep the direct close and ask one earlier diagnostic question.",
  review_status: "draft_not_dipak_adjudicated",
  source_label: "Server-derived source-bound draft",
  source_sha256: "00".repeat(32),
  transcript_revision: "scribe-test-r1",
  dimensions,
  report_sections: reportSections,
};
const transcript = {
  source_sha256: "00".repeat(32),
  revision: "scribe-test-r1",
  timebase_id: "1ms",
  duration_ms: 4000,
  segments: [
    {
      id: "s1",
      speaker_id: "speaker-1",
      start_ms: 1000,
      end_ms: 2200,
      text: "Let us agree on the next step.",
    },
    {
      id: "s2",
      speaker_id: "speaker-2",
      start_ms: 2500,
      end_ms: 3200,
      text: "What would make this useful?",
    },
  ],
};

let root: Root;
let container: HTMLDivElement;
let requests: RequestRecord[];
let handleApi: (
  path: string,
  init: RequestInit,
) => JsonResponse | Promise<JsonResponse>;
let fetchMock: ReturnType<typeof vi.fn>;

function response(body: unknown, ok = true, status?: number): JsonResponse {
  return { ok, body, status };
}

function getButton(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((node) =>
    node.textContent?.includes(label),
  );
  if (!(found instanceof HTMLButtonElement))
    throw new Error(`Missing button ${label}`);
  return found;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function render() {
  await act(async () => root.render(<CallStudio />));
  await flush();
}

async function selectAudio(name = "call.wav", bytes = "synthetic audio") {
  const file = new File([bytes], name, { type: "audio/wav" });
  const input = container.querySelector<HTMLInputElement>("#call-file");
  if (!input) throw new Error("Missing call file input");
  Object.defineProperty(input, "files", {
    configurable: true,
    value: [file],
  });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  const audio = container.querySelector<HTMLAudioElement>("audio");
  if (!audio) throw new Error("Missing local audio preview");
  Object.defineProperty(audio, "duration", {
    configurable: true,
    value: 4,
  });
  await act(async () => audio.dispatchEvent(new Event("loadedmetadata")));
  await flush();
  return file;
}

async function prepareAndAuthorize(file: File) {
  await act(async () => getButton("Continue to analysis").click());
  await flush();
  const checkbox = container.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  expect(checkbox).not.toBeNull();
  expect(getButton("Upload and measure privately").disabled).toBe(true);
  await act(async () => checkbox?.click());
  await flush();
  return file;
}

async function acceptProcessingPlan() {
  expect(container.textContent).toContain("Your approved report plan");
  const checkbox = container.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  expect(checkbox).not.toBeNull();
  expect(getButton("Start approved report").disabled).toBe(true);
  await act(async () => checkbox?.click());
  await flush();
  await act(async () => getButton("Start approved report").click());
  await flush();
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  requests = [];
  let planAccepted = false;
  let reportMode: "measurement" | "report" = "measurement";
  handleApi = (path, init) => {
    if (path.endsWith("/workspace"))
      return response({
        intake_enabled: true,
        authenticated: true,
        sign_in_url: null,
        message: "Ready for a synthetic call.",
      });
    if (path.endsWith("/recordings")) return response({ recordings: [] });
    if (
      path.endsWith("/recordings/recording-1/plan") &&
      init.method !== "POST"
    ) {
      if (!planAccepted)
        return response({ detail: "No processing plan." }, false, 404);
      reportMode = "report";
      return response({
        ...processingPlan,
        accepted: true,
        state: "completed",
        current_stage: "C6",
        report_ready: true,
        report_run_id: "run-1",
      });
    }
    if (/\/recordings\/[^/]+\/plan$/.test(path) && init.method !== "POST")
      return response({ detail: "No processing plan." }, false, 404);
    if (path.endsWith("/recordings/recording-1/plan/quote"))
      return response(processingPlan);
    if (path.endsWith("/recordings/recording-1/plan")) {
      planAccepted = true;
      return response({
        ...processingPlan,
        accepted: true,
        state: "active",
        current_stage: "C2",
        report_run_id: "run-1",
      });
    }
    if (path.endsWith("/recordings/recording-1/transcript"))
      return response(transcript);
    if (path.endsWith("/intake/quote")) return response(quote);
    if (path.endsWith("/quotes/quote-1/approve"))
      return response({ accepted: true });
    if (path.endsWith("/recordings/recording-1/source"))
      return response({ accepted: true });
    if (path.endsWith("/runs"))
      return response({
        id: "run-1",
        recording_id: "recording-1",
        state: "running",
        message: "Queued for analysis.",
      });
    if (path.endsWith("/runs/run-1/report"))
      return response({
        id: "run-1",
        recording_id: "recording-1",
        state: "completed",
        message:
          reportMode === "report"
            ? "Report ready."
            : "Local measurement complete.",
        report: reportMode === "report" ? report : null,
      });
    throw new Error(`Unexpected API path ${path}`);
  };
  fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    requests.push({ url, init });
    const result = await handleApi(
      new URL(url, "http://localhost").pathname,
      init,
    );
    return {
      ok: result.ok,
      status: result.status ?? (result.ok ? 200 : 400),
      json: async () => result.body,
    } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", {
    randomUUID: vi.fn(() => "request-key-1"),
    subtle: {
      digest: vi.fn(async () => new Uint8Array(32).buffer),
    },
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-call");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});

afterEach(async () => {
  vi.useRealTimers();
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("CallStudio", () => {
  it("keeps source selection local and clears a quote when the source changes", async () => {
    await render();
    const first = await selectAudio("first.wav", "first source");
    expect(first.name).toBe("first.wav");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain(
      "Selecting a file does not upload it.",
    );
    expect(getButton("Continue to analysis").disabled).toBe(false);

    await act(async () => getButton("Continue to analysis").click());
    await flush();
    expect(container.textContent).toContain("Ready to upload privately");
    expect(
      requests.filter((request) => request.init.method === "PUT"),
    ).toHaveLength(0);

    await selectAudio("replacement.wav", "replacement source");
    expect(container.textContent).toContain("replacement.wav");
    expect(container.textContent).not.toContain("Ready to upload privately");
    expect(
      requests.filter((request) => request.init.method === "POST"),
    ).toHaveLength(1);
  });

  it("requires the quote and permission before sending exact source bytes", async () => {
    await render();
    const file = await selectAudio();
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();

    const quoteRequest = requests.find((request) =>
      request.url.endsWith("/intake/quote"),
    );
    expect(quoteRequest?.init.method).toBe("POST");
    expect(quoteRequest?.init.headers).toEqual({
      "Content-Type": "application/json",
      "Idempotency-Key": "request-key-1",
    });
    expect(JSON.parse(String(quoteRequest?.init.body))).toEqual({
      source_sha256: "00".repeat(32),
      source_bytes: file.size,
      content_type: "audio/wav",
      duration_ms: 4000,
      purpose: "internal_analysis",
    });

    const uploadRequest = requests.find(
      (request) => request.init.method === "PUT",
    );
    const approvalRequest = requests.find((request) =>
      request.url.endsWith("/quotes/quote-1/approve"),
    );
    expect(approvalRequest?.init.method).toBe("POST");
    expect(approvalRequest?.init.headers).toMatchObject({
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(approvalRequest?.init.body))).toEqual({
      quote_fingerprint: "f".repeat(64),
      privacy_revision: "privacy-1",
      accepted: true,
    });
    expect(
      requests.findIndex((request) => request === approvalRequest),
    ).toBeLessThan(requests.findIndex((request) => request === uploadRequest));
    expect(uploadRequest?.url).toBe(
      "/v1/conversation/recordings/recording-1/source",
    );
    expect(uploadRequest?.init.headers).toEqual({
      "Content-Type": "application/octet-stream",
      "X-Analysis-Quote": "quote-1",
    });
    expect(uploadRequest?.init.body).toBe(file);
    expect(container.textContent).toContain("Your call is being processed");
  });

  it("polls for the report, renders evidence, and seeks the local audio", async () => {
    vi.useFakeTimers();
    await render();
    const file = await selectAudio("seekable.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    expect(
      requests.filter((request) => request.url.endsWith("/report")),
    ).toHaveLength(0);

    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(container.textContent).toContain("Your approved report plan");
    expect(
      requests.filter((request) =>
        request.url.endsWith("/recordings/recording-1/plan/quote"),
      ),
    ).toHaveLength(1);
    await acceptProcessingPlan();
    const planQuoteRequest = requests.find((request) =>
      request.url.endsWith("/recordings/recording-1/plan/quote"),
    );
    expect(planQuoteRequest?.init.method).toBe("POST");
    expect(planQuoteRequest?.init.headers).toEqual({
      "Idempotency-Key": "request-key-1:plan",
    });
    expect(planQuoteRequest?.init.body).toBeUndefined();
    const planAcceptRequest = requests.find(
      (request) =>
        request.url.endsWith("/recordings/recording-1/plan") &&
        request.init.method === "POST",
    );
    expect(planAcceptRequest?.init.headers).toEqual({
      "Content-Type": "application/json",
      "Idempotency-Key": "request-key-1:plan:accept",
    });
    expect(JSON.parse(String(planAcceptRequest?.init.body))).toEqual({
      plan_id: "plan-1",
      plan_fingerprint: "ab".repeat(32),
      privacy_revision: "sales-xray-processing-plan-v1",
      accepted: true,
    });
    expect(requests.some((request) => request.url.endsWith("/analysis"))).toBe(
      false,
    );
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(container.textContent).toContain(
      "The prospect asked for a clear next step.",
    );
    expect(container.textContent).toContain("Name the objection earlier");
    expect(container.textContent).toContain("Questions and concerns");
    expect(container.textContent).toContain(
      "AI draft · Dipak has not reviewed this",
    );
    expect(container.textContent).not.toContain("draft_not_dipak_adjudicated");
    expect(container.textContent).not.toContain("Practise:");
    const audio = container.querySelector<HTMLAudioElement>("audio");
    expect(audio).not.toBeNull();
    if (audio)
      Object.defineProperty(audio, "currentTime", {
        configurable: true,
        writable: true,
        value: 0,
      });
    await act(async () => getButton("00:01").click());
    expect(audio?.currentTime).toBe(1.5);
  });

  it("shows source-derived report measurements and keeps display language scoped to UI labels", async () => {
    vi.useFakeTimers();
    await render();
    const file = await selectAudio("language-mode.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();

    expect(container.textContent).toContain("Source moments");
    expect(container.textContent).toContain("Evidence-backed findings");
    expect(container.textContent).toContain("Held");
    expect(container.textContent).toContain("95 / 100 weights declared");
    expect(container.textContent).toContain("Moments from your call");
    expect(container.querySelectorAll(".studio-moment")).toHaveLength(2);

    const audio = container.querySelector<HTMLAudioElement>("audio");
    expect(audio).not.toBeNull();
    if (audio)
      Object.defineProperty(audio, "currentTime", {
        configurable: true,
        writable: true,
        value: 0,
      });
    const firstMoment = container.querySelector<HTMLButtonElement>(
      ".studio-moment",
    );
    expect(firstMoment?.getAttribute("aria-pressed")).toBe("false");
    await act(async () => firstMoment?.click());
    expect(audio?.currentTime).toBe(1.5);
    expect(firstMoment?.getAttribute("aria-pressed")).toBe("true");

    const language = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Display language"]',
    );
    expect(language).not.toBeNull();
    if (language) {
      expect([...language.options].map((option) => option.value)).toEqual([
        "en",
        "hi",
        "mr",
        "en-hi-mixed",
      ]);
      language.value = "hi";
      await act(async () =>
        language.dispatchEvent(new Event("change", { bubbles: true })),
      );
    }
    expect(container.textContent).toContain("आपकी कॉल के क्षण");
    expect(container.textContent).toContain(
      "रिपोर्ट का पाठ server-provided भाषा में ही रहता है",
    );
    expect(container.textContent).toContain("The prospect asked for a clear next step.");
  });

  it("polls report status before transcript and continues when the report arrives later", async () => {
    vi.useFakeTimers();
    let reportRequests = 0;
    let transcriptRequests = 0;
    const originalHandler = handleApi;
    let planReads = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/runs/run-1/report")) {
        reportRequests += 1;
        return reportRequests === 1
          ? response({
              id: "run-1",
              recording_id: "recording-1",
              state: "completed",
              message: "Local measurement complete.",
              report: null,
            })
          : response({
              id: "run-1",
              recording_id: "recording-1",
              state: "completed",
              message: "Report ready.",
              report,
            });
      }
      if (
        path.endsWith("/recordings/recording-1/plan") &&
        init.method !== "POST"
      ) {
        planReads += 1;
        if (planReads === 1)
          return response({
            ...processingPlan,
            accepted: true,
            state: "active",
            current_stage: "C2",
            report_run_id: "run-1",
          });
      }
      if (path.endsWith("/recordings/recording-1/transcript")) {
        transcriptRequests += 1;
        return response(transcript);
      }
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("delayed-report.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();

    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(reportRequests).toBe(1);
    expect(transcriptRequests).toBe(0);
    expect(container.textContent).not.toContain("Your sales call report");

    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(reportRequests).toBe(2);
    expect(transcriptRequests).toBe(1);
    expect(container.textContent).toContain("YOUR SALES CALL REPORT");
  });

  it("stops polling after a completed plan has no report", async () => {
    vi.useFakeTimers();
    let reportRequests = 0;
    const originalHandler = handleApi;
    handleApi = (path, init) => {
      if (path.endsWith("/runs/run-1/report")) {
        reportRequests += 1;
        return response({
          id: "run-1",
          recording_id: "recording-1",
          state: "completed",
          message: "Local measurement complete.",
          report: null,
        });
      }
      if (
        path.endsWith("/recordings/recording-1/plan") &&
        init.method !== "POST"
      )
        return response({
          ...processingPlan,
          accepted: true,
          state: "completed",
          current_stage: "C6",
          report_ready: false,
          report_run_id: null,
        });
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("completed-without-report.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();

    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(reportRequests).toBe(1);
    expect(container.textContent).toContain(
      "Analysis finished without a saved report",
    );

    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    await flush();
    expect(reportRequests).toBe(1);
  });

  it("rejects a report bound to a different source and keeps it hidden", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    let reportRequests = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/runs/run-1/report")) {
        reportRequests += 1;
        if (reportRequests === 1)
          return response({
            id: "run-1",
            recording_id: "recording-1",
            state: "completed",
            message: "Local measurement complete.",
            report: null,
          });
        return response({
          id: "run-1",
          recording_id: "recording-1",
          state: "completed",
          message: "Report ready.",
          report: { ...report, source_sha256: "11".repeat(32) },
        });
      }
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("mismatched.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(
      container.querySelector('[aria-label="Sales call report"]'),
    ).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "could not be verified",
    );
  });

  it("rejects a report status bound to a different run or recording", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    let reportRequests = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/runs/run-1/report")) {
        reportRequests += 1;
        if (reportRequests === 1)
          return response({
            id: "run-1",
            recording_id: "recording-1",
            state: "completed",
            message: "Local measurement complete.",
            report: null,
          });
        return response({
          id: "run-other",
          recording_id: "recording-other",
          state: "completed",
          message: "Report ready.",
          report,
        });
      }
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("mismatched-status.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(container.querySelector('[aria-label="Sales call report"]')).toBe(
      null,
    );
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "could not be verified",
    );
  });

  it("shows held plans honestly and requires a fresh quote to resume", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    let planReads = 0;
    handleApi = (path, init) => {
      if (
        path.endsWith("/recordings/recording-1/plan") &&
        init.method !== "POST"
      ) {
        planReads += 1;
        if (planReads >= 1)
          return response({
            ...processingPlan,
            accepted: true,
            state: "held",
            current_stage: "C4",
            failure_code: "provider_timeout",
          });
      }
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("held-plan.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();

    expect(container.textContent).toContain("report needs a fresh plan");
    expect(container.textContent).toContain("Processing is paused");
    expect(container.querySelector('[aria-label="Sales call report"]')).toBe(
      null,
    );
    await act(async () => getButton("Request a fresh plan").click());
    await flush();
    expect(
      requests.filter((request) =>
        request.url.endsWith("/recordings/recording-1/plan/quote"),
      ),
    ).toHaveLength(2);
    expect(container.textContent).toContain("Your approved report plan");
  });

  it("rejects a nonzero-cost plan response before showing a report", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    handleApi = (path, init) => {
      if (
        path.endsWith("/recordings/recording-1/plan") &&
        init.method !== "POST"
      )
        return response({
          ...processingPlan,
          accepted: true,
          state: "active",
          current_stage: "C2",
          report_run_id: "run-1",
          max_cost_paise: 1,
        });
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("malformed-plan.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(container.querySelector('[aria-label="Sales call report"]')).toBe(
      null,
    );
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "approved processing plan could not be verified",
    );
  });

  it("keeps a deferred report read alive while the plan view updates", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    let releaseReport: ((value: JsonResponse) => void) | undefined;
    let reportCalls = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/runs/run-1/report")) {
        reportCalls += 1;
        if (reportCalls === 1) return originalHandler(path, init);
        return new Promise<JsonResponse>((resolve) => {
          releaseReport = resolve;
        });
      }
      return originalHandler(path, init);
    };
    await render();
    const file = await selectAudio("deferred-report.wav");
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    await acceptProcessingPlan();
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(container.querySelector('[aria-label="Sales call report"]')).toBe(
      null,
    );
    expect(releaseReport).toBeDefined();
    releaseReport?.(
      response({
        id: "run-1",
        recording_id: "recording-1",
        state: "completed",
        message: "Report ready.",
        report,
      }),
    );
    await flush();
    expect(container.textContent).toContain(
      "The prospect asked for a clear next step.",
    );
  });

  it("restores an active plan for a saved call and polls its current stage", async () => {
    vi.useFakeTimers();
    const originalHandler = handleApi;
    const savedRecording = {
      id: "recording-1",
      state: "running",
      source_revision: "source-1",
      source_sha256: "00".repeat(32),
      source_bytes: 128,
      content_type: "audio/wav",
      created_at: "2026-09-13T00:00:00Z",
      latest_run: {
        id: "run-1",
        state: "running",
        recipe_revision: "audioatlas-48000-v1",
        provider_calls: 0,
        has_report: false,
      },
      has_report: false,
    };
    let planReads = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/recordings"))
        return response({ recordings: [savedRecording] });
      if (
        path.endsWith("/recordings/recording-1/plan") &&
        init.method !== "POST"
      ) {
        planReads += 1;
        return response({
          ...processingPlan,
          accepted: true,
          state: "active",
          current_stage: planReads === 1 ? "C2" : "C4",
          report_run_id: "run-1",
        });
      }
      return originalHandler(path, init);
    };
    await render();
    await act(async () => getButton("Sales call").click());
    await flush();
    expect(container.textContent).toContain("Transcribing the call");
    await act(async () => vi.advanceTimersByTimeAsync(2500));
    await flush();
    expect(planReads).toBe(2);
    expect(container.textContent).toContain("Extracting conversation facts");
    expect(container.querySelector('[aria-label="Sales call report"]')).toBe(
      null,
    );
  });

  it("prepares the report plan for a completed hosted 16 kHz measurement", async () => {
    const originalHandler = handleApi;
    const savedRecording = {
      id: "recording-1",
      state: "completed",
      source_revision: "source-1",
      source_sha256: "00".repeat(32),
      source_bytes: 128,
      content_type: "audio/wav",
      created_at: "2026-09-13T00:00:00Z",
      latest_run: {
        id: "run-1",
        state: "completed",
        recipe_revision: "audioatlas-16000-v1",
        provider_calls: 0,
        has_report: false,
      },
      has_report: false,
    };
    let planQuoteRequests = 0;
    handleApi = (path, init) => {
      if (path.endsWith("/recordings"))
        return response({ recordings: [savedRecording] });
      if (path.endsWith("/recordings/recording-1/plan/quote")) {
        planQuoteRequests += 1;
        return response(processingPlan);
      }
      return originalHandler(path, init);
    };

    await render();
    await act(async () => getButton("Sales call").click());
    await flush();

    expect(planQuoteRequests).toBe(1);
    expect(
      requests.some(
        (request) =>
          request.url.endsWith("/recordings/recording-1/plan/quote") &&
          request.init.method === "POST",
      ),
    ).toBe(true);
    expect(container.textContent).toContain("Your approved report plan");
    expect(container.textContent).not.toContain("Your sales call report");
  });

  it("shows upload failures, allows retry, and never invents a report", async () => {
    let uploadAttempts = 0;
    handleApi = (path) => {
      if (path.endsWith("/recordings/recording-1/source")) {
        uploadAttempts += 1;
        return uploadAttempts === 1
          ? response({ detail: "Synthetic upload failed." }, false)
          : response({ accepted: true });
      }
      if (path.endsWith("/recordings")) return response({ recordings: [] });
      if (path.endsWith("/recordings/recording-1/transcript"))
        return response(transcript);
      if (path.endsWith("/runs"))
        return response({
          id: "run-1",
          state: "running",
          message: "Queued for analysis.",
        });
      if (path.endsWith("/quotes/quote-1/approve"))
        return response({ accepted: true });
      return response(
        path.endsWith("/workspace")
          ? {
              intake_enabled: true,
              authenticated: true,
              sign_in_url: null,
              message: "Ready for a synthetic call.",
            }
          : quote,
      );
    };
    await render();
    const file = await selectAudio();
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Synthetic upload failed.",
    );
    expect(container.textContent).not.toContain("Your sales call report");
    expect(getButton("Upload and measure privately").disabled).toBe(false);

    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    expect(uploadAttempts).toBe(2);
    expect(container.textContent).toContain("Your call is being processed");
  });

  it("does not send source bytes when the server rejects quote approval", async () => {
    handleApi = (path) => {
      if (path.endsWith("/quotes/quote-1/approve"))
        return response({ detail: "Quote approval expired." }, false);
      if (path.endsWith("/recordings")) return response({ recordings: [] });
      if (path.endsWith("/recordings/recording-1/transcript"))
        return response(transcript);
      return path.endsWith("/workspace")
        ? response({
            intake_enabled: true,
            authenticated: true,
            sign_in_url: null,
            message: "Ready for a synthetic call.",
          })
        : response(quote);
    };
    await render();
    const file = await selectAudio();
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Quote approval expired.",
    );
    expect(requests.some((request) => request.init.method === "PUT")).toBe(
      false,
    );
    expect(container.textContent).not.toContain("Your call is being processed");
  });

  it.each(["audioatlas-48000-v1", "audioatlas-16000-v1"] as const)(
    "opens a saved %s recording, binds its report, and returns to the saved draft",
    async (recipeRevision) => {
      const originalHandler = handleApi;
      const savedRecording = {
        id: "recording-1",
        state: "completed",
        source_revision: "source-1",
        source_sha256: "00".repeat(32),
        source_bytes: 128,
        content_type: "audio/wav",
        created_at: "2026-09-13T00:00:00Z",
        latest_run: {
          id: "run-1",
          state: "completed",
          recipe_revision: recipeRevision,
          provider_calls: 0,
          has_report: true,
        },
        has_report: true,
      };
      handleApi = (path, init) => {
        if (path.endsWith("/recordings"))
          return response({ recordings: [savedRecording] });
        if (path.endsWith("/recordings/recording-1/transcript"))
          return response(transcript);
        if (path.endsWith("/runs/run-1/report"))
          return response({
            id: "run-1",
            recording_id: "recording-1",
            state: "completed",
            message: "Saved report ready.",
            report,
          });
        return originalHandler(path, init);
      };
      await render();
      expect(container.textContent).toContain("Saved calls");
      expect(container.textContent).toContain("Open report");
      await act(async () => getButton("Sales call").click());
      await flush();

      expect(container.textContent).toContain("Sales call");
      expect(container.textContent).toContain(
        "The prospect asked for a clear next step.",
      );
      expect(container.textContent).toContain(
        "Speaker labels remain unverified.",
      );
      expect(container.querySelector("audio")?.getAttribute("src")).toBe(
        "/v1/conversation/recordings/recording-1/source",
      );
      const transcriptIndex = requests.findIndex((request) =>
        request.url.endsWith("/recordings/recording-1/transcript"),
      );
      const reportIndex = requests.findIndex((request) =>
        request.url.endsWith("/runs/run-1/report"),
      );
      expect(transcriptIndex).toBeGreaterThanOrEqual(0);
      expect(reportIndex).toBeGreaterThanOrEqual(0);
      expect(reportIndex).toBeLessThan(transcriptIndex);
      expect(
        requests.filter(
          (request) =>
            request.url.endsWith("/recordings/recording-1/plan/quote") &&
            request.init.method === "POST",
        ),
      ).toHaveLength(0);
    },
  );

  it("plays a pending saved call without requiring a transcript", async () => {
    const originalHandler = handleApi;
    const savedRecording = {
      id: "recording-1",
      state: "running",
      source_revision: "source-1",
      source_sha256: "00".repeat(32),
      source_bytes: 128,
      content_type: "audio/wav",
      created_at: "2026-09-13T00:00:00Z",
      latest_run: {
        id: "run-1",
        state: "running",
        recipe_revision: "dipak-report-v1",
        provider_calls: 0,
        has_report: false,
      },
      has_report: false,
    };
    const transcriptRequests: string[] = [];
    handleApi = (path, init) => {
      if (path.endsWith("/recordings"))
        return response({ recordings: [savedRecording] });
      if (path.endsWith("/recordings/recording-1/transcript")) {
        transcriptRequests.push(path);
        return response({ detail: "Transcript is not ready." }, false);
      }
      return originalHandler(path, init);
    };
    await render();
    await act(async () => getButton("Sales call").click());
    await flush();

    expect(container.textContent).toContain("Analysis pending");
    expect(container.querySelector("audio")?.getAttribute("src")).toBe(
      "/v1/conversation/recordings/recording-1/source",
    );
    expect(transcriptRequests).toHaveLength(0);
  });

  it("clears old playback before a saved-call selection that fails", async () => {
    const originalHandler = handleApi;
    const firstRecording = {
      id: "recording-1",
      state: "completed",
      source_revision: "source-1",
      source_sha256: "00".repeat(32),
      source_bytes: 128,
      content_type: "audio/wav",
      created_at: "2026-09-13T00:00:00Z",
      latest_run: null,
      has_report: false,
    };
    const secondRecording = {
      id: "recording-2",
      state: "completed",
      source_revision: "source-2",
      source_sha256: "00".repeat(32),
      source_bytes: 128,
      content_type: "audio/wav",
      created_at: "2026-09-12T00:00:00Z",
      latest_run: {
        id: "run-2",
        state: "completed",
        recipe_revision: "dipak-report-v1",
        provider_calls: 0,
        has_report: true,
      },
      has_report: true,
    };
    handleApi = (path, init) => {
      if (path.endsWith("/recordings"))
        return response({ recordings: [firstRecording, secondRecording] });
      if (path.endsWith("/runs/run-2/report"))
        return response({
          id: "run-2",
          recording_id: "recording-2",
          state: "completed",
          message: "Report ready.",
          report,
        });
      if (path.endsWith("/recordings/recording-2/transcript"))
        return response({ detail: "Transcript is not ready." }, false);
      return originalHandler(path, init);
    };
    const pause = vi
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    await render();
    const historyButtons = () => [
      ...container.querySelectorAll<HTMLButtonElement>(
        ".recording-history-item",
      ),
    ];
    await act(async () => historyButtons()[0]?.click());
    await flush();
    expect(container.querySelector("audio")?.getAttribute("src")).toBe(
      "/v1/conversation/recordings/recording-1/source",
    );

    await act(async () => historyButtons()[1]?.click());
    await flush();
    expect(pause).toHaveBeenCalled();
    expect(container.querySelector("audio")?.getAttribute("src")).toBe(
      "/v1/conversation/recordings/recording-2/source",
    );
    expect(container.querySelector("audio")?.getAttribute("src")).not.toBe(
      "/v1/conversation/recordings/recording-1/source",
    );
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Transcript is not ready.",
    );
  });

  it("never persists selected source data in browser storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await render();
    const file = await selectAudio();
    await prepareAndAuthorize(file);
    await act(async () => getButton("Upload and measure privately").click());
    await flush();
    expect(setItem).not.toHaveBeenCalled();
    expect(Object.keys(localStorage)).toHaveLength(0);
  });
});
