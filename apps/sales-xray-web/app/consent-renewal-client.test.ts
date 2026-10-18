import { afterEach, expect, it, vi } from "vitest";

import {
  CONSENT_PATH,
  CONSENT_RENEW_PATH,
  ConsentRequestError,
  parseConsent,
  readConsent,
  renewConsent,
} from "./consent-renewal-client";

afterEach(() => vi.unstubAllGlobals());

const answer = {
  status: "renewal_required",
  current_version: "ac-learner-terms-privacy-2026-10-18-v2",
  recorded_version: "ac-learner-terms-privacy-2026-09-30-v1",
  consented_at: "2026-09-30T10:00:00Z",
  replayed: false,
  document: {
    version: "ac-learner-terms-privacy-2026-10-18-v2",
    acknowledgement:
      "I confirm that I am 18 or older and accept the current Authority Closers Terms and Privacy notice for my Authority Closers account.",
    terms_path: "/terms",
    privacy_path: "/privacy",
  },
};

it("reads the server's document without caching, from this origin only", async () => {
  const fetcher = vi.fn(async () => Response.json(answer));
  vi.stubGlobal("fetch", fetcher);
  await expect(readConsent()).resolves.toEqual({
    status: "renewal_required",
    current_version: answer.current_version,
    document: answer.document,
  });
  expect(fetcher).toHaveBeenCalledWith(
    CONSENT_PATH,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
});

it("accepts with the version the server showed and nothing else", async () => {
  const fetcher = vi.fn(async () =>
    Response.json({ ...answer, status: "current", replayed: false }),
  );
  vi.stubGlobal("fetch", fetcher);
  const record = await renewConsent(answer.document.version);
  expect(record.status).toBe("current");
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe(CONSENT_RENEW_PATH);
  expect(init).toMatchObject({
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  expect(JSON.parse(String(init.body))).toEqual({
    accepted: true,
    expected_version: answer.document.version,
  });
});

it.each([401, 403, 409, 500])("raises the status %s", async (status) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status })),
  );
  await expect(readConsent()).rejects.toMatchObject({ status });
  await expect(renewConsent("v")).rejects.toBeInstanceOf(ConsentRequestError);
});

it.each([
  ["not an object", "nope"],
  ["an unknown status", { ...answer, status: "maybe" }],
  ["no document", { ...answer, document: undefined }],
  [
    "an empty version",
    { ...answer, document: { ...answer.document, version: "" } },
  ],
  [
    "empty words",
    { ...answer, document: { ...answer.document, acknowledgement: "  " } },
  ],
])("rejects an answer with %s", (_name, body) => {
  expect(() => parseConsent(body)).toThrow("invalid_consent_response");
});

it.each([
  ["https://example.test/terms", "/terms"],
  ["//example.test/terms", "/terms"],
  ["/terms?next=1", "/terms"],
  [42, "/terms"],
  ["/terms", "/terms"],
])("only links to a page of this app: %s", (terms_path, expected) => {
  expect(
    parseConsent({ ...answer, document: { ...answer.document, terms_path } })
      .document.terms_path,
  ).toBe(expected);
});
