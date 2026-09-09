import { afterEach, expect, it, vi } from "vitest";
import PracticePage, { dynamic } from "./page";
import { GET, dynamic as availabilityDynamic } from "./availability/route";
import { PracticeEngine } from "../components/practice-engine";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not-found");
  },
}));
vi.mock("../components/site-shell", () => ({ LearnerShell: "learner-shell" }));
vi.mock("../components/practice-arcade", () => ({
  PracticeArcade: "practice-catalog",
}));
vi.mock("../components/practice-engine", () => ({
  PracticeEngine: "practice-engine",
  PracticeRecognition: "practice-recognition",
}));
afterEach(() => vi.unstubAllEnvs());
const enable = () => {
  vi.stubEnv("AC_ENVIRONMENT", "local");
  vi.stubEnv("AC_PRACTICE_PILOT_ENABLED", "false");
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
};
it("keeps page and navigation availability runtime-dynamic, not image-build decisions", () => {
  expect(dynamic).toBe("force-dynamic");
  expect(availabilityDynamic).toBe("force-dynamic");
});
it.each(["staging", "production"])(
  "uses the same runtime %s gate for route and shared navigation",
  async (environment) => {
    const tenant = "11111111-1111-4111-8111-111111111111";
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("AC_ENVIRONMENT", environment);
    vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "false");
    vi.stubEnv("AC_PRACTICE_PILOT_ENABLED", "true");
    vi.stubEnv("AC_PRACTICE_PILOT_TENANT_ID", tenant);
    vi.stubEnv("AC_PUBLIC_LEARNER_TENANT_ID", tenant);
    vi.stubEnv(
      "AC_OPERATIONS_TENANT_ID",
      "22222222-2222-4222-8222-222222222222",
    );
    expect(
      await PracticePage({ searchParams: Promise.resolve({ set: "gaps" }) }),
    ).toBeTruthy();
    const admitted = GET();
    expect(admitted.headers.get("cache-control")).toBe("private, no-store");
    expect(await admitted.json()).toEqual({ enabled: true });
    vi.stubEnv("AC_PRACTICE_PILOT_ENABLED", "false");
    await expect(
      PracticePage({ searchParams: Promise.resolve({}) }),
    ).rejects.toThrow("not-found");
    expect(await GET().json()).toEqual({ enabled: false });
  },
);
it("does not expose the local earned pilot in a production build", async () => {
  enable();
  vi.stubEnv("NODE_ENV", "production");
  await expect(
    PracticePage({ searchParams: Promise.resolve({}) }),
  ).rejects.toThrow("not-found");
});
it("requires the explicit sandbox environment", async () => {
  enable();
  vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "false");
  await expect(
    PracticePage({ searchParams: Promise.resolve({ set: "next-move" }) }),
  ).rejects.toThrow("not-found");
});
it("mounts a separately keyed focused durable attempt without app navigation", async () => {
  enable();
  const attempt = "11111111-1111-4111-8111-111111111111";
  const page = await PracticePage({
    searchParams: Promise.resolve({ set: "next-move", attempt }),
  });
  expect(page.type).toBe(PracticeEngine);
  expect(page.key).toBe(`next-move:${attempt}`);
  expect(page.props).toEqual({ setId: "next-move", attemptId: attempt });
});
it.each([
  { set: ["next-move", "gaps"] },
  { set: "../profile" },
  { set: "next-move", attempt: ["one", "two"] },
  { set: "next-move", attempt: "not-an-id" },
  { attempt: "11111111-1111-4111-8111-111111111111" },
])("rejects malformed or ambiguous practice selectors %j", async (query) => {
  enable();
  await expect(
    PracticePage({ searchParams: Promise.resolve(query) }),
  ).rejects.toThrow("not-found");
});
