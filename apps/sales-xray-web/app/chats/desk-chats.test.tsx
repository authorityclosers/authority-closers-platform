import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DeskChats } from "./desk-chats";

const LEAD = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
let root: Root;
let host: HTMLDivElement;
let social: unknown[];

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  social = [
    {
      leadId: LEAD,
      leadName: "Asha Rao",
      channel: "messenger",
      lastText: "Can we visit on Saturday?",
      lastAt: new Date(Date.now() - 5 * 60000).toISOString(),
      waiting: true,
      windowOpen: true,
    },
    {
      leadId: OTHER,
      leadName: "Ravi Iyer",
      channel: "instagram",
      lastText: "Thanks!",
      lastAt: new Date(Date.now() - 90 * 60000).toISOString(),
      waiting: false,
      windowOpen: true,
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/social/inbox")
        ? json(social)
        : String(input).endsWith("/chats")
          ? json({ detail: "Not here." }, 404)
          : json({ detail: "WhatsApp isn't set up." }, 409),
    ),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const settle = async () => {
  for (let index = 0; index < 5; index += 1)
    await act(async () => {
      await Promise.resolve();
    });
};

it("puts waiting chats on the desk, each opening in Chats", async () => {
  await act(async () => root.render(<DeskChats />));
  await settle();
  expect(host.textContent).toContain("1 waiting for a reply");
  const rows = [...host.querySelectorAll<HTMLAnchorElement>("li a")];
  expect(rows.map((row) => row.getAttribute("href"))).toEqual([
    `/chats#chat=messenger:${LEAD}`,
  ]);
  expect(host.querySelector("header a")?.getAttribute("href")).toBe("/chats");
});

it("shows nothing until someone has written", async () => {
  social = [];
  await act(async () => root.render(<DeskChats />));
  await settle();
  expect(host.innerHTML).toBe("");
});
