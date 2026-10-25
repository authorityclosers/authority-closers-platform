// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notices = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("../notice-center", () => notices);
const opener = vi.hoisted(() => ({ openSettings: vi.fn() }));
vi.mock("../settings-open", async (original) => ({
  ...(await original<object>()),
  ...opener,
}));
vi.mock("./profile-details-client", async (original) => ({
  ...(await original<typeof import("./profile-details-client")>()),
  // happy-dom has no image decoder; the crop is the browser's job.
  squarePhoto: vi.fn(async () => new Blob(["webp"], { type: "image/webp" })),
}));

import { invalidateShellProfile } from "../shell/profile-store";
import { ProfileCompletionCard, ProfileDetailsPanel } from "./profile-details";
import {
  missingWords,
  normalizeHandle,
  profileDetails,
} from "./profile-details-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const PERSON = "5f0c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a";
const PHOTO = `/v1/people/${PERSON}/photo?v=0a1b2c3d`;
const PROFILE = {
  name: "Fictional Seller",
  email: "seller@example.test",
  photo_url: null,
  phone_number_e164: "+919800000000",
  phone_verified: true,
  profile_complete: true,
  revision: 3,
  handle: null,
  title: null,
  team: null,
  details_revision: 0,
  avatar_url: null,
  own_photo: false,
  completion: {
    done: 2,
    total: 6,
    missing: ["photo", "handle", "title", "team"],
  },
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  notices.notify.mockReset();
  opener.openSettings.mockReset();
  invalidateShellProfile();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = () =>
  act(async () => new Promise((done) => setTimeout(done, 0)));
const input = (name: string) =>
  host.querySelector(`input[name="${name}"]`) as HTMLInputElement;
const button = (words: string) =>
  Array.from(host.querySelectorAll("button")).find((item) =>
    item.textContent?.includes(words),
  );
function type(field: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const submit = () =>
  act(async () => {
    host
      .querySelector("form")
      ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });

type Call = { url: string; method: string; type?: string; body?: unknown };
function serve(answer: (call: Call) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const call: Call = {
        url,
        method: init?.method ?? "GET",
        type: headers["content-type"],
        body:
          typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      };
      calls.push(call);
      return answer(call);
    }),
  );
  return calls;
}

it("reads the profile fields strictly and words what is missing", () => {
  const record = {
    ...PROFILE,
    handle: "priya.s",
    avatar_url: PHOTO,
    own_photo: true,
    completion: { done: 3, total: 6, missing: ["photo", "admin", "team"] },
  };
  expect(profileDetails(record as never)).toEqual({
    handle: "priya.s",
    title: null,
    team: null,
    revision: 0,
    avatarUrl: PHOTO,
    ownPhoto: true,
    completion: { done: 3, total: 6, missing: ["photo", "team"] },
  });
  const elsewhere = { ...PROFILE, avatar_url: "https://elsewhere.test/a.png" };
  expect(profileDetails(elsewhere as never).avatarUrl).toBeNull();
  const odd = { ...PROFILE, completion: { done: 7, total: 6, missing: [] } };
  expect(profileDetails(odd as never).completion).toBeNull();
  expect(missingWords(["photo", "handle", "team"])).toBe(
    "a photo, a user id and your team",
  );
  expect(missingWords(["phone"])).toBe("your phone number");
  expect(normalizeHandle(" @Priya.S ")).toBe("priya.s");
  expect(normalizeHandle("ab")).toBeNull();
  expect(normalizeHandle("-priya")).toBeNull();
});

