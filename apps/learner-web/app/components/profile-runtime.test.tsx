// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type LearnerApi,
  type MeResponse,
  type OnboardingResponse,
  type ProfileAvatarResponse,
} from "../lib/learner-api";
import type { AvatarCropDialogProps } from "./avatar-crop-dialog";
import { ProfileRuntime } from "./profile-runtime";

const dialogFixture = vi.hoisted(() => ({
  latest: null as AvatarCropDialogProps | null,
}));

// Explicit dialog-host seam: browser QA separately exercises the real crop dialog.
// This fixture represents an adapter-confirmed ready avatar, never a live upload.
vi.mock("./avatar-crop-dialog", () => ({
  AvatarCropDialog: (props: AvatarCropDialogProps) => {
    dialogFixture.latest = props;
    return (
      <div role="dialog" aria-label="Synthetic avatar adapter">
        <button type="button" onClick={props.onClose}>
          Cancel fixture
        </button>
        <button
          type="button"
          onClick={() =>
            props.onSuccess?.({
              assetId: "asset-fixture",
              versionId: "version-fixture",
              deliveryUrl: "https://avatar.example.invalid/confirmed.png",
              alt: "Confirmed fixture photo",
              revision: "2",
            })
          }
        >
          Confirm fixture avatar
        </button>
      </div>
    );
  },
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const me: MeResponse = {
  person_id: "profile-fixture",
  display_name: "Profile learner",
  email: "profile@example.invalid",
  email_verified_at: "2026-09-07T00:00:00Z",
  selected_tenant_id: "profile-tenant",
  membership_role: "learner",
  permissions: [],
};
const onboarding: OnboardingResponse = {
  person_id: me.person_id,
  experience_context: "sales",
  learning_goal: "More thoughtful conversations",
  practice_situation: "Discovery calls",
  weekly_minutes: 30,
  status: "completed",
  current_step: 4,
  revision: 1,
  updated_at: "2026-09-07T00:00:00Z",
  next_action_href: "/home",
  next_action_reason: "complete",
};

let root: Root;
let container: HTMLDivElement;
let api: LearnerApi;

beforeEach(() => {
  window.history.replaceState(null, "", "/profile");
  window.localStorage.clear();
  dialogFixture.latest = null;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  api = {
    me: vi.fn(async () => me),
    onboarding: vi.fn(async () => onboarding),
    profileAvatar: vi.fn(async () => ({ avatar: null })),
    logout: vi.fn(async () => undefined),
  } as unknown as LearnerApi;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function mount(currentApi = api) {
  await act(async () => root.render(<ProfileRuntime api={currentApi} />));
}

function button(label: string) {
  const match = Array.from(container.querySelectorAll("button")).find(
    (control) => control.textContent?.trim() === label,
  );
  expect(match, `Button ${label}`).toBeDefined();
  return match!;
}

async function click(label: string) {
  await act(async () => button(label).click());
}

function readyAvatar(url: string): ProfileAvatarResponse {
  return {
    avatar: {
      asset_id: "asset-fixture",
      version_id: "version-fixture",
      version_number: 1,
      state: "ready",
      delivery_url: url,
      content_type: "image/png",
      size_px: 256,
      avatar_crop: null,
      supersedes_version_id: null,
      updated_at: "2026-09-07T00:00:00Z",
    },
    pending: null,
  };
}

describe("mounted profile", () => {
  it("shows source-backed identity and learning focus without invented achievements", async () => {
    await mount();
    expect(container.querySelector("h1")?.textContent).toBe("Your profile");
    expect(container.querySelector("#identity-card-title")?.textContent).toBe(
      me.display_name,
    );
    expect(container.textContent?.match(/Email verified/g)).toHaveLength(1);
    expect(container.textContent).not.toMatch(
      /Active Learner|Verification Status|streak|XP|server-backed|first-slice/,
    );
    expect(container.textContent).toContain(onboarding.learning_goal);
    expect(container.textContent).toContain("30 minutes / week");
    expect(
      container.querySelector('a[href="/onboarding?return=profile"]')
        ?.textContent,
    ).toContain("Edit learning setup");
    expect(
      container
        .querySelector('nav[aria-label="Profile shortcuts"] a')
        ?.getAttribute("href"),
    ).toBe("/learning");
  });

  it("does not mark an unverified email as verified", async () => {
    api.me = vi.fn(async () => ({ ...me, email_verified_at: "" }));
    await mount();
    expect(container.textContent).toContain("Email verification pending");
    expect(container.textContent).not.toContain("Email verified");
  });

  it("does not request secondary profile data without membership", async () => {
    api.me = vi.fn(async () => ({ ...me, membership_role: null }));
    await mount();
    expect(api.onboarding).not.toHaveBeenCalled();
    expect(api.profileAvatar).not.toHaveBeenCalled();
    expect(container.querySelector("#identity-card-title")).toBeNull();
    expect(
      container.querySelector('a[href="/onboarding?return=profile"]'),
    ).toBeNull();
  });

  it("keeps identity when secondary reads fail, and retries photo without discarding the profile", async () => {
    api.onboarding = vi.fn(async () => {
      throw new ApiError(503, "Synthetic unavailable");
    });
    api.profileAvatar = vi.fn(async () => {
      throw new ApiError(503, "Synthetic unavailable");
    });
    await mount();
    const identity = container.querySelector("#identity-card-title");
    expect(identity?.textContent).toBe(me.display_name);
    expect(button("Retry photo")).toBeDefined();
    api.profileAvatar = vi.fn(async () => ({ avatar: null, pending: null }));
    await click("Retry photo");
    expect(api.me).toHaveBeenCalledTimes(1);
    expect(container.querySelector("#identity-card-title")).toBe(identity);
    expect(container.textContent).not.toContain("Your photo couldn’t load");
    api.onboarding = vi.fn(async () => onboarding);
    await click("Retry learning setup");
    expect(container.textContent).toContain(onboarding.learning_goal);
  });

  it("does not fabricate missing goals or weekly commitment", async () => {
    api.onboarding = vi.fn(async () => ({
      ...onboarding,
      learning_goal: null,
      weekly_minutes: null,
      practice_situation: null,
    }));
    await mount();
    expect(container.textContent).toContain("Choose a goal");
    expect(container.textContent).toContain("Not set");
    expect(container.textContent).not.toContain("30 minutes");
  });

  it("ignores an obsolete identity response after the API context changes", async () => {
    let resolveOld!: (value: MeResponse) => void;
    let oldSignal: AbortSignal | undefined;
    api.me = vi.fn((options) => {
      oldSignal = options?.signal;
      return new Promise<MeResponse>((resolve) => {
        resolveOld = resolve;
      });
    });
    await mount();
    const nextApi = {
      ...api,
      me: vi.fn(async () => ({
        ...me,
        person_id: "next-person",
        display_name: "Next learner",
      })),
    } as LearnerApi;
    await mount(nextApi);
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolveOld(me));
    expect(container.querySelector("#identity-card-title")?.textContent).toBe(
      "Next learner",
    );
  });

  it("preserves the current photo until adapter confirmation and publishes one host success status", async () => {
    api.profileAvatar = vi.fn(async () =>
      readyAvatar("https://avatar.example.invalid/current.png"),
    );
    await mount();
    const current = container.querySelector<HTMLImageElement>("section img")!;
    await click("Change photo");
    expect(current.src).toContain("/current.png");
    expect(container.textContent).not.toContain("Profile photo updated.");
    await click("Cancel fixture");
    expect(current.src).toContain("/current.png");
    const publish = vi.spyOn(window, "dispatchEvent");
    await click("Change photo");
    await click("Confirm fixture avatar");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(
      container.querySelector<HTMLImageElement>("section img")?.src,
    ).toContain("/confirmed.png");
    const status = container.querySelector(
      '[role="status"][aria-live="polite"][aria-atomic="true"]',
    );
    expect(status?.textContent).toContain("Profile photo updated.");
    expect(
      publish.mock.calls.filter(
        ([event]) => event.type === "ac-profile-avatar-updated",
      ),
    ).toHaveLength(1);
  });

  it("refreshes an expired photo without recreating the active upload adapter", async () => {
    api.profileAvatar = vi
      .fn()
      .mockResolvedValueOnce(
        readyAvatar("https://avatar.example.invalid/expired.png"),
      )
      .mockResolvedValueOnce(
        readyAvatar("https://avatar.example.invalid/fresh.png"),
      );
    await mount();
    await click("Change photo");
    const adapter = dialogFixture.latest!.adapter;
    await act(async () =>
      container
        .querySelector<HTMLImageElement>("section img")!
        .dispatchEvent(new Event("error")),
    );
    expect(
      container.querySelector<HTMLImageElement>("section img")?.src,
    ).toContain("/fresh.png");
    expect(dialogFixture.latest?.adapter).toBe(adapter);
  });

  it("does not apply a late avatar refresh from a previous identity context", async () => {
    let finishRefresh!: (value: ProfileAvatarResponse) => void;
    api.profileAvatar = vi
      .fn()
      .mockResolvedValueOnce(
        readyAvatar("https://avatar.example.invalid/old.png"),
      )
      .mockImplementationOnce(
        () =>
          new Promise<ProfileAvatarResponse>((resolve) => {
            finishRefresh = resolve;
          }),
      );
    await mount();
    await act(async () =>
      container
        .querySelector<HTMLImageElement>("section img")!
        .dispatchEvent(new Event("error")),
    );
    const nextApi = {
      ...api,
      me: vi.fn(async () => ({
        ...me,
        person_id: "next-person",
        display_name: "Next learner",
      })),
      profileAvatar: vi.fn(async () => ({ avatar: null })),
    } as unknown as LearnerApi;
    await mount(nextApi);
    await act(async () =>
      finishRefresh(readyAvatar("https://avatar.example.invalid/stale.png")),
    );
    expect(container.querySelector("#identity-card-title")?.textContent).toBe(
      "Next learner",
    );
    expect(container.querySelector("section img")).toBeNull();
  });
});
