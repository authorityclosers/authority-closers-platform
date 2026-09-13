// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ReviewInvitationPanel } from "./review-invitation-panel";
import { createReviewInvitation } from "./review-invitation-api";

vi.mock("./review-invitation-api", () => ({
  createReviewInvitation: vi.fn(),
  revokeReviewInvitation: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const runId = "33333333-3333-4333-8333-333333333333";

function value(input: HTMLInputElement, text: string) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, text);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

it("retries the same invitation safely, gives edited invitations a new identity, and uses a calendar expiry", async () => {
  const send = vi.mocked(createReviewInvitation);
  send.mockRejectedValue(
    Object.assign(new Error("Temporary delivery outage"), { retryable: true }),
  );
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () =>
      root.render(<ReviewInvitationPanel initialRunId={runId} />),
    );
    const email =
      container.querySelector<HTMLInputElement>("#invitation-email")!;
    const sendButton = () =>
      [...container.querySelectorAll("button")].find((button) =>
        button.textContent?.includes("Send invitation"),
      )!;
    await act(async () => value(email, "reviewer@example.test"));
    await act(async () => {
      sendButton().click();
      sendButton().click();
    });
    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => sendButton().click());
    expect(send.mock.calls[1]![0].idempotencyKey).toBe(
      send.mock.calls[0]![0].idempotencyKey,
    );
    await act(async () => value(email, "second@example.test"));
    await act(async () => sendButton().click());
    expect(send.mock.calls[2]![0].idempotencyKey).not.toBe(
      send.mock.calls[0]![0].idempotencyKey,
    );
    expect(send.mock.calls[2]![0].invitedEmail).toBe("second@example.test");
    expect(send.mock.calls[2]![0].expiresAtEpoch).toBeGreaterThan(
      Date.now() / 1000,
    );
    expect(
      container.querySelector<HTMLInputElement>("#invitation-expiry")!.type,
    ).toBe("datetime-local");
    expect(container.querySelector("details")!.open).toBe(false);
    send.mockImplementation(async (intent) => ({
      id: "11111111-1111-4111-8111-111111111111",
      tenant_id: "22222222-2222-4222-8222-222222222222",
      run_id: intent.runId,
      invited_email: intent.invitedEmail,
      allowed_lenses: [...intent.allowedLenses],
      created_at_epoch: Math.floor(Date.now() / 1000),
      expires_at_epoch: intent.expiresAtEpoch,
      state: "pending",
      assignment_id: null,
      created_by_person_id: "55555555-5555-4555-8555-555555555555",
      schema: "ac.sales-xray.review-invitation/1",
    }));
    await act(async () => sendButton().click());
    await act(async () => sendButton().click());
    expect(send.mock.calls[4]![0].idempotencyKey).not.toBe(
      send.mock.calls[3]![0].idempotencyKey,
    );
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.clearAllMocks();
  }
});

it("preserves a draft when the selected analysis arrives after initial loading", async () => {
  const container = document.createElement("div");
  const root = createRoot(container);
  try {
    await act(async () => root.render(<ReviewInvitationPanel />));
    await act(async () =>
      value(
        container.querySelector<HTMLInputElement>("#invitation-email")!,
        "keep@example.test",
      ),
    );
    await act(async () =>
      root.render(<ReviewInvitationPanel initialRunId={runId} />),
    );
    expect(
      container.querySelector<HTMLInputElement>("#invitation-email")!.value,
    ).toBe("keep@example.test");
    expect(
      container.querySelector<HTMLInputElement>("#invitation-run-id")!.value,
    ).toBe(runId);
  } finally {
    await act(async () => root.unmount());
  }
});
