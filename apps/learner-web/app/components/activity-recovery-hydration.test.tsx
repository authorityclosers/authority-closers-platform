// @vitest-environment happy-dom

import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ActivityResponse, LearnerApi } from "../lib/learner-api";
import {
  activityServerFingerprint,
  readActivityLocalDraftWithLock,
  writeActivityLocalDraftWithLock,
  type ActivityDraftScope,
  type OnboardingRecoveryLockManager,
} from "../lib/local-drafts";
import { ConnectedActivityWorkspace } from "./learner-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const scope: ActivityDraftScope = {
  kind: "activity",
  tenantId: "recovery-tenant",
  personId: "recovery-person",
  enrollmentId: "recovery-enrollment",
  activityId: "86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
};
const serverResponse = "Synthetic saved response B";
const localResponse = "Synthetic unsaved response C";
const activity: ActivityResponse = {
  id: scope.activityId,
  enrollment_id: scope.enrollmentId,
  module_id: "recovery-module",
  program_id: "recovery-program",
  program_version_id: "recovery-version",
  position: 1,
  kind: "REFLECTION",
  title: "Reflect on the shift",
  prompt: "Write your reflection.",
  state: "available",
  revision: 3,
  required: true,
  allowed_actions: ["save_draft"],
  draft_revision: 2,
  draft_payload: { response: serverResponse },
  explanation: {
    activity_id: scope.activityId,
    state: "available",
    required: true,
    reason: "fixture_only",
    missing_activity_ids: [],
    missing_module_ids: [],
  },
};

describe("mounted activity recovery hydration", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalLocks: PropertyDescriptor | undefined;
  let refuseNextRead: boolean;
  let lockHeld: boolean;
  let api: LearnerApi;

  beforeEach(async () => {
    window.localStorage.clear();
    originalLocks = Object.getOwnPropertyDescriptor(navigator, "locks");
    refuseNextRead = false;
    lockHeld = false;
    // Preserve the browser's exclusive, ifAvailable semantics: overlapping
    // requests receive no lock while the first async callback still owns it.
    const locks: OnboardingRecoveryLockManager = {
      async request(_name, _options, callback) {
        if (refuseNextRead) {
          refuseNextRead = false;
          return callback(null);
        }
        if (lockHeld) return callback(null);
        lockHeld = true;
        try {
          return await callback({});
        } finally {
          lockHeld = false;
        }
      },
    };
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: locks,
    });
    expect(
      await writeActivityLocalDraftWithLock(window.localStorage, {
        scope,
        response: localResponse,
        baseRevision: activity.draft_revision,
        serverFingerprint: activityServerFingerprint(serverResponse),
      }),
    ).toEqual({ ok: true });
    api = {
      saveDraft: vi.fn(),
      submitEvidence: vi.fn(),
    } as unknown as LearnerApi;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.localStorage.clear();
    if (originalLocks) Object.defineProperty(navigator, "locks", originalLocks);
    else Reflect.deleteProperty(navigator, "locks");
  });

  async function mount(strict = false, current = activity) {
    const workspace = (
      <ConnectedActivityWorkspace
        activity={current}
        tenantId={scope.tenantId}
        personId={scope.personId}
        api={api}
      />
    );
    await act(async () =>
      root.render(strict ? <StrictMode>{workspace}</StrictMode> : workspace),
    );
  }

  async function expectRecoveryPreserved() {
    const recovered = await readActivityLocalDraftWithLock(
      window.localStorage,
      scope,
    );
    expect(recovered.status).toBe("ready");
    if (recovered.status === "ready")
      expect(recovered.envelope.draft.response).toBe(localResponse);
    expect(api.saveDraft).not.toHaveBeenCalled();
    expect(api.submitEvidence).not.toHaveBeenCalled();
  }

  it.each([false, true])(
    "restores the same-account response with StrictMode=%s",
    async (strict) => {
      await mount(strict);
      expect(
        container.querySelector<HTMLTextAreaElement>("textarea")?.value,
      ).toBe(localResponse);
      expect(
        container.querySelector(".activity-response-form__save-state")
          ?.textContent,
      ).toContain("Local draft restored");
      await expectRecoveryPreserved();
    },
  );

  it("preserves an unread recovery copy when its initial lock is unavailable", async () => {
    refuseNextRead = true;
    await mount();
    expect(
      container.querySelector<HTMLTextAreaElement>("textarea")?.value,
    ).toBe(serverResponse);
    await expectRecoveryPreserved();
    const retry = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Retry local recovery",
    );
    expect(retry).toBeDefined();
    await act(async () => retry!.click());
    expect(
      container.querySelector<HTMLTextAreaElement>("textarea")?.value,
    ).toBe(localResponse);
    await expectRecoveryPreserved();
  });

  it("keeps stale recovery separate from a newer canonical server draft", async () => {
    await mount(false, {
      ...activity,
      draft_revision: 3,
      draft_payload: { response: "Synthetic newer server response" },
    });
    expect(container.textContent).toContain(
      "A newer activity draft exists on the server.",
    );
    expect(container.textContent).toContain(localResponse);
    expect(container.textContent).toContain("Synthetic newer server response");
    await expectRecoveryPreserved();
  });

  it("keeps the learner's current edit when retrying an unavailable recovery read", async () => {
    refuseNextRead = true;
    await mount();
    const currentResponse = "Synthetic new response typed before retry";
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )!.set!.call(textarea, currentResponse);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(
      container.querySelector(".activity-response-form__save-state")
        ?.textContent,
    ).toContain("Not saved on this device");
    const retry = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Retry local recovery",
    )!;
    await act(async () => retry.click());
    expect(textarea.value).toBe(currentResponse);
    const recovered = await readActivityLocalDraftWithLock(
      window.localStorage,
      scope,
    );
    expect(recovered.status).toBe("ready");
    if (recovered.status === "ready")
      expect(recovered.envelope.draft.response).toBe(currentResponse);
    expect(api.saveDraft).not.toHaveBeenCalled();
    expect(api.submitEvidence).not.toHaveBeenCalled();
  });
});
