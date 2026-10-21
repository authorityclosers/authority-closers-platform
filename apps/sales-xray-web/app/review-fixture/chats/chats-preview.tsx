"use client";

/**
 * Chats with fictional leads on WhatsApp, Messenger and Instagram, for
 * screenshots on GitHub (wb-ci --visual). The real Chats page draws; its
 * reads are answered here and nothing leaves the browser.
 * `?open=1` opens the first WhatsApp chat (on a phone, full screen).
 */

import { useEffect, useState } from "react";

import { ChatsRoute } from "../../chats/chats-page";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const NUMBER = "00000000-0000-4000-8000-000000000009";
const PAGE = "00000000-0000-4000-8000-000000000010";
const MINUTE = 60_000;
const lead = (index: number) =>
  `00000000-0000-4000-8000-0000000005${String(index).padStart(2, "0")}`;

function threads(now: number) {
  return (
    [
      [
        "whatsapp",
        "asha fictional",
        "Is the 2 BHK still free this weekend?",
        4,
        true,
        3,
      ],
      ["instagram", "ravi sample", "Price list please", 22, true, 1],
      [
        "messenger",
        "meera fictional",
        "You: Sharing the site visit slots",
        95,
        false,
        0,
      ],
      ["whatsapp", "", "Hello, I saw your ad", 180, true, 2],
      ["whatsapp", "KARAN EXAMPLE", "Thanks, see you Sunday", 600, false, 0],
    ] as const
  ).map(([channel, name, text, minutes, waiting, unread], index) => ({
    channel,
    leadId: lead(index),
    leadName: name,
    lastText: text.replace(/^You: /, ""),
    lastAt: new Date(now - minutes * MINUTE).toISOString(),
    lastDirection: text.startsWith("You: ") ? "out" : "in",
    lastStatus: text.startsWith("You: ") ? "read" : null,
    waiting,
    waitingSince: waiting
      ? new Date(now - minutes * MINUTE).toISOString()
      : null,
    windowOpen: true,
    accountId: channel === "whatsapp" ? null : PAGE,
    place:
      channel === "whatsapp" ? "WhatsApp · Fictional Homes" : "Fictional Homes",
    ownerId: SELLER,
    ownerName: "swamini fictional",
    unread,
  }));
}

function answers(now: number, path: string): unknown {
  if (path === "/v1/lead-desk/chats")
    return { threads: threads(now), sla: { on: true, minutes: 15 } };
  if (path === "/v1/lead-desk/me")
    return {
      person_id: OWNER,
      name: "priya owner",
      role: "owner",
      can_manage: true,
    };
  if (path === `/v1/lead-desk/leads/${lead(0)}/whatsapp`)
    return {
      configured: true,
      connected: true,
      numbers: [
        {
          id: NUMBER,
          displayNumber: "+91 98765 00000",
          verifiedName: "Fictional Homes",
          autoReplies: {},
        },
      ],
      messages: [
        ["in", "Hi, I saw your ad for the Baner flats", 40],
        ["out", "Hello Asha, thanks for writing. 2 BHK or 3 BHK?", 36],
        ["in", "2 BHK. Is it still free this weekend?", 4],
      ].map(([direction, text, minutes], index) => ({
        id: `m${index}`,
        direction,
        kind: "text",
        text,
        status: direction === "out" ? "read" : "received",
        at: new Date(now - Number(minutes) * MINUTE).toISOString(),
      })),
      windowOpen: true,
      windowClosesAt: new Date(now + 20 * 60 * MINUTE).toISOString(),
      optedIn: true,
      templates: [],
    };
  return null;
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const body = path.startsWith("/v1/") ? answers(Date.now(), path) : null;
    if (body !== null)
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

export function ChatsPreview() {
  useState(install);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("open") !== "1") return;
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}#chat=whatsapp:${lead(0)}`,
    );
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, []);
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: OWNER, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <ChatsRoute />
    </WorkspaceAccessContext.Provider>
  );
}
