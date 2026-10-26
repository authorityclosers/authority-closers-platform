import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../analysis-start", () => ({
  startAnalysis: vi.fn(async () => ({ kind: "accepted", plan: null })),
}));
vi.mock("../call-label-client", () => ({
  readCallLabel: vi.fn(async () => null),
  renameCall: vi.fn(async () => undefined),
}));

import type { UploadPolicy } from "../acquisition-client";
import { startAnalysis } from "../analysis-start";
import type { LeadDetail } from "./leads-client";
import { attemptId, runRecordingUpload } from "./simulated-call";

// 26 Oct 2026: a seller's tap went through the recording import, which only
// owners and admins may use. A real call's recording is now the seller's own
// upload, as the studio sends it.
const LEAD = {
  lead: { lead_id: "lead-1", name: "Asha Rao" },
  events: [],
} as unknown as LeadDetail;
const POLICY = {
  title: "Recording terms",
  description: "Fictional terms for the test.",
  policy_sha256: "a".repeat(64),
} as UploadPolicy;
const RECORDING = "00000000-0000-4000-8000-0000000000bb";

type Sent = {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: unknown;
};

let sent: Sent[];
let stored: Record<string, string> | null;

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  sent = [];
  stored = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      const method = init.method ?? "GET";
      const headers = Object.fromEntries(
        Object.entries((init.headers ?? {}) as Record<string, string>).map(
          ([name, value]) => [name.toLowerCase(), value],
        ),
      );
      sent.push({ method, url, headers, body: init.body });
      const submission = url.match(
        /\/submissions\/([0-9a-f-]{36})(\/source)?$/,
      );
      if (submission && method === "PUT") {
        stored = {
          submission_id: submission[1]!,
          recording_id: RECORDING,
          source_sha256: headers["x-source-sha256"]!,
        };
        return json(stored, 202);
      }
      if (submission && method === "GET")
        return stored ? json(stored) : json({ detail: "Not found" }, 404);
      if (url.endsWith("/leads/lead-1/recordings") && method === "POST")
        return json({ ...LEAD, events: [{ kind: "call", recording: true }] });
      return json({ detail: "Unexpected" }, 500);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(startAnalysis).mockClear();
  localStorage.clear();
});

const upload = (attempt = "try-1", callEventId: string | null = "event-1") =>
  runRecordingUpload({
    lead: LEAD,
    file: new File(["fictional audio"], "call.m4a", { type: "audio/mp4" }),
    policy: POLICY,
    onStep: () => undefined,
    signal: new AbortController().signal,
    attempt,
    callEventId,
  });

it("uploads the seller's own recording, puts it on the lead and starts its analysis", async () => {
  const next = await upload();
  const id = await attemptId("lead-recording:lead-1:try-1");
  const put = sent.find((item) => item.method === "PUT");
  expect(put?.url).toBe(
    `/v1/conversation/acquisition/submissions/${id}/source`,
  );
  // This call's own tick, on the terms in force.
  expect(put?.headers["x-upload-consent"]).toBe("accepted");
  expect(put?.headers["x-upload-policy"]).toBe(POLICY.policy_sha256);
  expect(put?.headers["x-source-sha256"]).toMatch(/^[0-9a-f]{64}$/);
  // Never the import, which a seller may not use.
  expect(sent.some((item) => /import/.test(item.url))).toBe(false);
  const attach = sent.find((item) => item.url.endsWith("/recordings"));
  expect(JSON.parse(String(attach?.body))).toMatchObject({
    submission_id: id,
    call_event_id: "event-1",
  });
  expect(vi.mocked(startAnalysis).mock.calls[0]?.[0]).toMatchObject({
    bound: { id, sha: put?.headers["x-source-sha256"] },
    policySha256: POLICY.policy_sha256,
    reportLanguage: "en",
  });
  expect(next.events).toEqual([{ kind: "call", recording: true }]);
  // The studio's open call is left alone.
  expect(localStorage.length).toBe(0);
});

it("finds a try that was already saved instead of sending it again", async () => {
  await upload();
  sent = [];
  await upload();
  expect(sent.filter((item) => item.method === "PUT")).toEqual([]);
  expect(vi.mocked(startAnalysis)).toHaveBeenCalledTimes(2);
});

it("puts the call on the lead once, however often an attempt is tried", async () => {
  await upload();
  await upload();
  const commands = sent
    .filter((item) => item.url.endsWith("/recordings"))
    .map((item) => JSON.parse(String(item.body)).command_id);
  expect(commands).toHaveLength(2);
  expect(commands[1]).toBe(commands[0]);
  expect(commands[0]).toBe(
    await attemptId("lead-recording-attach:lead-1:try-1"),
  );
});

it("says why when the analysis can't start, with the call already on the lead", async () => {
  vi.mocked(startAnalysis).mockResolvedValueOnce({
    kind: "needs_action",
    reason: "checks_pending",
    message: "Your recording is saved. Its file checks are still running.",
  });
  await expect(upload()).rejects.toThrow(
    "Your recording is saved. Its file checks are still running.",
  );
  expect(sent.some((item) => item.url.endsWith("/recordings"))).toBe(true);
});

// Owner, 26 Oct 2026: "Analyse my calls automatically", the seller's standing
// consent, on the upload and on the plan.
it("uploads and starts under a standing consent when the card says so", async () => {
  await runRecordingUpload({
    lead: LEAD,
    file: new File(["fictional audio"], "call.m4a", { type: "audio/mp4" }),
    policy: POLICY,
    onStep: () => undefined,
    signal: new AbortController().signal,
    attempt: "try-1",
    consent: "standing",
  });
  const put = sent.find((item) => item.method === "PUT");
  expect(put?.headers["x-upload-consent"]).toBe("standing");
  expect(vi.mocked(startAnalysis).mock.calls[0]?.[0]).toMatchObject({
    standing: true,
  });
});

it("says the consent isn't on when the server refuses it, for the tap to follow", async () => {
  vi.mocked(startAnalysis).mockResolvedValueOnce({
    kind: "needs_action",
    reason: "start_failed",
    message: "Analysis is not available for this call yet.",
    status: 409,
  });
  const refused = runRecordingUpload({
    lead: LEAD,
    file: new File(["fictional audio"], "call.m4a", { type: "audio/mp4" }),
    policy: POLICY,
    onStep: () => undefined,
    signal: new AbortController().signal,
    attempt: "try-1",
    consent: "standing",
  });
  await expect(refused).rejects.toMatchObject({
    status: 409,
    message: "Automatic analysis isn't on for you here. Tap Analyse the call.",
  });
});

it("fixes one call id per lead and attempt", async () => {
  const id = await attemptId("lead-recording:lead-1:try-1");
  expect(id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  expect(await attemptId("lead-recording:lead-1:try-1")).toBe(id);
  expect(await attemptId("lead-recording:lead-1:try-2")).not.toBe(id);
});
