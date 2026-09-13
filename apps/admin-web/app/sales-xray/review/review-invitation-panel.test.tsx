// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewInvitationPanel } from "./review-invitation-panel";

const run = "30000000-0000-4000-8000-000000000003";
const invitation = "90000000-0000-4000-8000-000000000009";
let root: Root;
let container: HTMLDivElement;
let fetcher: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(async () => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<ReviewInvitationPanel />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function fill(label: string, value: string) {
  const input = [...container.querySelectorAll("label")]
    .find((item) => item.textContent?.includes(label))!
    .querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === text,
  )!;
  expect(button).toBeDefined();
  await act(async () => button.click());
}

function receipt(
  state: "pending" | "revoked",
  email = "Reviewer@example.test",
) {
  return {
    id: invitation,
    run_id: run,
    invited_email: email,
    allowed_lenses: ["sales", "technical", "ux"],
    created_at_epoch: 100,
    expires_at_epoch: Math.floor(Date.now() / 1000) + 3600,
    state,
    assignment_id: null,
  };
}

describe("review invitation controls", () => {
  it("reuses an unchanged failed intent key and gives edited intent a fresh key", async () => {
    fetcher.mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "Temporarily unavailable" }), {
          status: 503,
        }),
    );
    await fill("Exact run ID", run);
    await fill("Invited email", "Reviewer@example.test");
    await fill("Expiry", String(Math.floor(Date.now() / 1000) + 3600));
    await click("Queue invitation");
    await click("Retry invitation");
    const keys = () =>
      fetcher.mock.calls.map(([, init]) =>
        new Headers(init?.headers).get("Idempotency-Key"),
      );
    expect(keys()[0]).toBeTruthy();
    expect(keys()[1]).toBe(keys()[0]);
    await fill("Invited email", "another@example.test");
    await click("Retry invitation");
    expect(keys()[2]).not.toBe(keys()[0]);
    expect(
      JSON.parse(String(fetcher.mock.calls[2]![1]?.body)).invited_email,
    ).toBe("another@example.test");
  });

  it("shows invalid email feedback without an unhandled synchronous error or request", async () => {
    await fill("Exact run ID", run);
    await fill("Invited email", "broken@@example.test");
    await click("Queue invitation");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Check the run ID, email address",
    );
    expect(fetcher).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Queue invitation");
  });

  it("reports server-confirmed revocation even for an invitation from an earlier visit", async () => {
    fetcher.mockResolvedValue(
      new Response(JSON.stringify(receipt("revoked")), { status: 200 }),
    );
    await fill("Revoke a known invitation", invitation);
    await click("Revoke known invitation");
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      `Invitation revoked. ${invitation}`,
    );
    expect(fetcher.mock.calls[0]![0]).toBe(
      `/v1/admin/conversation/review-invitations/${invitation}/revoke`,
    );
  });

  it("suppresses simultaneous clicks and renders only the confirmed queue receipt", async () => {
    let finish!: (value: Response) => void;
    fetcher.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const saved = receipt("pending");
    await fill("Exact run ID", run);
    await fill("Invited email", saved.invited_email);
    await fill("Expiry", String(saved.expires_at_epoch));
    const button = [...container.querySelectorAll("button")].find(
      (item) => item.textContent === "Queue invitation",
    )!;
    await act(async () => {
      button.click();
      button.click();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[role="status"]')).toBeNull();
    await act(async () => {
      finish(new Response(JSON.stringify(saved), { status: 201 }));
    });
    expect(container.textContent).toContain(
      "Invitation queued for email delivery.",
    );
    expect(container.querySelectorAll("article")).toHaveLength(1);
  });
});
