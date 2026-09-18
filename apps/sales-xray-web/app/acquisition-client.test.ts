import { afterEach, describe, expect, it, vi } from "vitest";
import { parseAcquisitionReport, parseTranscript } from "./report-contract";
import {
  acquisition,
  clearRequestedSubmission,
  AcquisitionError,
  parseAllowance,
  parseEntry,
  parsePolicy,
  parseProgress,
  parseSubmission,
  rememberSubmission,
  requestedSubmissionId,
  savedSubmissionId,
} from "./acquisition-client";
import {
  allowance,
  entry,
  envelope,
  policy,
  progress,
  submissionId,
  recordingId,
  transcript,
} from "../tests/acquisition-fixture";

afterEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});
describe("acquisition permission recovery", () => {
  const path = `/submissions/${submissionId}/plan`;
  const allowanceDetail =
    "This recording's approved provider allowance is used.";

  it("keeps sign-in recovery specific to 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );
    await expect(acquisition(path)).rejects.toMatchObject({
      status: 401,
      message: expect.stringContaining("guest session is no longer active"),
    });
  });

  it.each(["", "/quote"])(
    "translates the exact plan%s allowance denial",
    async (suffix) => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: allowanceDetail }), {
          status: 403,
        }),
      );
      vi.stubGlobal("fetch", fetch);
      await expect(
        acquisition(path + suffix, { method: "POST" }),
      ).rejects.toMatchObject({
        status: 403,
        message: expect.stringContaining(
          "approved analysis allowance has been used",
        ),
      });
      expect(fetch).toHaveBeenCalledOnce();
      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          method: "POST",
        }),
      );
    },
  );

  it.each([
    JSON.stringify({ detail: "private-provider-context" }),
    JSON.stringify({ detail: `${allowanceDetail} private-provider-context` }),
    JSON.stringify([{ detail: allowanceDetail }]),
    "<html>private-provider-context</html>",
    "null",
  ])(
    "uses controlled plan copy for an unknown or malformed denial %#",
    async (body) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(body, { status: 403 })),
      );
      await expect(acquisition(path)).rejects.toMatchObject({
        status: 403,
        message: new AcquisitionError(403, "plan_permission").message,
      });
    },
  );

  it("does not infer an allowance denial outside the plan endpoints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: allowanceDetail }), {
          status: 403,
        }),
      ),
    );
    await expect(
      acquisition(`/submissions/${submissionId}`),
    ).rejects.toMatchObject({
      status: 403,
      message: new AcquisitionError(403).message,
    });
  });

  it.each([
    [
      "The provider budget cannot cover this complete plan.",
      "provider_budget_insufficient",
      "shared analysis budget",
    ],
    [
      "Finish local audio inspection before transcription.",
      "source_checking_not_ready",
      "still being checked privately",
    ],
    [
      "This call already has an active processing plan.",
      "active_plan",
      "already has an active analysis plan",
    ],
    [
      "Provider analysis is not enabled for this upload yet.",
      "analysis_unavailable",
      "not enabled for this upload yet",
    ],
    [
      "The approved allowance cannot cover this bounded processing plan.",
      "processing_allowance_unavailable",
      "approved processing allowance cannot cover",
    ],
    [
      "The approved private recording capacity is full.",
      "recording_capacity_full",
      "private recording capacity is full",
    ],
    [
      "Claim this upload before starting another analysis.",
      "claim_required",
      "Claim this upload",
    ],
  ])("translates the exact plan conflict %s", async (detail, reason, copy) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail }), { status: 409 }),
        ),
    );
    await expect(acquisition(path, { method: "POST" })).rejects.toMatchObject({
      status: 409,
      reason,
      message: expect.stringContaining(copy),
    });
  });

  it("translates an exhausted trial allowance on source upload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "Your current free call allowance has been used.",
          }),
          { status: 409 },
        ),
      ),
    );
    await expect(
      acquisition(`/submissions/${submissionId}/source`, { method: "PUT" }),
    ).rejects.toMatchObject({
      status: 409,
      reason: "trial_allowance_used",
      message: expect.stringContaining("trial allowance is used"),
    });
  });

  it("keeps an unknown conflict private and generic", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "private-provider-context" }), {
          status: 409,
        }),
      ),
    );
    await expect(acquisition(path)).rejects.toMatchObject({
      status: 409,
      message: new AcquisitionError(409).message,
    });
  });
});
describe("acquisition source-bound presentation", () => {
  it("preserves the full overview and mixed-script evidence through the v2 projection", () => {
    const parsed = parseAcquisitionReport(
      envelope,
      { submissionId, recordingId },
      parseTranscript(transcript, transcript.source_sha256),
    );
    expect(parsed.claimed).toBe(false);
    expect(parsed.report.overview).toEqual(envelope.report.content.overview);
    expect(parsed.report.report_sections).toEqual([]);
    expect(parsed.report.strengths).toEqual(envelope.report.content.strengths);
  });
  it.each([
    "source",
    "recording",
    "submission",
    "transcript",
    "numeric",
    "quote",
  ])("rejects a mismatched %s without presenting a report", (kind) => {
    const value = structuredClone(envelope);
    if (kind === "source") value.source_sha256 = "a".repeat(64);
    if (kind === "recording") value.recording_id = submissionId;
    if (kind === "submission") value.submission_id = recordingId;
    if (kind === "transcript") value.transcript_revision = "another-revision";
    if (kind === "numeric") value.report.numeric_publication = true;
    if (kind === "quote")
      value.report.content.strengths[0].evidence[0].quote =
        "An invented quotation";
    expect(() =>
      parseAcquisitionReport(
        value,
        { submissionId, recordingId },
        parseTranscript(transcript, transcript.source_sha256),
      ),
    ).toThrow();
  });
  it("rejects forged quota, paid upload policy and mismatched progress", () => {
    expect(parseAllowance(allowance).available_seconds).toBe(6000);
    expect(parsePolicy(policy).maximum_file_bytes).toBe(32 * 1024 ** 2);
    expect(parsePolicy(policy).maximum_call_seconds).toBe(3600);
    expect(
      parsePolicy({
        ...policy,
        privacy_details:
          "Approved service providers may process the recording.",
      }).privacy_details,
    ).toContain("Approved service providers");
    expect(() =>
      parsePolicy({ ...policy, maximum_file_bytes: 32 * 1024 ** 2 + 1 }),
    ).toThrow();
    expect(() =>
      parsePolicy({ ...policy, maximum_call_seconds: 3601 }),
    ).toThrow();
    expect(parseEntry(entry).site_key).toBe(entry.site_key);
    expect(() =>
      parseAllowance({ ...allowance, available_seconds: 5999 }),
    ).toThrow();
    expect(() => parsePolicy({ ...policy, max_cost_paise: 1 })).toThrow();
    expect(() =>
      parseProgress(
        { ...progress, source_sha256: "a".repeat(64) },
        parseSubmission(progress),
      ),
    ).toThrow();
  });
  it.each([3599, 3600])("accepts a call policy at %s seconds", (seconds) => {
    expect(
      parsePolicy({ ...policy, maximum_call_seconds: seconds })
        .maximum_call_seconds,
    ).toBe(seconds);
  });
  it("remembers only a UUID and rejects injected paths", () => {
    rememberSubmission(submissionId);
    expect(localStorage.length).toBe(1);
    expect(savedSubmissionId()).toBe(submissionId);
    localStorage.setItem(
      "ac.xray.submission.v1",
      "https://other.example/private",
    );
    expect(savedSubmissionId()).toBeNull();
  });
  it("uses a validated call selector and clears it without losing other navigation state", () => {
    window.history.replaceState(
      { marker: true },
      "",
      `/?call=${submissionId}&view=report#overview`,
    );
    expect(requestedSubmissionId()).toBe(submissionId);
    clearRequestedSubmission();
    expect(window.location.search).toBe("?view=report");
    expect(window.location.hash).toBe("#overview");
    expect(window.history.state).toEqual({ marker: true });
    window.history.replaceState(
      null,
      "",
      "/?call=https://other.example/private",
    );
    expect(requestedSubmissionId()).toBeNull();
  });
  it("keeps historical consumption visible when the server reduces the trial to sixty minutes", () => {
    expect(
      parseAllowance({
        allowance_seconds: 3600,
        committed_seconds: 4000,
        available_seconds: 0,
      }),
    ).toEqual({
      allowance_seconds: 3600,
      committed_seconds: 4000,
      available_seconds: 0,
    });
  });
  it("accepts the explicit unlimited internal tester allowance", () => {
    expect(
      parseAllowance({
        allowance_seconds: 3600,
        committed_seconds: 7200,
        available_seconds: 0,
        unlimited: true,
      }),
    ).toEqual({
      allowance_seconds: 3600,
      committed_seconds: 7200,
      available_seconds: 0,
      unlimited: true,
    });
    expect(() =>
      parseAllowance({
        allowance_seconds: 3600,
        committed_seconds: 7200,
        available_seconds: 0,
        unlimited: "true",
      }),
    ).toThrow();
  });
  it("accepts the authenticated learner entry without enabling a guest challenge", () => {
    const accountEntry = {
      ...entry,
      auth_mode: "account",
      site_key: null,
      challenge_action: null,
    };
    expect(parseEntry(accountEntry)).toMatchObject({
      enabled: true,
      site_key: null,
      challenge_action: null,
    });
    expect(() => parseEntry({ ...entry, site_key: null })).toThrow();
    expect(() => parseEntry({ ...accountEntry, auth_mode: "guest" })).toThrow();
    expect(() =>
      parseEntry({ ...accountEntry, site_key: entry.site_key }),
    ).toThrow();
    expect(() =>
      parseEntry({ ...accountEntry, allowance_seconds: 6001 }),
    ).toThrow();
  });
});
