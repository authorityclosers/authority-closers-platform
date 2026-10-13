import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  plan,
  progress,
  recordingId,
  submissionId,
} from "../tests/acquisition-fixture";
import {
  advanceImport,
  confirmImport,
  readImportBatch,
  refreshImport,
  retryImportItem,
  type ImportBatch,
} from "./bulk-import-runner";
import type { ImportSelection } from "./bulk-import-files";
import { MAX_ACQUISITION_FILE_BYTES } from "./acquisition-client";

const id = "11111111-1111-4111-8111-111111111111";
const person = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const digest = progress.source_sha256 as string;
const file = new File(["fixture"], "one.wav");
const selection: ImportSelection = {
  manifest: {
    files: [
      {
        relative_path: "Rep/one.wav",
        source_sha256: digest,
        source_bytes: file.size,
      },
    ],
  },
  files: new Map([["Rep/one.wav", file]]),
  skipped: 0,
};
const raw = () => ({
  batch_id: id,
  tenant_id: tenant,
  manifest_sha256: "b".repeat(64),
  policy_sha256: "c".repeat(64),
  total_files: 1,
  total_bytes: file.size,
  expires_at: "2030-01-01T00:00:00Z",
  terminal_state: null,
  files: [
    {
      item_index: 0,
      source_sha256: digest,
      source_bytes: file.size,
      person_id: person,
      upload_submission_id: submissionId,
      submission_id: null,
      state: "awaiting_upload",
      current_stage: null,
      minute_state: null,
      retry_available: false,
    },
  ],
});
const batch = (): ImportBatch => readImportBatch(raw())!;
const signal = () => new AbortController().signal;
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const fixturePlan = {
  ...plan,
  report_language: "en",
  coaching_prompt_revision: "coaching-v5",
  expires_at_epoch: 2_000_000_000,
};
let calls: { path: string; init: RequestInit }[];
beforeEach(() => {
  calls = [];
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function fetchWith(
  action: (path: string, init: RequestInit) => Response | Promise<Response>,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      return action(path, init);
    }),
  );
}

