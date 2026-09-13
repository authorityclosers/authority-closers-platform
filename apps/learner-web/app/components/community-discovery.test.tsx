// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LearnerApi } from "../lib/learner-api";
import { CommunityDiscovery } from "./community-discovery";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const discovery = {
  username: "learner_7",
  discoverable: false,
  public_display_name: "Chosen display",
  avatar_asset_id: null,
  revision: 1,
};
const profile = {
  username: "other_learner",
  display_name: "Chosen peer",
  avatar_asset_id: null,
  practice_xp_total: 30,
  connection_state: null as
    | "pending"
    | "accepted"
    | "declined"
    | "removed"
    | null,
  connection_incoming: null as boolean | null,
};

let root: Root;
let container: HTMLDivElement;
let api: LearnerApi;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  api = {
    communityDiscovery: vi.fn(async () => discovery),
    setCommunityDiscovery: vi.fn(async (discoverable: boolean) => ({
      ...discovery,
      discoverable,
      revision: 2,
    })),
    communitySearch: vi.fn(async () => ({ items: [profile] })),
    communityPublicProfile: vi.fn(async () => profile),
    requestCommunityConnection: vi.fn(async () => ({
      username: profile.username,
      state: "pending",
      incoming: false,
    })),
    respondCommunityConnection: vi.fn(
      async (_username: string, action: "accept" | "decline") => ({
        username: profile.username,
        state: action === "accept" ? "accepted" : "declined",
        incoming: true,
      }),
    ),
    removeCommunityConnection: vi.fn(async () => ({
      username: profile.username,
      state: "removed",
      incoming: false,
    })),
    blockCommunityLearner: vi.fn(async () => ({
      username: profile.username,
      blocked: true as const,
    })),
    reportCommunityLearner: vi.fn(async () => ({
      username: profile.username,
      reported: true as const,
    })),
  } as unknown as LearnerApi;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function mount() {
  await act(async () => root.render(<CommunityDiscovery api={api} />));
}

async function click(label: string) {
  const button = Array.from(container.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === label,
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    Object.getPrototypeOf(input),
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new InputEvent("input", { bubbles: true, data: value }));
}

describe("community discovery", () => {
  it("keeps the profile private until explicit opt-in", async () => {
    await mount();
    expect(container.textContent).toContain("Private by default");
    expect(container.textContent).toContain("Enable discovery");
    await click("Enable discovery");
    expect(api.setCommunityDiscovery).toHaveBeenCalledWith(
      true,
      "Chosen display",
      null,
      1,
    );
    expect(container.textContent).toContain("You can now be found by username");
  });

  it("views the bounded projection and supports connection request", async () => {
    await mount();
    await act(async () => {
      const input = container.querySelector("input") as HTMLInputElement;
      setInputValue(input, "other_learner");
    });
    await click("Search");
    expect(api.communitySearch).toHaveBeenCalledWith("other_learner", 10);
    await click("View profile");
    expect(api.communityPublicProfile).toHaveBeenCalledWith("other_learner");
    expect(container.textContent).toContain("Chosen peer");
    await click("Connect");
    expect(api.requestCommunityConnection).toHaveBeenCalledWith(
      "other_learner",
    );
    expect(container.textContent).toContain("Connection request sent");
    expect(container.textContent).not.toContain("other@example");
  });

  it("shows recipient controls for an incoming request", async () => {
    api.communitySearch = vi.fn(async () => ({
      items: [
        { ...profile, connection_state: "pending", connection_incoming: true },
      ],
    })) as LearnerApi["communitySearch"];
    await mount();
    await act(async () => {
      const input = container.querySelector("input") as HTMLInputElement;
      setInputValue(input, "other_learner");
    });
    await click("Search");
    await click("Accept");
    expect(api.respondCommunityConnection).toHaveBeenCalledWith(
      "other_learner",
      "accept",
    );
    expect(container.textContent).toContain("now connected");
  });
});
