// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

import { ReviewWorkspace } from "./review-workspace";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ids = {
  assignment: "11111111-1111-4111-8111-111111111111",
  tenant: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
  reviewer: "44444444-4444-4444-8444-444444444444",
  actor: "55555555-5555-4555-8555-555555555555",
  recording: "66666666-6666-4666-8666-666666666666",
  permission: "77777777-7777-4777-8777-777777777777",
  checkpoint: "88888888-8888-4888-8888-888888888888",
};
const digest = "a".repeat(64);
const assignment = {
  schema_id: "ac.sales-xray.review-assignment/1" as const,
  id: ids.assignment,
  tenant_id: ids.tenant,
  run_id: ids.run,
  run_generation: 2,
  recipe_revision: "recipe-v1",
  source: {
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    permission_id: ids.permission,
    provenance_ref:
      "ref:conversation-permission:77777777-7777-4777-8777-777777777777",
  },
  checkpoint: {
    id: ids.checkpoint,
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: digest,
    source_revision: 1,
    stage: "C2" as const,
    revision: "checkpoint-v1",
    cache_key: digest,
    manifest_sha256: digest,
    payload_sha256: digest,
  },
  reviewer_person_id: ids.reviewer,
  allowed_lenses: ["sales", "technical"] as const,
  state: "assigned" as const,
  created_at_epoch: 1_800_000_000,
  expires_at_epoch: 1_800_086_400,
  created_by_person_id: ids.actor,
};
const { schema_id: schemaId, ...assignmentFields } = assignment;
const wireAssignment = { schema: schemaId, ...assignmentFields };

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function createdResponse(init: RequestInit | undefined): Response {
  const body = JSON.parse(init?.body as string);
  return jsonResponse(
    {
      ...wireAssignment,
      run_id: body.run_id,
      reviewer_person_id: body.reviewer_person_id,
      allowed_lenses: body.allowed_lenses,
      expires_at_epoch: body.expires_at_epoch,
      created_at_epoch: Math.floor(Date.now() / 1000),
    },
    201,
  );
}

function setInputValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

