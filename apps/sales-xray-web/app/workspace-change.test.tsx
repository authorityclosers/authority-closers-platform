import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const chatAnswers: ((list: unknown) => void)[] = [];
vi.mock("./chats/chats-client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readChats: vi.fn(
    () => new Promise((resolve) => void chatAnswers.push(resolve)),
  ),
}));
const badgeAnswers: ((badge: unknown) => void)[] = [];
vi.mock("./leads/badge-client", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readBadge: vi.fn(
    () => new Promise((resolve) => void badgeAnswers.push(resolve)),
  ),
}));

import { resetChatsStore, useChats } from "./chats/chats-store";
import { LeadsTabIcon } from "./leads/leads-badge";
import {
  announceWorkspaceChange,
  justArrived,
  resetWorkspaceChangeForTests,
  workspaceGeneration,
} from "./workspace-change";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner bug #17 (29 Oct 2026): a workspace switch no longer reloads the page,
// so what one workspace read must never show under another.

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  // The badges read only while the page is in view.
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  chatAnswers.length = 0;
  badgeAnswers.length = 0;
  resetChatsStore();
  resetWorkspaceChangeForTests();
});

function Chats() {
  const { list } = useChats({ live: true });
  return <p data-chats={list ? "listed" : "none"} />;
}

const chats = () =>
  host.querySelector("[data-chats]")?.getAttribute("data-chats");
const settle = () =>
  act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });

it("forgets the old workspace's chats and drops an answer that lands after the switch", async () => {
  await act(async () => root.render(<Chats />));
  expect(chatAnswers).toHaveLength(1);
  await act(async () => chatAnswers[0]({ threads: [] }));
  await settle();
  expect(chats()).toBe("listed");

  await act(async () => {
    announceWorkspaceChange("leaving");
  });
  expect(chats()).toBe("none");
  // Leaving reads nothing yet: the server still has the old workspace.
  expect(chatAnswers).toHaveLength(1);

  await act(async () => {
    announceWorkspaceChange("arrived");
  });
  // Landed: the new workspace's list is read at once.
  expect(chatAnswers).toHaveLength(2);
  await act(async () => chatAnswers[1]({ threads: [] }));
  await settle();
  expect(chats()).toBe("listed");
});

it("never shows a poll that was sent for the workspace being left", async () => {
  await act(async () => root.render(<Chats />));
  const stale = chatAnswers[0];
  await act(async () => {
    announceWorkspaceChange("leaving");
  });
  await act(async () => stale({ threads: [] }));
  await settle();
  expect(chats()).toBe("none");
});

it("clears the Leads badge's counts on a switch and reads the new workspace's", async () => {
  await act(async () => root.render(<LeadsTabIcon live />));
  expect(badgeAnswers).toHaveLength(1);
  await act(async () => badgeAnswers[0]({ overdue: 3, to_call: 0 }));
  await settle();
  expect(host.textContent).toContain("3");

  const before = workspaceGeneration();
  await act(async () => {
    announceWorkspaceChange("leaving");
  });
  expect(workspaceGeneration()).toBe(before + 1);
  expect(host.textContent).not.toContain("3");

  await act(async () => {
    announceWorkspaceChange("arrived");
  });
  expect(badgeAnswers).toHaveLength(2);
  await act(async () => badgeAnswers[1]({ overdue: 0, to_call: 2 }));
  await settle();
  expect(host.textContent).toContain("2");
  expect(justArrived()).toBe(true);
});
