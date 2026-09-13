// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewWorkspace } from "./review-workspace";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/v1/me")) {
        return Promise.resolve(
          Response.json({
            person_id: "11111111-1111-4111-8111-111111111111",
            email: "reviewer@example.test",
            display_name: "Reviewer",
            email_verified_at: "2026-09-13T00:00:00Z",
            selected_tenant_id: "22222222-2222-4222-8222-222222222222",
            membership_role: "support",
            permissions: ["admin_surface", "learning_review"],
          }),
        );
      }
      if (path.endsWith("/v1/context")) {
        return Promise.resolve(
          Response.json({
            person_id: "11111111-1111-4111-8111-111111111111",
            session_id: "33333333-3333-4333-8333-333333333333",
            tenant_id: "22222222-2222-4222-8222-222222222222",
            membership_role: "support",
            permissions: ["admin_surface", "learning_review"],
          }),
        );
      }
      if (path.endsWith("/v1/me/studio-access")) {
        return Promise.resolve(
          Response.json({
            person_id: "11111111-1111-4111-8111-111111111111",
            session_id: "33333333-3333-4333-8333-333333333333",
            tenant_id: "22222222-2222-4222-8222-222222222222",
            studio_capabilities: [],
          }),
        );
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("assigned review workspace", () => {
  it("keeps the report and save controls unavailable until an authorized assignment arrives", async () => {
    await act(async () =>
      root.render(<ReviewWorkspace assignmentId="assignment-7" />),
    );

    expect(container.textContent).toContain("Conversation review");
    expect(container.textContent).toContain("assignment-7");
    expect(container.textContent).toContain("The review bridge contract is pending its server-owned DTO.");
    expect(container.textContent).toContain("No report, reviewer, clip, or saved review is shown");
    expect(
      [...container.querySelectorAll("button[disabled]")].some((button) =>
        button.textContent?.includes("Save append-only proposal"),
      ),
    ).toBe(true);
  });
});
