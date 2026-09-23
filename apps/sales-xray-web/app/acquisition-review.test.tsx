import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock(
  "./processing-review-port",
  () => import("./processing-review-port.dev"),
);
vi.mock("./upload-check", () => ({
  UploadCheck: () => <span>Upload verification</span>,
}));
import Page from "./page";
import { entry, policy } from "../tests/acquisition-fixture";

const selected = "11111111-1111-4111-8111-111111111111";
const empty = "22222222-2222-4222-8222-222222222222";
let root: Root, container: HTMLDivElement;
let requests: { path: string; init: RequestInit }[];
let originalCreateObjectUrl: PropertyDescriptor | undefined;
let originalRevokeObjectUrl: PropertyDescriptor | undefined;
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
function frame(id: string) {
  return {
    id,
    observedAt: Date.now() - 100,
    expiresAt: Date.now() + 60_000,
    label:
      id === selected
        ? "Selected call with Hindi report"
        : "Empty upload screen",
    observation: {
      phase: id === selected ? "upload.file.selected" : "upload.empty",
      file_name: id === selected ? "Observed sales conversation.wav" : null,
      file_size_bytes: id === selected ? 4096 : null,
      privacy_open: id === selected,
      consent_checked: id === selected,
      report_language: id === selected ? "hi-Deva+en" : "en",
      verification: "guest-challenge-required",
    },
  };
}
beforeEach(() => {
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  localStorage.clear();
  window.history.replaceState(null, "", `/?new=1&sx-review-local=${selected}`);
  requests = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      requests.push({ path, init });
      if (path === "/health") return response({ analysis_read_only: true });
      if (path === "/__review/api/local/catalog")
        return response({
          frames: [selected, empty].map((id) => ({
            id,
            state: frame(id).observation.phase,
          })),
        });
      if (path.startsWith("/__review/api/local/frames/"))
        return response(frame(path.split("/").at(-1)!));
      if (path.endsWith("/entry"))
        return response({
          ...entry,
          report_language_default: "en",
          report_languages: ["en", "hi-Deva+en", "mr-Deva+en"],
        });
      if (path.endsWith("/upload-policy")) return response(policy);
      if (path.endsWith("/availability")) return response({ paused: false });
      return response({}, 401);
    }),
  );
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  if (originalCreateObjectUrl)
    Object.defineProperty(URL, "createObjectURL", originalCreateObjectUrl);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevokeObjectUrl)
    Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectUrl);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
  originalCreateObjectUrl = undefined;
  originalRevokeObjectUrl = undefined;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("the mounted page displays observed upload controls without applying consent or issuing a command", async () => {
  const page = await Page({ searchParams: Promise.resolve({}) });
  await act(async () => root.render(page));
  await act(async () => {
    for (let index = 0; index < 20; index++) await Promise.resolve();
  });
  expect(container.textContent).toContain("Observed sales conversation.wav");
  expect(container.textContent).toContain(
    "Guest verification was required at capture. The challenge is not run in read-only review.",
  );
  expect(container.textContent).not.toContain("Upload verification");
  expect(
    container.querySelector<HTMLInputElement>('input[type="file"]')?.files
      ?.length ?? 0,
  ).toBe(0);
  const consent = container.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  expect(
    consent,
    container.textContent ?? "No mounted page text",
  ).not.toBeNull();
  expect(consent.checked).toBe(true);
  expect(consent.disabled).toBe(true);
  expect(
    container.querySelector<HTMLSelectElement>("#report-language")?.value,
  ).toBe("hi-Deva+en");
  const privacy = [...container.querySelectorAll("details")].find(
    (element) =>
      element.querySelector("summary")?.textContent === "Privacy details",
  );
  expect(privacy?.open).toBe(true);
  const analyse = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent?.includes("Analyse my call"))!;
  expect(analyse.disabled).toBe(true);
  await act(async () => analyse.click());
  expect(requests.every((r) => !r.init.method || r.init.method === "GET")).toBe(
    true,
  );
  expect(
    container.querySelector<HTMLAnchorElement>(
      'a[href*="sx-review-local=' + empty + '"]',
    ),
  ).not.toBeNull();

  window.history.pushState(null, "", `/?new=1&sx-review-local=${empty}`);
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
  expect(container.textContent).toContain("Add a call to review");
  expect(container.textContent).not.toContain(
    "Observed sales conversation.wav",
  );
  expect(container.querySelector('input[type="checkbox"]')).toBeNull();
  expect(requests.every((r) => !r.init.method || r.init.method === "GET")).toBe(
    true,
  );
});

it("keeps the previous valid file in a validation-error observation", async () => {
  window.history.replaceState(null, "", "/?new=1");
  const observations: Record<string, unknown>[] = [];
  requests = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      requests.push({ path, init });
      if (path === "/health") return response({ analysis_read_only: true });
      if (path === "/__review/api/local/observe" && init.method === "POST") {
        observations.push(
          JSON.parse(String(init.body)).observation as Record<string, unknown>,
        );
        return response({ id: "33333333-3333-4333-8333-333333333333" });
      }
      if (path.endsWith("/entry"))
        return response({
          ...entry,
          report_language_default: "en",
          report_languages: ["en", "hi-Deva+en", "mr-Deva+en"],
        });
      if (path.endsWith("/upload-policy")) return response(policy);
      if (path.endsWith("/availability")) return response({ paused: false });
      return response({}, 401);
    }),
  );
  originalCreateObjectUrl = Object.getOwnPropertyDescriptor(
    URL,
    "createObjectURL",
  );
  originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(
    URL,
    "revokeObjectURL",
  );
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: () => "blob:ac-review-test",
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined,
  });

  const page = await Page({ searchParams: Promise.resolve({}) });
  await act(async () => root.render(page));
  const flush = async () => {
    for (let index = 0; index < 30; index++) await Promise.resolve();
  };
  await act(flush);
  expect(container.textContent).not.toContain("Upload verification");
  const input =
    container.querySelector<HTMLInputElement>('input[type="file"]')!;
  expect(input.disabled).toBe(false);
  const select = async (name: string) => {
    const chosen = new File(["synthetic audio"], name, {
      type: name.endsWith(".wav") ? "audio/wav" : "application/pdf",
    });
    await act(async () => {
      Object.defineProperty(input, "files", {
        configurable: true,
        value: [chosen],
      });
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await flush();
    });
  };
  await select("Previously valid call.wav");
  expect(container.textContent).toContain("Previously valid call.wav");
  await select("invalid replacement.pdf");
  expect(container.textContent).toContain("Previously valid call.wav");
  expect(container.textContent).toContain(
    "Choose an MP3, MPEG, WAV, M4A, OGG or FLAC within the displayed size limit.",
  );
  expect(observations.at(-1)).toEqual({
    phase: "upload.validation.error",
    privacy_open: false,
    consent_checked: false,
    report_language: "en",
    verification: "guest-challenge-required",
    file_name: "Previously valid call.wav",
    file_size_bytes: new File(["synthetic audio"], "Previously valid call.wav")
      .size,
  });
});
