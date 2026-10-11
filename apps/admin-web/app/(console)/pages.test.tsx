/**
 * Every console page renders when its data can't be read (Pulse rule: a
 * missing API route or field never crashes a page), and when reads succeed
 * with empty bodies. Pages fetch on the server; here every read fails, or
 * returns {}, and each page must still render a header and an honest card.
 */
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult } from "../lib/server-api";

const mode = vi.hoisted(() => ({
  value: "unavailable" as "unavailable" | "empty",
}));

vi.mock("../lib/server-api", async (original) => {
  const actual = await original<typeof import("../lib/server-api")>();
  return {
    ...actual,
    adminRead: async <T,>(
      _path: string,
      normalize: (raw: unknown) => T,
    ): Promise<ApiResult<T>> =>
      mode.value === "empty"
        ? { ok: true, status: 200, data: normalize({}) }
        : { ok: false, status: 503, error: actual.MESSAGES.reconnecting },
  };
});
vi.mock("../lib/console-access", () => ({
  loadConsoleAccess: async () => ({
    state: "preview",
    email: null,
    displayName: null,
    role: null,
    permissions: [],
    platform: [
      "platform_tenants_read",
      "platform_billing_manage",
      "platform_content_safety_manage",
    ],
  }),
  consoleEnvironment: () => "preview",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  redirect: () => {
    throw new Error("NEXT_REDIRECT");
  },
}));

const root = new URL(".", import.meta.url).pathname;
function pages(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return pages(path);
    return name === "page.tsx" ? [path] : [];
  });
}

const UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const params = () =>
  Promise.resolve({
    recordingId: UUID,
    callId: "syn-x-J01-C-01",
    assignmentId: UUID,
    runId: UUID,
  });
const searchParams = Promise.resolve({ recording: UUID, tab: "billing" });

describe.each(["unavailable", "empty"] as const)(
  "console pages when reads are %s",
  (current) => {
    beforeEach(() => {
      mode.value = current;
    });
    for (const file of pages(root)) {
      const name = `/${relative(root, file).replace(/\/?page\.tsx$/, "")}`;
      it(`${name} renders without throwing`, async () => {
        const page = (await import(/* @vite-ignore */ file)) as {
          default: (props: unknown) => unknown;
        };
        const element = await page.default({
          params: params(),
          searchParams,
        });
        const markup = renderToStaticMarkup(element as React.ReactElement);
        expect(markup.length).toBeGreaterThan(50);
        expect(markup).toMatch(/<h1|role="status"/);
      });
    }
  },
);
