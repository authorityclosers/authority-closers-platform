"use client";

/**
 * A lead's chats for its page (lead hub, approved map slice 6, 22 Oct 2026): read
 * once, shared by the timeline and the chat sections below it. In the timeline a
 * chat is one line per app per day ("3 WhatsApp messages"), so calls, notes and
 * stage changes are never swamped; the line opens the chat in Chats.
 */

import { useEffect, useState } from "react";

import { chatHref } from "../chats/chats-client";
import type { SocialConversation } from "./social-client";
import { waCall, type WaConversation } from "./whatsapp-client";

export type ChatApp = "whatsapp" | "messenger" | "instagram";

export type ChatDay = {
  key: string;
  /** The day's last message: where the line sits in the timeline. */
  at: string;
  app: ChatApp;
  count: number;
  /** Their messages that day. */
  inbound: number;
  last: { text: string; mine: boolean } | null;
  href: string;
};

export const APP_WORDS: Record<ChatApp, string> = {
  whatsapp: "WhatsApp",
  messenger: "Messenger",
  instagram: "Instagram",
};

type Message = { direction: "in" | "out"; text?: string | null; at: string };

/** The local calendar day a message falls on (the browser's own time zone). */
function dayKey(iso: string): string {
  const at = new Date(iso);
  return `${at.getFullYear()}-${at.getMonth()}-${at.getDate()}`;
}

function daysOf(
  app: ChatApp,
  messages: readonly Message[],
  href: string,
  place = "",
): ChatDay[] {
  const days = new Map<string, ChatDay>();
  for (const message of messages) {
    if (Number.isNaN(Date.parse(message.at))) continue;
    const key = `${app}:${place}:${dayKey(message.at)}`;
    const day = days.get(key) ?? {
      key,
      at: message.at,
      app,
      count: 0,
      inbound: 0,
      last: null,
      href,
    };
    day.count += 1;
    if (message.direction === "in") day.inbound += 1;
    if (Date.parse(message.at) >= Date.parse(day.at) || day.count === 1) {
      day.at = message.at;
      day.last = message.text?.trim()
        ? { text: message.text.trim(), mine: message.direction === "out" }
        : day.last;
    }
    days.set(key, day);
  }
  return [...days.values()];
}

/** Every app's messages, one line per app per day, newest first. */
export function chatDays(
  leadId: string,
  wa: WaConversation | null | undefined,
  social: SocialConversation | null | undefined,
): ChatDay[] {
  const all = [
    ...(wa?.configured && wa.connected
      ? daysOf("whatsapp", wa.messages, chatHref("whatsapp", leadId))
      : []),
    ...(social?.configured
      ? social.threads.flatMap((thread) =>
          daysOf(
            thread.channel,
            thread.messages,
            chatHref(thread.channel, leadId, thread.accountId),
            thread.accountId,
          ),
        )
      : []),
  ];
  return all.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

/** In words: "3 WhatsApp messages", "1 Instagram message". */
export function chatDayTitle(day: ChatDay): string {
  return `${day.count} ${APP_WORDS[day.app]} ${day.count === 1 ? "message" : "messages"}`;
}

export type LeadConversations = {
  /** Undefined while reading; null when the app isn't set up or didn't answer. */
  wa: WaConversation | null | undefined;
  social: SocialConversation | null | undefined;
};

/** The lead's WhatsApp and Messenger / Instagram chats, read once per lead. */
export function useLeadConversations(leadId: string): LeadConversations {
  const [read, setRead] = useState<{
    leadId: string;
    wa?: WaConversation | null;
    social?: SocialConversation | null;
  }>({ leadId });
  useEffect(() => {
    let live = true;
    // A reply for this lead keeps what this lead has already; another lead's goes.
    const keep = (part: {
      wa?: WaConversation | null;
      social?: SocialConversation | null;
    }) =>
      live &&
      setRead((now) =>
        now.leadId === leadId ? { ...now, ...part } : { leadId, ...part },
      );
    waCall<WaConversation>(`/leads/${leadId}/whatsapp`).then(
      (wa) => keep({ wa }),
      () => keep({ wa: null }),
    );
    waCall<SocialConversation>(`/leads/${leadId}/social`).then(
      (data) => keep({ social: Array.isArray(data?.threads) ? data : null }),
      () => keep({ social: null }),
    );
    return () => {
      live = false;
    };
  }, [leadId]);
  return read.leadId === leadId
    ? { wa: read.wa, social: read.social }
    : { wa: undefined, social: undefined };
}
