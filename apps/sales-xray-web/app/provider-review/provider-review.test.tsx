import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  acquisition: vi.fn(),
  host: "salesxray-staging.authorityclosers.com",
}));

vi.mock("../acquisition-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../acquisition-client")>();
  return { ...actual, acquisition: mocks.acquisition };
});
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ host: mocks.host }),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

import Page from "./page";
import {
  BenchmarkQuoteError,
  parseBenchmarkQuote,
  parseSavedBenchmarkSource,
  ProviderReview,
} from "./provider-review";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const submissionId = "11111111-1111-4111-8111-111111111111";
const recordingId = "22222222-2222-4222-8222-222222222222";
const approvalId = "33333333-3333-4333-8333-333333333333";
const runId = "44444444-4444-4444-8444-444444444444";
const sha = "a".repeat(64);
const fingerprint = "b".repeat(64);

function savedCall(overrides: Record<string, unknown> = {}) {
  return {
    submission_id: submissionId,
    recording_id: recordingId,
    source_sha256: sha,
    state: "report_ready",
    local_state: "completed",
    failure_code: null,
    has_report: true,
    automatic_progression: true,
    stages: [
      { stage: "C2", state: "completed" },
      { stage: "C4", state: "completed" },
      { stage: "C5", state: "completed" },
    ],
    ...overrides,
  };
}

function quote(overrides: Record<string, unknown> = {}) {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    recording_id: recordingId,
    stage: "C5",
    provider: "openai",
    model: "gpt-6-luna",
    quote_fingerprint: fingerprint,
    privacy_revision: "privacy-owner-benchmark-v1",
    privacy_notice: "Synthetic test privacy notice.",
    cost_label: "up to ₹22.00 · approved project cap",
    max_cost_paise: 2_200,
    budget_cap_paise: 250_000,
    entitlement_seconds: 0,
    input_sha256: "c".repeat(64),
    expires_at_epoch: Math.floor(Date.now() / 1000) + 600,
    accepted: false,
    purpose: "acquisition_c5_benchmark",
    benchmark_approval_id: approvalId,
    ...overrides,
  };
}

let root: Root;
let container: HTMLDivElement;

async function flush() {
  await act(async () => {
    for (let index = 0; index < 15; index++) await Promise.resolve();
  });
}

async function mount(callId = submissionId) {
  await act(async () => root.render(<ProviderReview submissionId={callId} />));
  await flush();
}

function button(label: string) {
  const found = [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  );
  expect(found, label).toBeDefined();
  return found as HTMLButtonElement;
}

async function click(label: string) {
  await act(async () => button(label).click());
  await flush();
}