let container: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
let queueResponses: Array<Response | Promise<Response>>;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  queueResponses = [jsonResponse({ items: [] })];
  fetchMock = vi.fn<typeof fetch>((input, init) => {
    const path = String(input);
    if (path.endsWith("/v1/me")) {
      return Promise.resolve(
        jsonResponse({
          person_id: ids.actor,
          email: "admin@authorityclosers.com",
          display_name: "Operations Admin",
          email_verified_at: "2026-09-13T00:00:00Z",
          selected_tenant_id: ids.tenant,
          membership_role: "admin",
          permissions: ["admin_surface"],
        }),
      );
    }
    if (path.endsWith("/v1/context")) {
      return Promise.resolve(
        jsonResponse({
          person_id: ids.actor,
          session_id: "99999999-9999-4999-8999-999999999999",
          tenant_id: ids.tenant,
          membership_role: "admin",
          permissions: ["admin_surface"],
        }),
      );
    }
    if (path.endsWith("/v1/me/studio-access")) {
      return Promise.resolve(
        jsonResponse({
          person_id: ids.actor,
          session_id: "99999999-9999-4999-8999-999999999999",
          tenant_id: ids.tenant,
          studio_capabilities: [],
        }),
      );
    }
    if (
      path.includes("/v1/admin/conversation/review-assignments") &&
      init?.method === "GET"
    ) {
      return Promise.resolve(
        queueResponses.shift() ?? jsonResponse({ items: [] }),
      );
    }
    if (
      path.includes("/v1/admin/conversation/review-assignments") &&
      path.endsWith("/revoke")
    ) {
      return Promise.resolve(
        jsonResponse({ ...wireAssignment, state: "revoked" }),
      );
    }
    if (path.endsWith("/v1/admin/conversation/review-assignments")) {
      return Promise.resolve(createdResponse(init));
    }
    return Promise.resolve(new Response(null, { status: 404 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "review-key-1") });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function settle() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

async function render(props: { assignmentId?: string } = {}) {
  await act(async () =>
    root.render(
      <ReviewWorkspace
        {...props}
        academyOrigin="https://learner.authorityclosers.com"
      />,
    ),
  );
  await settle();
}

describe("Admin review assignment workspace", () => {
  it("loads the queue after Strict Mode replays the mount effects", async () => {
    queueResponses = Array.from({ length: 4 }, () =>
      jsonResponse({ items: [wireAssignment] }),
    );
    await act(async () =>
      root.render(
        <StrictMode>
          <ReviewWorkspace academyOrigin="https://learner.authorityclosers.com" />
        </StrictMode>,
      ),
    );
    await settle();
    expect(container.textContent).toContain("Reviewer 44444444…4444");
    expect(container.textContent).not.toContain("Loading assignments");
  });

  it("renders the real server queue and never invents reviewer identities or submission controls", async () => {
    queueResponses = [jsonResponse({ items: [wireAssignment] })];
    await render({ assignmentId: ids.assignment });

    expect(container.textContent).toContain(
      "Active and historical assignments",
    );
    expect(container.textContent).toContain("Reviewer 44444444…4444");
    expect(container.textContent).toContain("Open in Academy");
    expect(container.textContent).not.toContain("Dipak");
    expect(container.textContent).not.toContain("PREVIEW DATA");
    expect(container.textContent).toContain(
      "Saved changes confirmed by the service",
    );
    expect(container.textContent).not.toContain("Save append-only proposal");
    expect(container.textContent).not.toContain("NOT WRITTEN");
    expect(container.textContent).not.toContain("AUDIT EVENT: NONE");
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/admin/conversation/review-assignments?limit=50",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("creates an assignment, keeps confirmed success, and retains it when a later queue refresh fails", async () => {
    await render();
    const inputs = container.querySelectorAll<HTMLInputElement>("input");
    await act(async () => {
      setInputValue(inputs[0]!, ids.run);
      setInputValue(inputs[1]!, ids.reviewer);
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>("button.button-primary")!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await settle();

    expect(container.textContent).toContain(
      "Assignment created and confirmed.",
    );
    expect(container.textContent).toContain("Reviewer 44444444…4444");
    const createCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect((createCall?.[1]?.headers as Headers).get("Idempotency-Key")).toBe(
      "review-key-1",
    );

    queueResponses = [jsonResponse({ detail: "temporary queue outage" }, 503)];
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>(
          "[aria-label='Refresh review assignment queue']",
        )!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await settle();
    expect(container.textContent).toContain(
      "Assignment created and confirmed.",
    );
    expect(container.textContent).toContain("temporary queue outage");
    expect(container.textContent).toContain("Reviewer 44444444…4444");
  });

  it("reuses the same idempotency key after a retryable create failure", async () => {
    await render();
    const inputs = container.querySelectorAll<HTMLInputElement>("input");
    await act(async () => {
      setInputValue(inputs[0]!, ids.run);
      setInputValue(inputs[1]!, ids.reviewer);
    });
    let createAttempts = 0;
    fetchMock.mockImplementation((input, init) => {
      const path = String(input);
      if (
        path.endsWith("/v1/admin/conversation/review-assignments") &&
        init?.method === "POST"
      ) {
        createAttempts += 1;
        return Promise.resolve(
          createAttempts === 1
            ? jsonResponse({ detail: "temporary failure" }, 503)
            : createdResponse(init),
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>("button.button-primary")!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await settle();
    expect(container.textContent).toContain("Retry same request");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Retry same request"))!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await settle();
    expect(container.textContent).toContain(
      "Assignment created and confirmed.",
    );
    const postCalls = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(postCalls).toHaveLength(2);
    expect((postCalls[0]![1]!.headers as Headers).get("Idempotency-Key")).toBe(
      "review-key-1",
    );
    expect((postCalls[1]![1]!.headers as Headers).get("Idempotency-Key")).toBe(
      "review-key-1",
    );
  });

  it("shows the dynamic assignment detail and applies a server-confirmed revoke", async () => {
    queueResponses = [jsonResponse({ items: [wireAssignment] })];
    await render({ assignmentId: ids.assignment });
    expect(container.textContent).toContain("Assignment lineage");
    expect(container.textContent).toContain(ids.tenant);
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Revoke")!
        .click();
    });
    expect(container.textContent).toContain("Confirm revoke");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Confirm revoke"))!
        .click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await settle();
    expect(container.textContent).toContain(
      "Revocation confirmed by the server.",
    );
    expect(container.textContent).toContain("Revoked");
    const revokeCall = fetchMock.mock.calls.find(([path]) =>
      String(path).endsWith("/revoke"),
    );
    expect(revokeCall?.[0]).toBe(
      `/v1/admin/conversation/review-assignments/${ids.assignment}/revoke`,
    );
  });
});
