// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountProfile } from "./account-profile";
import {
  ACCOUNT_PROFILE_ELIGIBILITY_PATH,
  ACCOUNT_PROFILE_PATH,
} from "./account-profile-client";
import { PROFILE_UPDATED_EVENT } from "./profile-menu";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let profileUpdatedCount: number;
let onProfileUpdated: (event: Event) => void;
const selectedFile = { name: "Chosen call.wav", size: 24, type: "audio/wav" };
const baseProfile = {
  name: null,
  email: "morgan@example.test",
  phone_number_e164: null,
  phone_verified: false,
  profile_complete: false,
  revision: 0,
};

const json = (body: unknown, status = 200) => Response.json(body, { status });
const flush = async () => {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  profileUpdatedCount = 0;
  onProfileUpdated = () => {
    profileUpdatedCount += 1;
  };
  window.addEventListener(PROFILE_UPDATED_EVENT, onProfileUpdated);
});

afterEach(async () => {
  await act(async () => root.unmount());
  window.removeEventListener(PROFILE_UPDATED_EVENT, onProfileUpdated);
  host.remove();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

async function changeInput(name: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function changeCountry(value: string) {
  const select = host.querySelector<HTMLSelectElement>(
    'select[name="phone_country"]',
  )!;
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    host
      .querySelector<HTMLFormElement>("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await flush();
}

it("keeps the selected file in view and advances only after a server 204", async () => {
  const onEligible = vi.fn();
  const requests: Array<{ path: string; init: RequestInit }> = [];
  let currentProfile = baseProfile;
  let eligibility = 403;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      requests.push({ path, init });
      if (path === ACCOUNT_PROFILE_ELIGIBILITY_PATH)
        return new Response(null, { status: eligibility });
      if (path === ACCOUNT_PROFILE_PATH && init.method === "PUT") {
        const body = JSON.parse(String(init.body));
        currentProfile = {
          ...baseProfile,
          name: body.full_name,
          phone_number_e164: body.phone_number_e164,
          revision: 1,
        };
        return new Response(null, { status: 204 });
      }
      if (path === ACCOUNT_PROFILE_PATH) return json(currentProfile);
      throw new Error(`Unexpected request: ${path}`);
    }),
  );
  await act(async () =>
    root.render(
      <AccountProfile selectedFile={selectedFile} onEligible={onEligible} />,
    ),
  );
  await flush();
  expect(host.textContent).toContain(selectedFile.name);
  expect(host.textContent).toContain("still in this browser");
  await changeInput("full_name", "Morgan Lee");
  await changeCountry("US");
  await changeInput("phone_number_e164", "+14155550123");
  await submit();
  expect(profileUpdatedCount).toBe(1);
  expect(onEligible).not.toHaveBeenCalled();
  expect(host.textContent).toContain("details were saved");
  expect(host.textContent).toContain("No audio was uploaded");
  const put = requests.find((request) => request.init.method === "PUT")!;
  expect(JSON.parse(String(put.init.body))).toEqual({
    full_name: "Morgan Lee",
    phone_number_e164: "+14155550123",
    expected_revision: 0,
  });
  expect(requests.map((request) => request.path)).toEqual([
    ACCOUNT_PROFILE_PATH,
    ACCOUNT_PROFILE_ELIGIBILITY_PATH,
    ACCOUNT_PROFILE_PATH,
    ACCOUNT_PROFILE_PATH,
    ACCOUNT_PROFILE_ELIGIBILITY_PATH,
  ]);
  eligibility = 204;
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Check access again"))!
      .click(),
  );
  await flush();
  expect(onEligible).toHaveBeenCalledTimes(1);
});

