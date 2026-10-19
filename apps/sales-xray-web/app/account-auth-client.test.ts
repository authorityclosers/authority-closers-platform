// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import {
  AUTH_COMPLETE_MESSAGE,
  emailCodeRequest,
  isAuthCompleteMessage,
  parseAuthCompletionQuery,
  parseAuthCompletionUrl,
  readGoogleCompletion,
  maskedEmail,
  parseAuthenticatedAccount,
  parseCanonicalSession,
  parseCodeTiming,
  parseEmailCodeConfig,
  passwordLogin,
  readCanonicalSession,
  validAuthFlow,
  keepSignInResult,
  popupHostileBrowser,
  rememberRedirectSignIn,
  safeReturnPath,
  takeRedirectSignIn,
  takeSignInResult,
} from "./account-auth-client";

afterEach(() => vi.unstubAllGlobals());
const config = {
  enabled: true,
  consent_version: "test-v1",
  google_enabled: true,
  expires_in_seconds: 600,
  resend_after_seconds: 60,
};

it("accepts server policy timing, never inventing account existence or accepting malformed capabilities", () => {
  expect(parseEmailCodeConfig(config)).toEqual(config);
  expect(
    parseEmailCodeConfig({
      ...config,
      enabled: false,
      google_enabled: false,
      consent_version: null,
    }),
  ).toEqual({
    ...config,
    enabled: false,
    google_enabled: false,
    consent_version: null,
  });
  expect(() =>
    parseEmailCodeConfig({ ...config, enabled: false, consent_version: null }),
  ).toThrow();
  for (const value of [
    null,
    {},
    { ...config, enabled: "yes" },
    { ...config, consent_version: "" },
    { ...config, resend_after_seconds: 601 },
    { ...config, expires_in_seconds: Infinity },
  ])
    expect(() => parseEmailCodeConfig(value)).toThrow();
  expect(() =>
    parseCodeTiming({ expires_in_seconds: 600, resend_after_seconds: -1 }),
  ).toThrow();
});

it("rejects a popup signal unless its exact flow matches", () => {
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  expect(validAuthFlow(flow)).toBe(true);
  expect(validAuthFlow("../../../login")).toBe(false);
  expect(
    isAuthCompleteMessage(
      { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "success" },
      flow,
    ),
  ).toBe(true);
  for (const candidate of [
    {
      type: AUTH_COMPLETE_MESSAGE,
      flow: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    },
    { type: AUTH_COMPLETE_MESSAGE, flow, token: "synthetic" },
    { type: AUTH_COMPLETE_MESSAGE, flow },
    { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "success", extra: true },
    { type: AUTH_COMPLETE_MESSAGE, flow, auth_result: "pending" },
    { type: "other", flow },
  ])
    expect(isAuthCompleteMessage(candidate, flow)).toBe(false);
});

it("parses only exact, unambiguous completion query and URL shapes", () => {
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  expect(parseAuthCompletionQuery({ flow, auth_result: "success" })).toEqual({
    flow,
    result: "success",
  });
  for (const query of [
    { flow: [flow], auth_result: "success" },
    { flow, auth_result: ["success", "failed"] },
    { flow, auth_result: "unknown" },
    { flow, auth_result: "success", extra: "x" },
    { flow: "bad", auth_result: "success" },
  ])
    expect(parseAuthCompletionQuery(query)).toBeNull();
  const origin = "https://sales.example.test";
  expect(
    parseAuthCompletionUrl(
      `${origin}/auth/complete?flow=${flow}&auth_result=failed`,
      origin,
      flow,
    ),
  ).toBe("failed");
  const invalidUrls = [
    [
      `${origin}/auth/complete?flow=${flow}&flow=${flow}&auth_result=success`,
      flow,
    ],
    [`${origin}/auth/complete?flow=${flow}&auth_result=success&extra=x`, flow],
    [`${origin}/auth/complete?flow=${flow}&auth_result=success#fragment`, flow],
    [`${origin}/other?flow=${flow}&auth_result=success`, flow],
    [
      `https://evil.example.test/auth/complete?flow=${flow}&auth_result=success`,
      flow,
    ],
    [
      `${origin}/auth/complete?flow=${flow}&auth_result=success`,
      "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    ],
  ] as const;
  for (const [url, candidateFlow] of invalidUrls)
    expect(parseAuthCompletionUrl(url, origin, candidateFlow)).toBeNull();
});

it("requires an exact matched response from the Google completion endpoint", async () => {
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  const fetcher = vi.fn().mockResolvedValue(Response.json({ matched: true }));
  vi.stubGlobal("fetch", fetcher);
  await expect(
    readGoogleCompletion(flow, new AbortController().signal),
  ).resolves.toBe(true);
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/auth/google/completion",
    expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      body: JSON.stringify({ flow_id: flow }),
    }),
  );
  fetcher.mockResolvedValueOnce(
    Response.json({ matched: true, person_id: "private" }),
  );
  await expect(
    readGoogleCompletion(flow, new AbortController().signal),
  ).rejects.toThrow();
});

