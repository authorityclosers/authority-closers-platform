import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ACCOUNT_PROFILE_PHOTO_PATH } from "./account-profile-client";
import { readCharacters, resetCharactersForTests } from "./people/characters";
import { AccountAvatarImage } from "./speaker-avatar";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner bug #50 (29 Oct 2026): your own face in the app's frame is the same
// picture everyone else sees for you, never bare initials when you have one.

let root: Root;
let host: HTMLDivElement;
const CHARACTERS = [
  { key: "owl", label: "Owl", url: "/v1/people/characters/owl.svg" },
  { key: "fox", label: "Fox", url: "/v1/people/characters/fox.svg" },
];

beforeEach(async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ characters: CHARACTERS })),
  );
  resetCharactersForTests();
  await readCharacters();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  resetCharactersForTests();
});

const face = (photoUrl: string | null) =>
  act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          status: "ready",
          authenticated: true,
          // 0x00000001 % 2 characters: the second, as the server picks it.
          context: {
            personId: "00000001-0000-4000-8000-000000000000",
            sessionId: "s",
            tenantId: "t",
          },
          retry: () => {},
        }}
      >
        <AccountAvatarImage photoUrl={photoUrl}>VE</AccountAvatarImage>
      </WorkspaceAccessProvider>,
    ),
  );

it("shows your own photo, or the character you chose, when there is one", async () => {
  await face(ACCOUNT_PROFILE_PHOTO_PATH);
  expect(host.querySelector("img")?.getAttribute("src")).toBe(
    ACCOUNT_PROFILE_PHOTO_PATH,
  );
});

it("shows your default character instead of initials when you have no photo", async () => {
  await face(null);
  expect(host.querySelector("img")?.getAttribute("src")).toBe(
    "/v1/people/characters/fox.svg",
  );
  expect(host.textContent).toBe("");
});

it("keeps the initials when the character can't load", async () => {
  await face(null);
  await act(async () => {
    host.querySelector("img")!.dispatchEvent(new Event("error"));
  });
  expect(host.querySelector("img")).toBeNull();
  expect(host.textContent).toBe("VE");
});
