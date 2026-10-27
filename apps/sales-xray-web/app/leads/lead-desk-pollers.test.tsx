import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  BADGE_EVERY_MS,
  resetChatsStore,
  useChats,
} from "../chats/chats-store";
import { LeadsTabIcon } from "./leads-badge";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Lead OS (27 Oct 2026): outside an organisation every Leads read answers 403,
// and the badge and chats pollers kept asking every 20-40 s. After a 403 they
// stop until the app comes back to the front.
let root: Root;
let host: HTMLDivElement;
const asked: string[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  asked.length = 0;
  resetChatsStore();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal("fetch", async (url: string) => {
    asked.push(String(url));
    return Response.json(
      { detail: "Leads work inside an organisation workspace." },
      { status: 403 },
    );
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}

const count = (part: string) =>
  asked.filter((url) => url.includes(part)).length;

it("stops reading the Leads badge after a 403, until the app is back in front", async () => {
  await act(async () => root.render(<LeadsTabIcon size={20} live />));
  await settle();
  expect(count("/v1/lead-desk/badge")).toBe(1);
  await act(async () => vi.advanceTimersByTimeAsync(10 * 60 * 1000));
  expect(count("/v1/lead-desk/badge")).toBe(1);
  // Back in front: one more try.
  await act(async () => window.dispatchEvent(new Event("focus")));
  await settle();
  expect(count("/v1/lead-desk/badge")).toBe(2);
});

function ChatsReader() {
  useChats({ live: true });
  return null;
}

it("stops polling the chats list after a 403, until the app is back in front", async () => {
  await act(async () => root.render(<ChatsReader />));
  await settle();
  const first = count("/chats");
  expect(first).toBeGreaterThan(0);
  await act(async () => vi.advanceTimersByTimeAsync(BADGE_EVERY_MS * 4));
  expect(count("/chats")).toBe(first);
  await act(async () => {
    vi.advanceTimersByTime(10_000);
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await settle();
  expect(count("/chats")).toBeGreaterThan(first);
});