async function prepareSuccess() {
  mocks.acquisition.mockImplementation(async (path: string) => {
    if (path === `/submissions/${submissionId}`) return savedCall();
    if (path.endsWith("/c5-benchmark/quote")) return quote();
    throw new Error("unexpected_api_call");
  });
  await mount();
  await click("Prepare exact quote");
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  mocks.host = "salesxray-staging.authorityclosers.com";
  mocks.acquisition.mockReset();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("provider review staging owner action", () => {
  it("serves the route only on the exact staging host with one UUID call selector", async () => {
    const page = await Page({
      searchParams: Promise.resolve({ call: submissionId }),
    });
    await act(async () => root.render(page));
    expect(container.querySelector("h1")?.textContent).toBe(
      "OpenAI comparison",
    );

    mocks.host = "salesxray.authorityclosers.com";
    await expect(
      Page({ searchParams: Promise.resolve({ call: submissionId }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    mocks.host = "salesxray-staging.authorityclosers.com";
    await expect(
      Page({
        searchParams: Promise.resolve({ call: [submissionId, submissionId] }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("rejects malformed, mismatched-source, over-cap, expired and non-approved-model quotes", () => {
    expect(() => parseBenchmarkQuote({}, recordingId)).toThrow(
      BenchmarkQuoteError,
    );
    expect(() =>
      parseBenchmarkQuote(quote({ recording_id: approvalId }), recordingId),
    ).toThrow(expect.objectContaining({ code: "source_mismatch" }));
    expect(() =>
      parseBenchmarkQuote(quote({ max_cost_paise: 2_201 }), recordingId),
    ).toThrow(expect.objectContaining({ code: "scope" }));
    expect(() =>
      parseBenchmarkQuote(quote({ expires_at_epoch: 10 }), recordingId, 10),
    ).toThrow(expect.objectContaining({ code: "expired" }));
    expect(() =>
      parseBenchmarkQuote(quote({ model: "gpt-4o" }), recordingId),
    ).toThrow(BenchmarkQuoteError);
  });

  it("requires the same saved source with completed C2 and C4 before requesting a quote", () => {
    expect(
      parseSavedBenchmarkSource(savedCall(), submissionId).recordingId,
    ).toBe(recordingId);
    expect(() =>
      parseSavedBenchmarkSource(
        savedCall({ submission_id: approvalId }),
        submissionId,
      ),
    ).toThrow(expect.objectContaining({ code: "source_mismatch" }));
    expect(() =>
      parseSavedBenchmarkSource(
        savedCall({ stages: [{ stage: "C2", state: "completed" }] }),
        submissionId,
      ),
    ).toThrow(expect.objectContaining({ code: "source_mismatch" }));
  });

  it("requests one empty-body quote, then sends one explicit acceptance with a different key and stops on uncertainty", async () => {
    await prepareSuccess();
    const quoteCall = mocks.acquisition.mock.calls.find(([path]) =>
      String(path).endsWith("/c5-benchmark/quote"),
    )!;
    expect(quoteCall[1]).toMatchObject({
      method: "POST",
      headers: { "Idempotency-Key": expect.stringContaining(":quote:") },
    });
    expect(quoteCall[1]).not.toHaveProperty("body");
    expect(container.textContent).toContain("Provider input SHA-256");
    expect(container.textContent).toContain(
      "The quote response does not disclose a token count",
    );

    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await flush();
    mocks.acquisition.mockImplementation(async (path: string) => {
      if (path.endsWith("/c5-benchmark"))
        throw new Error("network_outcome_uncertain");
      throw new Error("unexpected_retry");
    });
    await act(async () => {
      button("Accept quote and queue one comparison").click();
      button("Accept quote and queue one comparison").click();
    });
    await flush();

    const acceptCalls = mocks.acquisition.mock.calls.filter(([path]) =>
      String(path).endsWith("/c5-benchmark"),
    );
    expect(acceptCalls).toHaveLength(1);
    const acceptCall = acceptCalls[0]!;
    const quoteKey = quoteCall[1]?.headers as Record<string, string>;
    const acceptKey = acceptCall[1]?.headers as Record<string, string>;
    expect(acceptKey["Idempotency-Key"]).toContain(":accept:");
    expect(acceptKey["Idempotency-Key"]).not.toBe(quoteKey["Idempotency-Key"]);
    expect(JSON.parse(String(acceptCall[1]?.body))).toEqual({
      quote_id: quote().id,
      quote_fingerprint: fingerprint,
      privacy_revision: "privacy-owner-benchmark-v1",
      accepted: true,
    });
    expect(container.textContent).toContain("Do not retry it");
    expect(container.textContent).toContain(quote().id);
    expect(container.querySelector("button")).toBeNull();
  });

  it("shows the verified queued run after a valid owner acceptance", async () => {
    await prepareSuccess();
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await flush();
    mocks.acquisition.mockResolvedValueOnce({
      id: runId,
      recording_id: recordingId,
      state: "queued",
      purpose: "acquisition_c5_benchmark",
      benchmark_approval_id: approvalId,
    });
    await click("Accept quote and queue one comparison");
    expect(container.textContent).toContain("One comparison was accepted");
    expect(container.textContent).toContain(runId);
  });

  it("stops before quote on a different owner-bound submission", async () => {
    mocks.acquisition.mockResolvedValueOnce(
      savedCall({ submission_id: approvalId }),
    );
    await mount();
    await click("Prepare exact quote");
    expect(mocks.acquisition).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("No benchmark quote was requested");
  });
});