describe("batch intake commands", () => {
  it.each([32 * 1024 ** 2 + 1, MAX_ACQUISITION_FILE_BYTES])(
    "keeps a confirmed %i-byte recording readable within the current upload limit",
    (size) => {
      const response = raw();
      response.files[0]!.source_bytes = size;
      response.total_bytes = size;
      expect(readImportBatch(response)?.items[0]?.bytes).toBe(size);
    },
  );
  it("refuses a file above the current upload limit", () => {
    const response = raw();
    response.files[0]!.source_bytes = MAX_ACQUISITION_FILE_BYTES + 1;
    response.total_bytes = MAX_ACQUISITION_FILE_BYTES + 1;
    expect(readImportBatch(response)).toBeNull();
  });
  it("returns unavailable for sparse, invented or mismatched progress", () => {
    expect(readImportBatch({})).toBeNull();
    const invalid = raw();
    invalid.files[0]!.state = "magically_complete";
    expect(readImportBatch(invalid)).toBeNull();
    const wrong = raw();
    wrong.total_bytes++;
    expect(readImportBatch(wrong)).toBeNull();
    const reordered = raw();
    reordered.files[0]!.item_index = 1;
    expect(readImportBatch(reordered)).toBeNull();
  });
  it("binds confirmation to the current tenant, manifest, members and policy", async () => {
    fetchWith(() => response(raw(), 201));
    const preview = {
      tenantId: tenant,
      manifestSha: "b".repeat(64),
      folders: [
        {
          folder: "Rep",
          proposedPersonId: person,
          count: 1,
          bytes: file.size,
          state: "suggested" as const,
        },
      ],
      members: [{ personId: person, name: "Rep" }],
    };
    const request = {
      selection,
      preview,
      folders: { Rep: person },
      policySha: "c".repeat(64),
      key: "same-key",
      signal: signal(),
    };
    expect((await confirmImport(request)).error).toBeNull();
    const body = JSON.parse(calls[0]!.init.body as string);
    expect(body.rights_confirmed).toBe(true);
    expect(body.folders).toEqual([{ folder: "Rep", person_id: person }]);
    expect(calls[0]!.init.credentials).toBe("same-origin");
    expect(calls[0]!.init.redirect).toBe("error");
    const bad = await confirmImport({ ...request, folders: { Rep: id } });
    expect(bad.error).toBeTruthy();
    expect(calls).toHaveLength(1);
  });
  it("refuses a different tenant response instead of updating progress", async () => {
    fetchWith(() => response({ ...raw(), tenant_id: id }));
    expect((await refreshImport(batch(), signal())).error).toBeTruthy();
  });
  it("sends one source with the exact import grant and normal intake headers", async () => {
    fetchWith(() =>
      response({ submission_id: submissionId, source_sha256: digest }, 202),
    );
    expect(
      (await advanceImport(batch(), selection, signal())).error,
    ).toBeNull();
    expect(calls).toHaveLength(1);
    expect(calls[0]!.init.body).toBe(file);
    expect(calls[0]!.init.headers).toMatchObject({
      "X-Recording-Import": id,
      "X-Recording-Import-Item": "0",
      "X-Upload-Policy": "c".repeat(64),
      "X-Upload-Consent": "accepted",
    });
  });
  it("does not send a changed or missing local file", async () => {
    fetchWith(() => response({}));
    const changed = {
      ...selection,
      files: new Map([["Rep/one.wav", new File(["changed-size"], "one.wav")]]),
    };
    expect(
      (await advanceImport(batch(), changed, signal())).error,
    ).toBeTruthy();
    expect(calls).toHaveLength(0);
  });
  it("does not automatically retry a failed recording or upload an unassigned one", async () => {
    fetchWith(() => response({}));
    for (const state of [
      "failed",
      "needs_member",
      "expired",
      "already_imported",
    ]) {
      const current = batch();
      current.items[0]!.state = state;
      expect(
        (await advanceImport(current, selection, signal())).error,
      ).toBeNull();
    }
    expect(calls).toHaveLength(0);
  });
  it("waits for normal local checks before preparing or accepting a plan", async () => {
    const current = batch();
    current.items[0]!.state = "queued";
    current.items[0]!.submissionId = submissionId;
    fetchWith(() => response({ ...progress, local_state: "queued" }));
    expect(
      (await advanceImport(current, selection, signal())).error,
    ).toBeNull();
    expect(calls).toHaveLength(1);
  });
  it("uses normal quote and exact plan acceptance after canonical local completion", async () => {
    const current = batch();
    current.items[0]!.state = "working";
    current.items[0]!.submissionId = submissionId;
    fetchWith((path, init) => {
      if (path.endsWith("/plan/quote")) return response(fixturePlan, 201);
      if (path.endsWith("/plan"))
        return init.method === "POST"
          ? response({ ...fixturePlan, accepted: true, state: "active" }, 202)
          : response({}, 404);
      return response({
        ...progress,
        source_sha256: digest,
        recording_id: recordingId,
        local_state: "completed",
        automatic_progression: false,
        has_report: false,
        run_state: "working",
      });
    });
    expect(
      (await advanceImport(current, selection, signal())).error,
    ).toBeNull();
    const accepted = calls.find(
      (call) => call.path.endsWith("/plan") && call.init.method === "POST",
    )!;
    expect(JSON.parse(accepted.init.body as string)).toMatchObject({
      plan_id: fixturePlan.id,
      plan_fingerprint: fixturePlan.plan_fingerprint,
      privacy_revision: fixturePlan.privacy_revision,
      accepted: true,
    });
    expect(
      calls.every(
        (call) =>
          (call.init.headers as Record<string, string>)[
            "X-Recording-Import"
          ] === id,
      ),
    ).toBe(true);
  });
  it("never accepts a malformed or expired plan", async () => {
    const current = batch();
    current.items[0]!.state = "working";
    current.items[0]!.submissionId = submissionId;
    fetchWith((path) =>
      path.endsWith("/plan")
        ? response({ ...fixturePlan, expires_at_epoch: 1 })
        : response({
            ...progress,
            local_state: "completed",
            automatic_progression: false,
            has_report: false,
          }),
    );
    expect(
      (await advanceImport(current, selection, signal())).error,
    ).toBeTruthy();
    expect(calls.some((call) => call.init.method === "POST")).toBe(false);
  });
  it("bounds stalled reads and returns a resumable error", async () => {
    vi.useFakeTimers();
    fetchWith(
      (_path, init) =>
        new Promise((_resolve, reject) => {
          init.signal!.addEventListener("abort", () =>
            reject(new Error("aborted")),
          );
        }),
    );
    const running = refreshImport(batch(), signal());
    await vi.advanceTimersByTimeAsync(15_001);
    expect((await running).error).toContain("resume");
  });
  it("requires an explicit failed-call retry grant and keeps its request key", async () => {
    const current = batch();
    const item = current.items[0]!;
    fetchWith(() =>
      response(
        { retry_kind: "local", recording_id: recordingId, run_id: id },
        201,
      ),
    );
    expect(
      (await retryImportItem(current, item, "retry-key", signal())).error,
    ).toBeTruthy();
    expect(calls).toHaveLength(0);
    item.state = "failed";
    item.retryAvailable = true;
    item.submissionId = submissionId;
    expect(
      (await retryImportItem(current, item, "retry-key", signal())).error,
    ).toBeNull();
    expect(calls[0]!.init.headers).toMatchObject({
      "Idempotency-Key": "retry-key",
    });
  });
});
