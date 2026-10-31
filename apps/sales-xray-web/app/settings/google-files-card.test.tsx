import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../notice-center", () => ({ notify: () => undefined }));

import {
  GOOGLE_FILES_CONNECT,
  type GoogleFiles,
} from "../leads/google-files-client";
import { GoogleFilesCard } from "./google-files-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Settings → Connected apps → Google Sheets and Drive (Lead OS, 27 Oct 2026).
let root: Root;
let host: HTMLDivElement;
let state: GoogleFiles;
let status = 200;
const sent: string[] = [];

const files = (over: Partial<GoogleFiles> = {}): GoogleFiles => ({
  configured: true,
  picker: true,
  connected: true,
  email: "owner@fictional.example",
  connected_by: "Priya Example",
  folder_url: "https://drive.google.com/drive/folders/fictional",
  copy: { on: false, url: null, sent: 0, last_sent_at: null, problem: null },
  ...over,
});

beforeEach(() => {
  sent.length = 0;
  status = 200;
  state = files();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    sent.push(`${method} ${url}`);
    if (status !== 200) return Response.json({ detail: "No." }, { status });
    if (url.endsWith("/google/sheet-copy"))
      state = files({
        copy:
          method === "POST"
            ? {
                on: true,
                url: "https://docs.google.com/spreadsheets/d/fictional",
                sent: 3,
                last_sent_at: null,
                problem: null,
              }
            : {
                on: false,
                url: null,
                sent: 3,
                last_sent_at: null,
                problem: null,
              },
      });
    if (url.endsWith("/google/files/disconnect"))
      state = files({
        connected: false,
        email: null,
        connected_by: null,
        copy: null,
      });
    return Response.json(state);
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const show = async () => {
  await act(async () => root.render(<GoogleFilesCard />));
  await settle();
};

const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === label,
  );

it("stays away where the server doesn't offer it", async () => {
  status = 404;
  await show();
  expect(host.innerHTML).toBe("");
});

it("connects through Google when it isn't connected, and is Coming soon when not set up", async () => {
  state = files({
    connected: false,
    email: null,
    connected_by: null,
    copy: null,
  });
  await show();
  expect(host.textContent).toContain("Not connected");
  const connect = host.querySelector<HTMLAnchorElement>("a[data-variant]");
  expect(connect?.textContent).toBe("Connect");
  expect(connect?.getAttribute("href")).toBe(GOOGLE_FILES_CONNECT);

  await act(async () => root.unmount());
  root = createRoot(host);
  state = files({ configured: false, connected: false, copy: null });
  await show();
  expect(host.textContent).toContain("Coming soon");
  // What works today, as Leads offers it (ph1-23).
  expect(host.textContent).toContain(
    "Today, add a Sheet by its link in Leads, Lead sources, Google Sheet.",
  );
  expect(host.querySelector("a[data-variant]")).toBeNull();
});

it("keeps a copy in Google Sheets with one switch, and disconnects in two taps", async () => {
  await show();
  expect(host.textContent).toContain(
    "owner@fictional.example · connected by Priya Example",
  );
  const copy = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  expect(copy.checked).toBe(false);
  await act(async () => copy.click());
  await settle();
  expect(sent).toContain("POST /v1/lead-desk/google/sheet-copy");
  expect(
    host.querySelector<HTMLInputElement>('input[role="switch"]')!.checked,
  ).toBe(true);
  expect(host.textContent).toContain("3 leads added");
  expect(
    host.querySelector(
      'a[href="https://docs.google.com/spreadsheets/d/fictional"]',
    )?.textContent,
  ).toBe("Open the Sheet");

  await act(async () => button("Disconnect")!.click());
  expect(sent.some((line) => line.includes("disconnect"))).toBe(false);
  await act(async () => button("Disconnect Google")!.click());
  await settle();
  expect(sent).toContain("POST /v1/lead-desk/google/files/disconnect");
  expect(host.textContent).toContain("Not connected");
});
