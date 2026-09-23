import { afterEach, expect, it, vi } from "vitest";
import {
  AUTH_COMPLETE_MESSAGE,
  emailCodeRequest,
  isAuthCompleteMessage,
  maskedEmail,
  parseAuthenticatedAccount,
  parseCanonicalSession,
  parseCodeTiming,
  parseEmailCodeConfig,
  passwordLogin,
  readCanonicalSession,
  validAuthFlow,
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
    parseEmailCodeConfig({ ...config, enabled: false, consent_version: null }),
  ).toEqual({ ...config, enabled: false, consent_version: null });
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
    isAuthCompleteMessage({ type: AUTH_COMPLETE_MESSAGE, flow }, flow),
  ).toBe(true);
  for (const candidate of [
    {
      type: AUTH_COMPLETE_MESSAGE,
      flow: "6d5be9d7-bce6-49c0-9f67-3e68e5de9b45",
    },
    { type: AUTH_COMPLETE_MESSAGE, flow, token: "synthetic" },
    { type: "other", flow },
  ])
    expect(isAuthCompleteMessage(candidate, flow)).toBe(false);
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
