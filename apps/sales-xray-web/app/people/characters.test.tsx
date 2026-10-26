import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  CHARACTERS_PATH,
  characterFor,
  resetCharactersForTests,
  type Character,
} from "./characters";
import { PersonAvatar } from "./person-avatar";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Characters (owner #32, 26 Oct 2026): someone without a photo shows the
// character the server picks for their person id, never one chosen by name.
const KEYS = [
  "fox",
  "owl",
  "panda",
  "cat",
  "bear",
  "rabbit",
  "penguin",
  "koala",
];
const LIST: Character[] = KEYS.map((key) => ({
  key,
  label: key,
  url: `${CHARACTERS_PATH}/${key}?v=0123abcd`,
}));

it("picks the server's character: the id's first 8 hex digits modulo the count", () => {
  // As identity/characters.py: int(person_id.hex[:8], 16) % len(characters).
  expect(characterFor("0000000a-0000-4000-8000-000000000000", LIST)?.key).toBe(
    "panda",
  );
  expect(characterFor("ffffffff-0000-4000-8000-000000000000", LIST)?.key).toBe(
    "koala",
  );
  expect(characterFor("00000008-ffff-4fff-8fff-ffffffffffff", LIST)?.key).toBe(
    "fox",
  );
  expect(characterFor("0000000a-0000-4000-8000-000000000000", [])).toBeNull();
});

let root: Root;
let host: HTMLDivElement;
const fetched = vi.fn();

beforeEach(() => {
  resetCharactersForTests();
  fetched.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal("fetch", async (url: string) => {
    fetched(url);
    return Response.json({
      characters: [
        ...LIST,
        // Anything that isn't one of ours is left out.
        { key: "x", label: "x", url: "https://elsewhere.example/x.webp" },
      ],
    });
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const pictures = () =>
  [...host.querySelectorAll("img")].map((img) => img.getAttribute("src"));

it("shows a photo first, then the character, and reads the list once", async () => {
  await act(async () =>
    root.render(
      <>
        <PersonAvatar
          personId="0000000a-0000-4000-8000-000000000000"
          name="Asha Fictional"
          size={40}
        />
        <PersonAvatar
          personId="ffffffff-0000-4000-8000-000000000000"
          name="Dev Fictional"
          size={40}
        />
        <PersonAvatar
          personId="00000001-0000-4000-8000-000000000000"
          name="Meera Fictional"
          photoUrl="/v1/people/00000001-0000-4000-8000-000000000000/photo?v=1"
          size={40}
        />
      </>,
    ),
  );
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  expect(fetched).toHaveBeenCalledTimes(1);
  expect(fetched).toHaveBeenCalledWith(CHARACTERS_PATH);
  expect(pictures()).toEqual([
    `${CHARACTERS_PATH}/panda?v=0123abcd`,
    `${CHARACTERS_PATH}/koala?v=0123abcd`,
    "/v1/people/00000001-0000-4000-8000-000000000000/photo?v=1",
  ]);
});

it("keeps initials without a person, and reads nothing", async () => {
  await act(async () =>
    root.render(<PersonAvatar personId={null} name="No owner" size={40} />),
  );
  expect(fetched).not.toHaveBeenCalled();
  expect(host.textContent).toBe("NO");
});
