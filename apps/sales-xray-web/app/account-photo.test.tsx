import { readFileSync, readdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ACCOUNT_PROFILE_PATH,
  ACCOUNT_PROFILE_PHOTO_PATH,
} from "./account-profile-client";
import { AccountSettings } from "./account-settings";
import { ProfileMenu } from "./profile-menu";
import { SettingsMenu } from "./shell/settings-menu";
import {
  invalidateShellProfile,
  PROFILE_UPDATED_EVENT,
} from "./shell/profile-store";
import { SpeakerAvatar } from "./speaker-avatar";
import { WorkspaceAccessContext } from "./workspace-access";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("./notice-center", () => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
const profile = {
  name: "Morgan Lee",
  email: "morgan@example.test",
  phone_number_e164: null,
  phone_verified: false,
  profile_complete: false,
  revision: 1,
  photo_url: ACCOUNT_PROFILE_PHOTO_PATH,
};

beforeEach(() => {
  invalidateShellProfile();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  invalidateShellProfile();
  vi.unstubAllGlobals();
});

async function render(node: ReactNode, authenticated = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: authenticated ? "ready" : "unauthenticated",
          authenticated,
          context: authenticated
            ? {
                personId: "fictional-person",
                sessionId: "fictional-session",
                tenantId: "fictional-workspace",
              }
            : null,
          retry: () => {},
        }}
      >
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );
}

const surfaces = ["header", "rail", "account", "menu", "you"] as const;
type Surface = (typeof surfaces)[number];
function surfaceNode(
  surface: Surface,
  photoUrl: string | null = ACCOUNT_PROFILE_PHOTO_PATH,
) {
  return surface === "account" ? (
    <AccountSettings billing={{ status: "ready" }} />
  ) : surface === "menu" ? (
    <SettingsMenu
      open
      anchorRef={{ current: document.createElement("button") }}
      onClose={() => {}}
      name={profile.name}
      email={profile.email}
      photoUrl={photoUrl}
      allowance={null}
    />
  ) : surface === "you" ? (
    <SpeakerAvatar
      voice={0}
      profile={{ name: "Morgan Lee", role: "you", icon: null }}
    />
  ) : (
    <ProfileMenu authenticated accountHref="/account" variant={surface} />
  );
}

async function show(surface: Surface, photo_url: string | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      path === ACCOUNT_PROFILE_PATH
        ? Response.json({ ...profile, photo_url })
        : new Response(null, { status: 503 }),
    ),
  );
  await render(surfaceNode(surface, photo_url));
  if (surface === "header" || surface === "rail")
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
    );
  return surface === "account"
    ? [
        host.querySelector("aside header > span")!,
        host.querySelector('#account-pane-profile span[aria-hidden="true"]')!,
      ]
    : surface === "menu"
      ? [
          document.querySelector(
            '[aria-label="Account menu"] [aria-hidden="true"]',
          )!,
        ]
      : surface === "you"
        ? [host.querySelector('[data-you="true"]')!]
        : [
            ...host.querySelectorAll(
              'button[aria-expanded] > span[aria-hidden="true"], [aria-label="Profile actions"] > div > span[aria-hidden="true"]',
            ),
          ];
}

it.each(surfaces)(
  "shows the first-party photo in %s and falls back on image error",
  async (surface) => {
    const avatars = await show(surface, ACCOUNT_PROFILE_PHOTO_PATH);
    expect(avatars).toHaveLength(
      surface === "header" || surface === "rail" || surface === "account"
        ? 2
        : 1,
    );
    for (const avatar of avatars) {
      const image = avatar.querySelector("img")!;
      expect(image.getAttribute("src")).toBe(ACCOUNT_PROFILE_PHOTO_PATH);
      expect(image.getAttribute("alt")).toBe("");
      expect(image.getAttribute("referrerpolicy")).toBe("no-referrer");
      expect(image.getAttribute("decoding")).toBe("async");
      expect(avatar.textContent).toBe("");
      await act(async () => image.dispatchEvent(new Event("error")));
      expect(avatar.querySelector("img")).toBeNull();
      expect(avatar.textContent).toBe("ML");
    }
  },
);

it.each(surfaces)(
  "keeps initials in %s when the photo is missing or foreign",
  async (surface) => {
    for (const url of [null, "https://example.test/photo"]) {
      const avatars = await show(surface, url);
      expect(host.querySelector("img")).toBeNull();
      for (const avatar of avatars) expect(avatar.textContent).toBe("ML");
      await act(async () => root.unmount());
      root = createRoot(host);
      invalidateShellProfile();
    }
  },
);

it("reads the profile only for an authenticated speaker already marked as you", async () => {
  const fetcher = vi.fn(async () => Response.json(profile));
  vi.stubGlobal("fetch", fetcher);
  const you = surfaceNode("you");
  await render(you, false);
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.textContent).toBe("ML");
  await render(
    <SpeakerAvatar
      voice={1}
      profile={{ name: "Alex Rivera", role: "prospect", icon: null }}
    />,
  );
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.textContent).toBe("2");
  await render(you);
  expect(host.querySelector("img")).not.toBeNull();
  expect(fetcher).toHaveBeenCalledOnce();
  await render(you, false);
  expect(host.querySelector("img")).toBeNull();
  expect(host.textContent).toBe("ML");
});

it("allows a new account's photo after the previous account's photo failed", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(
        Response.json({
          ...profile,
          name: "Alex Rivera",
          email: "alex@example.test",
        }),
      ),
  );
  await render(surfaceNode("header"));
  await act(async () =>
    host.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(host.querySelector("img")).toBeNull();
  invalidateShellProfile();
  await act(async () => window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT)));
  expect(host.querySelector("img")?.getAttribute("src")).toBe(
    ACCOUNT_PROFILE_PHOTO_PATH,
  );
});

it("resets the account pop-up photo fallback when the account changes", async () => {
  const [avatar] = await show("menu", ACCOUNT_PROFILE_PHOTO_PATH);
  await act(async () =>
    avatar.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(avatar.textContent).toBe("ML");
  await render(
    <SettingsMenu
      open
      anchorRef={{ current: document.createElement("button") }}
      onClose={() => {}}
      name="Alex Rivera"
      email="alex@example.test"
      photoUrl={ACCOUNT_PROFILE_PHOTO_PATH}
      allowance={null}
    />,
  );
  const image = document.querySelector('[aria-label="Account menu"] img');
  expect(image?.getAttribute("src")).toBe(ACCOUNT_PROFILE_PHOTO_PATH);
});

it("keeps provider image hosts out of the app source", () => {
  const app = dirname(fileURLToPath(import.meta.url));
  const forbiddenHost = ["google", "usercontent"].join("");
  const offenders = readdirSync(app, { recursive: true, withFileTypes: true })
    .filter(
      (entry) =>
        entry.isFile() &&
        /\.(?:[cm]?[jt]sx?|css|json|html|svg)$/.test(entry.name),
    )
    .filter((entry) =>
      readFileSync(`${entry.parentPath}/${entry.name}`, "utf8")
        .toLowerCase()
        .includes(forbiddenHost),
    )
    .map((entry) => `${entry.parentPath}/${entry.name}`);
  expect(offenders).toEqual([]);
});
