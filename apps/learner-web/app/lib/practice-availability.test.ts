import { describe, expect, it } from "vitest";
import { isPracticeUiEnabled } from "./practice-availability";

const tenant = "11111111-1111-4111-8111-111111111111";
const operations = "22222222-2222-4222-8222-222222222222";
const pilot = {
  NODE_ENV: "production",
  AC_ENVIRONMENT: "production",
  AC_PRACTICE_PILOT_ENABLED: "true",
  AC_PRACTICE_PILOT_TENANT_ID: tenant,
  AC_PUBLIC_LEARNER_TENANT_ID: tenant,
  AC_OPERATIONS_TENANT_ID: operations,
};

it("defaults disabled and does not promote local/public build flags", () => {
  expect(isPracticeUiEnabled({})).toBe(false);
  expect(
    isPracticeUiEnabled({ ...pilot, AC_PRACTICE_PILOT_ENABLED: "false" }),
  ).toBe(false);
  expect(
    isPracticeUiEnabled({
      NODE_ENV: "production",
      AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
      NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED: "true",
    }),
  ).toBe(false);
});
it("retains only the explicit disposable-local development mode", () => {
  expect(
    isPracticeUiEnabled({
      NODE_ENV: "development",
      AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
    }),
  ).toBe(true);
  expect(
    isPracticeUiEnabled({
      NODE_ENV: "development",
      AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
      AC_ENVIRONMENT: "production",
    }),
  ).toBe(false);
});
it.each(["staging", "production"])(
  "accepts exact runtime %s pilot scope",
  (environment) => {
    expect(isPracticeUiEnabled({ ...pilot, AC_ENVIRONMENT: environment })).toBe(
      true,
    );
  },
);
describe("invalid or ambiguous activation is hidden", () => {
  it.each([
    { AC_PRACTICE_PILOT_TENANT_ID: undefined },
    { AC_PRACTICE_PILOT_TENANT_ID: "not-a-uuid" },
    { AC_PUBLIC_LEARNER_TENANT_ID: operations },
    { AC_OPERATIONS_TENANT_ID: tenant },
    { AC_OPERATIONS_TENANT_ID: undefined },
    { AC_ENVIRONMENT: "local" },
    { AC_ENVIRONMENT: "development" },
    { NODE_ENV: "development" },
    { AC_DEV_LOCAL_SANDBOX_ENABLED: "true" },
    { AC_PRACTICE_ARCADE_PREVIEW_ENABLED: "true" },
    { AC_PRACTICE_PILOT_ENABLED: "TRUE" },
  ])("rejects %j", (change) =>
    expect(isPracticeUiEnabled({ ...pilot, ...change })).toBe(false),
  );
});