it("requires canonical person and session values before reporting login", async () => {
  const session = {
    person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
    session_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    selected_tenant_id: null,
    workspaces: [],
  };
  expect(parseCanonicalSession(session)).toEqual({
    personId: session.person_id,
    sessionId: session.session_id,
  });
  expect(() =>
    parseCanonicalSession({ ...session, session_id: "bad" }),
  ).toThrow();
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json(session));
  vi.stubGlobal("fetch", fetcher);
  await expect(
    readCanonicalSession(new AbortController().signal),
  ).resolves.toEqual({
    personId: session.person_id,
    sessionId: session.session_id,
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/me/workspaces",
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      redirect: "error",
    }),
  );
});

it("checks a password session without navigating the document or exposing the password", async () => {
  const session = {
    person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
    session_id: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    selected_tenant_id: null,
    workspaces: [],
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ authenticated: true }))
    .mockResolvedValueOnce(Response.json(session));
  vi.stubGlobal("fetch", fetcher);
  await passwordLogin(
    "existing@example.test",
    "synthetic-password",
    new AbortController().signal,
  );
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
    "/v1/auth/password/login",
    "/v1/me/workspaces",
  ]);
  expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual({
    email: "existing@example.test",
    password: "synthetic-password",
  });
});

it("requires confirmed account identity before allowing the parent to resume", () => {
  const body = {
    authenticated: true,
    person_id: "eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
    account_created: true,
    profile_complete: false,
  };
  expect(parseAuthenticatedAccount(body)).toEqual({
    personId: body.person_id,
    profileComplete: false,
  });
  for (const invalid of [
    {},
    { ...body, authenticated: false },
    { ...body, person_id: "" },
    { ...body, profile_complete: "true" },
  ])
    expect(() => parseAuthenticatedAccount(invalid)).toThrow();
});

it("sends only a same-origin JSON auth request and never exposes provider error bodies", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "private-provider-diagnostics" }), {
      status: 400,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(
    emailCodeRequest("verify", new AbortController().signal, {
      email: "fictional@example.test",
      code: "123456",
    }),
  ).rejects.toThrow("sign-in-unavailable");
  expect(fetcher).toHaveBeenCalledWith(
    "/v1/auth/email-code/verify",
    expect.objectContaining({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      method: "POST",
    }),
  );
  expect(fetcher.mock.calls[0][1].body).toBe(
    JSON.stringify({ email: "fictional@example.test", code: "123456" }),
  );
  expect(maskedEmail("fictional@example.test")).toBe("f•••@example.test");
});

it("requests current Sales Xray consent capability on the correct surface", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json(config));
  vi.stubGlobal("fetch", fetcher);
  await emailCodeRequest("config", new AbortController().signal);
  expect(fetcher.mock.calls[0][0]).toBe(
    "/v1/auth/email-code/config?surface=sales_xray",
  );
});

it("knows the in-app browsers that break sign-in windows", () => {
  for (const agent of [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 [FBAN/FBIOS;FBAV/450.0.0.38.108;FBBV/1]",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/120 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/450.0.0.38.108;]",
    "Mozilla/5.0 (iPhone) AppleWebKit Mobile/15E148 Instagram 312.0.0.32.112 (iPhone15,2; iOS 17_0)",
    "Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36 Line/13.20.0",
  ])
    expect(popupHostileBrowser(agent)).toBe(true);
  for (const agent of [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36",
    "Mozilla/5.0 (Macintosh) AppleWebKit Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36 SalesXrayApp/0.3.70",
    "Pipeline/2.0",
    null,
  ])
    expect(popupHostileBrowser(agent)).toBe(false);
});

it("keeps only same-origin app pages as a place to return to", () => {
  expect(safeReturnPath("/login?next=/leads")).toBe("/login?next=/leads");
  expect(safeReturnPath("/leads#tab")).toBe("/leads");
  for (const value of [
    "//attacker.example/",
    "https://attacker.example/",
    "/\\attacker.example",
    "/auth/complete?flow=x",
    "/v1/auth/google/start",
    "leads",
    "/" + "a".repeat(600),
    42,
  ])
    expect(safeReturnPath(value)).toBe("/");
});

it("hands a full-page sign-in back once, for its own flow and not too late", () => {
  const flow = "eaed7960-d4d0-4675-bd34-5b6a7d9c598d";
  window.sessionStorage.clear();
  expect(rememberRedirectSignIn("not-a-flow", "google", "/")).toBe(false);
  expect(rememberRedirectSignIn(flow, "google", "/leads")).toBe(true);
  expect(takeRedirectSignIn("6d5be9d7-bce6-49c0-9f67-3e68e5de9b45")).toBeNull();
  rememberRedirectSignIn(flow, "google", "/leads");
  expect(takeRedirectSignIn(flow)).toEqual({
    provider: "google",
    returnTo: "/leads",
  });
  expect(takeRedirectSignIn(flow)).toBeNull();
  window.sessionStorage.setItem(
    "sx.signIn.redirect",
    JSON.stringify({ flow, provider: "google", returnTo: "/", at: 1 }),
  );
  expect(takeRedirectSignIn(flow)).toBeNull();
  keepSignInResult("unavailable", "google");
  expect(takeSignInResult()).toEqual({
    result: "unavailable",
    provider: "google",
  });
  expect(takeSignInResult()).toBeNull();
  window.sessionStorage.setItem(
    "sx.signIn.result",
    JSON.stringify({ result: "success", provider: "google", at: 1 }),
  );
  expect(takeSignInResult()).toBeNull();
});
