import { afterEach, expect, it, vi } from "vitest";
import { isLocalSandboxMediaUrl, LOCAL_SANDBOX_ORIGIN } from "./local-sandbox";

afterEach(() => vi.unstubAllEnvs());
const source = new URL(
  `${LOCAL_SANDBOX_ORIGIN}/v1/media/playback/fixture?token=not-authority`,
);

it("allows presentation only on the explicit same-origin local development sandbox", () => {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED", "true");
  expect(isLocalSandboxMediaUrl(source, LOCAL_SANDBOX_ORIGIN)).toBe(true);
  expect(isLocalSandboxMediaUrl(source, "http://remote.example")).toBe(false);
  expect(
    isLocalSandboxMediaUrl(
      new URL("http://remote.example/v1/media/playback/x"),
      LOCAL_SANDBOX_ORIGIN,
    ),
  ).toBe(false);
  expect(
    isLocalSandboxMediaUrl(
      new URL(`${LOCAL_SANDBOX_ORIGIN}/somewhere`),
      LOCAL_SANDBOX_ORIGIN,
    ),
  ).toBe(false);
});
it.each(["production", "test", undefined])(
  "cannot open the HTTP presentation seam in %s",
  (mode) => {
    vi.stubEnv("NODE_ENV", mode);
    vi.stubEnv("NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED", "true");
    expect(isLocalSandboxMediaUrl(source, LOCAL_SANDBOX_ORIGIN)).toBe(false);
  },
);
it("defaults closed in ordinary development", () => {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED", undefined);
  expect(isLocalSandboxMediaUrl(source, LOCAL_SANDBOX_ORIGIN)).toBe(false);
});