it("saves the user id, title and team, then reads the profile again", async () => {
  let current: object = PROFILE;
  const calls = serve(({ method }) => {
    if (method === "PUT")
      current = {
        ...PROFILE,
        details_revision: 1,
        handle: "priya.s",
        title: "Sales lead",
        completion: { done: 4, total: 6, missing: ["photo", "team"] },
      };
    return Response.json(current);
  });
  await act(async () => root.render(<ProfileDetailsPanel />));
  await settle();
  expect(host.textContent).toContain("2 of 6");
  expect(host.textContent).toContain(
    "Add a photo, a user id, your job title and your team",
  );
  expect(button("Save profile")?.disabled).toBe(true);
  type(input("handle"), "@Priya.S");
  type(input("title"), "Sales lead");
  expect(button("Save profile")?.disabled).toBe(false);
  await submit();
  await settle();
  expect(calls.filter((call) => call.method === "PUT")).toEqual([
    {
      url: "/v1/me/sales-xray-profile/details",
      method: "PUT",
      type: "application/json",
      body: {
        handle: "priya.s",
        title: "Sales lead",
        team: "",
        expected_revision: 0,
      },
    },
  ]);
  expect(host.textContent).toContain("4 of 6");
  expect(host.textContent).toContain("@priya.s");
  expect(input("handle").value).toBe("priya.s");
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success", title: "Profile saved" }),
  );
});

it("says why a user id cannot be saved, under the field, keeping the draft", async () => {
  const calls = serve(({ method }) =>
    method === "PUT"
      ? Response.json(
          { detail: "That user id is taken. Try another." },
          { status: 409 },
        )
      : Response.json(PROFILE),
  );
  await act(async () => root.render(<ProfileDetailsPanel />));
  await settle();
  type(input("handle"), "a");
  await submit();
  expect(host.querySelector("[role='alert']")?.textContent).toContain(
    "3 to 30 letters",
  );
  expect(calls.some((call) => call.method === "PUT")).toBe(false);
  type(input("handle"), "priya.s");
  expect(host.querySelector("[role='alert']")).toBeNull();
  await submit();
  await settle();
  expect(host.querySelector("[role='alert']")?.textContent).toBe(
    "That user id is taken. Try another.",
  );
  expect(input("handle").value).toBe("priya.s");
  expect(notices.notify).not.toHaveBeenCalled();
});

it("crops a chosen photo, uploads it, and offers Remove for the person's own", async () => {
  let current: object = PROFILE;
  const calls = serve(({ method, url }) => {
    if (method === "PUT" && url.endsWith("/photo"))
      current = {
        ...PROFILE,
        avatar_url: PHOTO,
        own_photo: true,
        completion: {
          done: 3,
          total: 6,
          missing: ["handle", "title", "team"],
        },
      };
    return Response.json(current);
  });
  await act(async () => root.render(<ProfileDetailsPanel />));
  await settle();
  expect(button("Add photo")).toBeTruthy();
  expect(button("Remove")).toBeUndefined();
  const picker = host.querySelector("input[type='file']") as HTMLInputElement;
  Object.defineProperty(picker, "files", {
    configurable: true,
    value: [new File(["jpeg"], "me.jpg", { type: "image/jpeg" })],
  });
  await act(async () => {
    picker.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
  expect(calls.find((call) => call.method === "PUT")).toMatchObject({
    url: "/v1/me/sales-xray-profile/photo",
    type: "image/webp",
  });
  expect(host.querySelector("img")?.getAttribute("src")).toBe(PHOTO);
  expect(button("Change photo")).toBeTruthy();
  expect(button("Remove")).toBeTruthy();
  expect(host.textContent).toContain("3 of 6");
});

it("shows the Home card until the profile is complete", async () => {
  serve(() => Response.json(PROFILE));
  await act(async () => root.render(<ProfileCompletionCard />));
  await settle();
  expect(host.textContent).toContain("2 of 6");
  await act(async () => button("Finish profile")?.click());
  expect(opener.openSettings).toHaveBeenCalledWith("profile");
  await act(async () => root.unmount());
  invalidateShellProfile();
  root = createRoot(host);
  serve(() =>
    Response.json({
      ...PROFILE,
      completion: { done: 6, total: 6, missing: [] },
    }),
  );
  await act(async () => root.render(<ProfileCompletionCard />));
  await settle();
  expect(host.textContent).toBe("");
});