it("keeps a draft on a revision conflict and requires review before resaving", async () => {
  const onEligible = vi.fn();
  let profileReads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      if (path === ACCOUNT_PROFILE_ELIGIBILITY_PATH)
        return new Response(null, { status: 403 });
      if (init.method === "PUT") return new Response(null, { status: 409 });
      profileReads += 1;
      return json({ ...baseProfile, revision: profileReads === 1 ? 0 : 1 });
    }),
  );
  await act(async () =>
    root.render(
      <AccountProfile selectedFile={selectedFile} onEligible={onEligible} />,
    ),
  );
  await flush();
  await changeInput("full_name", "Morgan Lee");
  await changeCountry("US");
  await changeInput("phone_number_e164", "+14155550123");
  await submit();
  expect(profileUpdatedCount).toBe(0);
  expect(onEligible).not.toHaveBeenCalled();
  expect(host.textContent).toContain("changed in another session");
  expect(
    host.querySelector<HTMLInputElement>('input[name="full_name"]')?.value,
  ).toBe("Morgan Lee");
  expect(
    host.querySelector<HTMLInputElement>('input[name="phone_number_e164"]')
      ?.value,
  ).toBe("+14155550123");
});

it("offers the parent a sign-in recovery callback without navigating away", async () => {
  const onEligible = vi.fn();
  const onSignIn = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 401 })),
  );
  await act(async () =>
    root.render(
      <AccountProfile
        selectedFile={selectedFile}
        onEligible={onEligible}
        onSignIn={onSignIn}
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain(selectedFile.name);
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Sign in again"))!
      .click(),
  );
  expect(onSignIn).toHaveBeenCalledTimes(1);
  expect(onEligible).not.toHaveBeenCalled();
});

it("focuses missing details and never sends an invalid phone number", async () => {
  const fetcher = vi.fn(async (path: string) =>
    path === ACCOUNT_PROFILE_PATH
      ? json(baseProfile)
      : new Response(null, { status: 403 }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <AccountProfile selectedFile={selectedFile} onEligible={vi.fn()} />,
    ),
  );
  await flush();
  await submit();
  expect(document.activeElement).toBe(
    host.querySelector('input[name="full_name"]'),
  );
  await changeInput("full_name", "Morgan Lee");
  await submit();
  expect(document.activeElement).toBe(
    host.querySelector('select[name="phone_country"]'),
  );
  await changeCountry("US");
  await changeInput("phone_number_e164", "415 555 0123");
  await submit();
  expect(document.activeElement).toBe(
    host.querySelector('input[name="phone_number_e164"]'),
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("renders each local profile fixture without profile reads, writes or eligibility callbacks", async () => {
  const fetcher = vi.fn();
  const onEligible = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <AccountProfile
        selectedFile={selectedFile}
        onEligible={onEligible}
        previewState="profile.required"
      />,
    ),
  );
  await flush();
  expect(host.querySelector("form")).not.toBeNull();
  await changeInput("full_name", "Preview User");
  await changeCountry("OTHER");
  await changeInput("phone_number_e164", "+12025550123");
  await submit();
  expect(host.textContent).toContain("does not save an account");

  await act(async () =>
    root.render(
      <AccountProfile
        selectedFile={selectedFile}
        onEligible={onEligible}
        previewState="profile.unverified"
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("mobile number is not verified yet");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Check access again"))!
      .click(),
  );

  await act(async () =>
    root.render(
      <AccountProfile
        selectedFile={selectedFile}
        onEligible={onEligible}
        previewState="profile.ready"
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("profile is ready for call review");
  expect(fetcher).not.toHaveBeenCalled();
  expect(onEligible).not.toHaveBeenCalled();
});

it("ignores the preview prop in a production build", async () => {
  vi.stubEnv("NODE_ENV", "production");
  const fetcher = vi.fn(async (path: string) =>
    path === ACCOUNT_PROFILE_PATH
      ? json(baseProfile)
      : new Response(null, { status: 403 }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <AccountProfile
        selectedFile={selectedFile}
        onEligible={vi.fn()}
        previewState="profile.ready"
      />,
    ),
  );
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(host.textContent).not.toContain("local preview");
});
