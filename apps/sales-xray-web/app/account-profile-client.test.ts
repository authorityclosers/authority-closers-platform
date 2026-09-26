import { afterEach, expect, it, vi } from "vitest";
import {
  ACCOUNT_PROFILE_ELIGIBILITY_PATH,
  ACCOUNT_PROFILE_PATH,
  AccountProfileRequestError,
  readAccountProfile,
  readAccountProfileEligibility,
  normalizeProfilePhoneInput,
  updateAccountProfile,
  validE164Phone,
} from "./account-profile-client";

afterEach(() => vi.unstubAllGlobals());

const profile = {
  name: "Morgan Lee",
  email: "morgan@example.test",
  phone_number_e164: "+14155550123",
  phone_verified: false,
  profile_complete: false,
  revision: 2,
};

it("reads only the same-origin canonical account profile without caching", async () => {
  const fetcher = vi.fn(async () => Response.json(profile));
  vi.stubGlobal("fetch", fetcher);
  await expect(readAccountProfile()).resolves.toEqual(profile);
  expect(fetcher).toHaveBeenCalledWith(
    ACCOUNT_PROFILE_PATH,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
});

it("saves a full-name/mobile revision and requires an exact 204 eligibility response", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response(null, { status: 403 }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  await updateAccountProfile({
    full_name: "Morgan Lee",
    phone_number_e164: "+14155550123",
    expected_revision: 2,
  });
  expect(fetcher).toHaveBeenNthCalledWith(
    1,
    ACCOUNT_PROFILE_PATH,
    expect.objectContaining({
      method: "PUT",
      credentials: "same-origin",
      body: JSON.stringify({
        full_name: "Morgan Lee",
        phone_number_e164: "+14155550123",
        expected_revision: 2,
      }),
    }),
  );
  await expect(readAccountProfileEligibility()).resolves.toBe("not_ready");
  await expect(readAccountProfileEligibility()).resolves.toBe("eligible");
  expect(fetcher).toHaveBeenNthCalledWith(
    3,
    ACCOUNT_PROFILE_ELIGIBILITY_PATH,
    expect.objectContaining({ method: "GET", cache: "no-store" }),
  );
});

it("rejects malformed profile data and unexpected eligibility success", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ ...profile, revision: "2" })),
  );
  await expect(readAccountProfile()).rejects.toThrow(
    "invalid_profile_response",
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ ready: true })),
  );
  await expect(readAccountProfileEligibility()).rejects.toMatchObject({
    status: 200,
  } satisfies Partial<AccountProfileRequestError>);
});

it("accepts only canonical E.164 shape without guessing local numbers", () => {
  expect(validE164Phone("+14155550123")).toBe(true);
  expect(validE164Phone("+911234567890")).toBe(true);
  expect(validE164Phone("4155550123")).toBe(false);
  expect(validE164Phone("+1 415 555 0123")).toBe(false);
  expect(validE164Phone("+0123456789")).toBe(false);
});

it("normalizes ordinary Indian mobile input and formatted international input", () => {
  expect(normalizeProfilePhoneInput("9876543210", "IN")).toBe("+919876543210");
  expect(normalizeProfilePhoneInput("+1 (415) 555-0123", "US")).toBe(
    "+14155550123",
  );
  expect(normalizeProfilePhoneInput("415 555 0123", "US")).toBe("4155550123");
});
