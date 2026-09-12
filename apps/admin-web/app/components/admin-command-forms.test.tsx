// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as sessionApi from "@ac/operations-web/api";
import { AdminSessionProvider } from "../lib/admin-session";
import {
  CorrectionForm,
  HeldJobRetryForm,
  ManualGrantForm,
  PublishVersionForm,
  ReconciliationForm,
} from "./admin-forms";

const commands = vi.hoisted(() => ({
  appendCorrection: vi.fn(),
  grantEnrollment: vi.fn(),
  retryJob: vi.fn(),
  publishProgramVersion: vi.fn(),
  reconcileRecovery: vi.fn(),
}));
vi.mock("../lib/admin-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/admin-api")>()),
  ...commands,
  newIdempotencyKey: () => "55555555-5555-4555-8555-555555555555",
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const targetId = "11111111-1111-4111-8111-111111111111";
const versionId = "22222222-2222-4222-8222-222222222222";
const cases = [
  {
    name: "correction",
    permission: "learning_correct",
    command: commands.appendCorrection,
    view: (resolved = true) => (
      <CorrectionForm
        target={
          resolved ? { submissionId: targetId, ifMatch: '"rev-1"' } : undefined
        }
      />
    ),
    expected: {
      submissionId: targetId,
      ifMatch: '"rev-1"',
      decision: "approved",
    },
  },
  {
    name: "enrollment grant",
    permission: "enrollment_grant",
    command: commands.grantEnrollment,
    view: (resolved = true) => (
      <ManualGrantForm
        target={
          resolved
            ? { personId: targetId, programVersionId: versionId }
            : undefined
        }
      />
    ),
    expected: { personId: targetId, programVersionId: versionId },
  },
  {
    name: "job retry",
    permission: "job_retry",
    command: commands.retryJob,
    view: (resolved = true) => (
      <HeldJobRetryForm target={resolved ? { jobId: targetId } : undefined} />
    ),
    expected: { jobId: targetId },
  },
  {
    name: "publication",
    permission: "catalog_publish",
    command: commands.publishProgramVersion,
    view: (resolved = true) => (
      <PublishVersionForm
        target={
          resolved
            ? { programVersionId: versionId, ifMatch: '"rev-1"' }
            : undefined
        }
      />
    ),
    expected: { programVersionId: versionId, ifMatch: '"rev-1"' },
  },
  {
    name: "reconciliation",
    permission: "recovery_reconcile",
    command: commands.reconcileRecovery,
    view: (resolved = true) => (
      <ReconciliationForm
        target={
          resolved ? { jobIds: [targetId], outboxEventIds: [] } : undefined
        }
      />
    ),
    expected: { jobIds: [targetId], outboxEventIds: [] },
  },
];
const account: sessionApi.AdminSession = {
  personId: targetId,
  sessionId: versionId,
  tenantId: "33333333-3333-4333-8333-333333333333",
  displayName: "Synthetic operator",
  email: "operator@example.test",
  emailVerifiedAt: "2026-09-12T00:00:00Z",
  membershipRole: "admin",
  permissions: ["admin_surface", ...cases.map((item) => item.permission)],
  studioCapabilities: [],
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.spyOn(sessionApi, "loadAdminSession").mockResolvedValue(account);
  for (const command of Object.values(commands))
    command.mockReset().mockResolvedValue({});
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function render(view: ReactNode) {
  await act(async () =>
    root.render(<AdminSessionProvider>{view}</AdminSessionProvider>),
  );
}
function fields() {
  return {
    form: host.querySelector<HTMLFormElement>("form")!,
    fieldset: host.querySelector<HTMLFieldSetElement>("fieldset")!,
    reason: host.querySelector<HTMLTextAreaElement>("textarea")!,
    submit: host.querySelector<HTMLButtonElement>('button[type="submit"]')!,
  };
}
async function enterReason(value: string) {
  const reason = fields().reason;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(reason, value);
    reason.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function submit() {
  return fields().form.dispatchEvent(
    new Event("submit", { bubbles: true, cancelable: true }),
  );
}

describe.each(cases)("$name command preparation", (item) => {
  it("allows entering a reason only after authorization and target resolution, then sends the exact command", async () => {
    await render(item.view());
    expect(fields().fieldset.disabled).toBe(false);
    expect(fields().submit.disabled).toBe(true);
    expect(fields().form.dataset.previewInert).toBe("false");
    const newline = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    fields().reason.dispatchEvent(newline);
    expect(newline.defaultPrevented).toBe(false);
    await enterReason(" \n ");
    await act(async () => {
      expect(submit()).toBe(false);
    });
    expect(item.command).not.toHaveBeenCalled();
    expect(fields().submit.disabled).toBe(true);
    await enterReason("  Reviewed supporting evidence.\nConfirmed target.  ");
    expect(fields().submit.disabled).toBe(false);
    await act(async () => {
      expect(submit()).toBe(false);
    });
    expect(item.command).toHaveBeenCalledExactlyOnceWith({
      ...item.expected,
      reason: "Reviewed supporting evidence.\nConfirmed target.",
      idempotencyKey: "55555555-5555-4555-8555-555555555555",
    });
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      "accepted by the canonical API",
    );
  });

  it.each([
    "unresolved",
    "missing permission",
    "missing admin surface",
    "session loading",
  ])("keeps fields and forged submits inert when %s", async (boundary) => {
    if (boundary === "session loading") {
      vi.mocked(sessionApi.loadAdminSession).mockReturnValue(
        new Promise(() => {}),
      );
    } else if (boundary !== "unresolved") {
      vi.mocked(sessionApi.loadAdminSession).mockResolvedValue({
        ...account,
        permissions:
          boundary === "missing permission"
            ? ["admin_surface"]
            : [item.permission],
      });
    }
    await render(item.view(boundary !== "unresolved"));
    expect(fields().fieldset.disabled).toBe(true);
    expect(fields().submit.disabled).toBe(true);
    expect(fields().form.dataset.previewInert).toBe("true");
    await enterReason("A forged input event must not authorize a command.");
    await act(async () => {
      expect(submit()).toBe(false);
    });
    expect(item.command).not.toHaveBeenCalled();
  });
});

it("ignores repeated submits while pending and preserves the reason after a rejected command", async () => {
  let reject!: (error: Error) => void;
  commands.grantEnrollment.mockReturnValueOnce(
    new Promise((_resolve, no) => {
      reject = no;
    }),
  );
  await render(cases[1].view());
  await enterReason("Reviewed access support request.");
  await act(async () => {
    submit();
    submit();
  });
  expect(commands.grantEnrollment).toHaveBeenCalledOnce();
  expect(fields().fieldset.disabled).toBe(true);
  expect(fields().submit.disabled).toBe(true);
  expect(host.textContent).toContain("Working…");
  await act(async () =>
    reject(new Error("The reviewed target is no longer eligible.")),
  );
  expect(fields().reason.value).toBe("Reviewed access support request.");
  expect(fields().fieldset.disabled).toBe(false);
  expect(fields().submit.disabled).toBe(false);
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "no longer eligible",
  );
  await act(async () => {
    submit();
  });
  expect(commands.grantEnrollment).toHaveBeenCalledTimes(2);
});
