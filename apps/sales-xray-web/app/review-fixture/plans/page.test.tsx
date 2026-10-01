import { expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import Page from "./page";
import PayPage from "./pay/page";
import ReturnPage from "./return/page";

it("the fictional billing routes are not routable outside local development", () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(() => Page()).toThrow("NEXT_NOT_FOUND");
  expect(() => PayPage()).toThrow("NEXT_NOT_FOUND");
  expect(() => ReturnPage()).toThrow("NEXT_NOT_FOUND");
  vi.unstubAllEnvs();
});
