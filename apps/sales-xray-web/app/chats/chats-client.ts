/**
 * Chats (owner, 20 Oct 2026: "a better chat experience and not everything
 * confused on one panel"): every WhatsApp, Messenger and Instagram
 * conversation of the Sales Xray CRM in one inbox, read from the CRM's own
 * routes (/v1/lead-desk). A seller sees their own leads' chats; a manager
 * sees the team's.
 *
 * Reads accept any extra field the server adds later (owner, reply clock,
 * read marks) and work without it, so the screen never waits on the server.
 */

import { LeadsError } from "../leads/leads-client";
import {
  sendSocial,
  type SocialConversation,
  type SocialInboxThread,
  type SocialThread,
} from "../leads/social-client";
import {
  sendWhatsApp,
  waCall,
  type WaConversation,
  type WaTemplate,
  type WaThread,
} from "../leads/whatsapp-client";

export const CHATS_PATH = "/chats";

export type ChatChannel = "whatsapp" | "messenger" | "instagram";

export const CHANNELS: ChatChannel[] = ["whatsapp", "messenger", "instagram"];

export const CHANNEL_LABEL: Record<ChatChannel, string> = {
  whatsapp: "WhatsApp",
  messenger: "Messenger",
  instagram: "Instagram",
};

/** One conversation in the list. Fields after `windowOpen` arrive later from the server. */
export type ChatThread = {
  key: string;
  channel: ChatChannel;
  leadId: string | null;
  leadName: string;
  lastText: string | null;
  lastAt: string;
  /** Their message is the newest: someone should answer. */
  waiting: boolean;
  windowOpen: boolean;
  accountId?: string | null;
  place?: string | null;
  lastKind?: string | null;
  lastDirection?: "in" | "out" | null;
  lastStatus?: string | null;
  /** Their first message after our last reply: when the reply clock started. */
  waitingSince?: string | null;
  ownerId?: string | null;
  ownerName?: string | null;
  /** Their messages since this person last opened the chat (server read marks). */
  unread?: number | null;
};

export type ChatList = {
  threads: ChatThread[];
  /** The server says who owns each lead, so Mine and Unassigned can filter. */
  owners: boolean;
  /** The organisation's first-response target, when the list carries it. */
  sla?: Sla | null;
};

export type Sla = { on: boolean; minutes: number };

type Extra = Partial<
  Pick<
    ChatThread,
    | "accountId"
    | "place"
    | "lastKind"
    | "lastDirection"
    | "lastStatus"
    | "waitingSince"
    | "ownerId"
    | "ownerName"
    | "unread"
  >
>;

/** The address of one chat, for "Open in Chats" elsewhere in the app. */
export function chatHref(
  channel: ChatChannel,
  leadId: string,
  accountId?: string | null,
): string {
  return `${CHATS_PATH}#chat=${[channel, leadId, accountId].filter(Boolean).join(":")}`;
}

/** Two references to one conversation (an account id may be missing on one). */
export function sameThread(
  a: Pick<ChatThread, "channel" | "leadId" | "accountId">,
  b: Pick<ChatThread, "channel" | "leadId" | "accountId">,
): boolean {
  return (
    a.channel === b.channel &&
    !!a.leadId &&
    a.leadId === b.leadId &&
    (!a.accountId || !b.accountId || a.accountId === b.accountId)
  );
}

/** The same conversation keeps the same key across reads. */
export function threadKey(
  channel: ChatChannel,
  leadId: string | null,
  accountId?: string | null,
  fallback = "",
): string {
  return [channel, leadId ?? `none-${fallback}`, accountId ?? ""]
    .filter((part, index) => index < 2 || part)
    .join(":");
}

function toThread(
  row: (SocialInboxThread | WaThread) & Extra,
  channel: ChatChannel,
  index: number,
): ChatThread {
  return {
    key: threadKey(channel, row.leadId ?? null, row.accountId, String(index)),
    channel,
    leadId: row.leadId ?? null,
    leadName: row.leadName || CHANNEL_LABEL[channel],
    lastText: row.lastText ?? null,
    lastAt: row.lastAt,
    waiting: Boolean(row.waiting),
    windowOpen: Boolean(row.windowOpen),
    accountId: row.accountId ?? null,
    place: row.place ?? null,
    lastKind: row.lastKind ?? null,
    lastDirection: row.lastDirection ?? (row.waiting ? "in" : null),
    lastStatus: row.lastStatus ?? null,
    waitingSince: row.waitingSince ?? null,
    ownerId: row.ownerId ?? null,
    ownerName: row.ownerName ?? null,
    unread: typeof row.unread === "number" ? row.unread : null,
  };
}

const isRow = (value: unknown): value is SocialInboxThread =>
  !!value &&
  typeof (value as SocialInboxThread).lastAt === "string" &&
  typeof (value as SocialInboxThread).leadName === "string";

/** Waiting first, then the newest: the order a seller answers in. */
export function sortThreads(threads: ChatThread[]): ChatThread[] {
  return [...threads].sort(
    (a, b) =>
      Number(b.waiting) - Number(a.waiting) ||
      new Date(b.lastAt).getTime() - new Date(a.lastAt).getTime(),
  );
}

function slaOf(value: unknown): Sla | null {
  const sla = value as Partial<Sla> | null;
  return sla && typeof sla.minutes === "number" && sla.minutes > 0
    ? { on: sla.on !== false, minutes: sla.minutes }
    : null;
}

/** GET /chats: the three channels in one list, with the reply target. */
function fromChats(value: unknown): ChatList | null {
  const body = value as { threads?: unknown; sla?: unknown } | null;
  if (!body || !Array.isArray(body.threads)) return null;
  const rows = (body.threads as unknown[]).filter(isRow) as ((
    | SocialInboxThread
    | WaThread
  ) &
    Extra & { channel?: unknown })[];
  const threads = rows
    .filter((row) => CHANNELS.includes(row.channel as ChatChannel))
    .map((row, index) => toThread(row, row.channel as ChatChannel, index));
  const seen = new Set<string>();
  return {
    threads: sortThreads(threads).filter((thread) => {
      if (seen.has(thread.key)) return false;
      seen.add(thread.key);
      return true;
    }),
    owners: rows.some((row) => "ownerId" in row),
    sla: slaOf(body.sla),
  };
}

/**
 * Every conversation of the last month across the three channels, in one read
 * (GET /chats). An older server without it answers from the two inboxes.
 */
export async function readChats(): Promise<ChatList> {
  try {
    const list = fromChats(await waCall<unknown>("/chats"));
    if (list) return list;
  } catch (reason) {
    if (
      !(reason instanceof LeadsError) ||
      (reason.status !== 404 && reason.status !== 405)
    )
      throw reason;
  }
  return readInboxes();
}

/**
 * The same from the WhatsApp and the Messenger/Instagram inboxes. A channel
 * the organisation hasn't connected simply adds nothing; only when nothing
 * answers at all is it an error.
 */
async function readInboxes(): Promise<ChatList> {
  const [social, whatsapp] = await Promise.allSettled([
    waCall<unknown>("/social/inbox"),
    waCall<unknown>("/whatsapp/inbox"),
  ]);
  if (social.status === "rejected" && whatsapp.status === "rejected") {
    const reason = social.reason as unknown;
    throw reason instanceof LeadsError
      ? reason
      : new LeadsError("Your chats didn't load. Try again.", 0);
  }
  const rows = (result: PromiseSettledResult<unknown>) =>
    result.status === "fulfilled" && Array.isArray(result.value)
      ? (result.value as unknown[]).filter(isRow)
      : [];
  const socialRows = rows(social) as (SocialInboxThread & Extra)[];
  const waRows = rows(whatsapp) as (WaThread & Extra)[];
  const threads = [
    ...waRows.map((row, index) => toThread(row, "whatsapp", index)),
    ...socialRows.map((row, index) =>
      toThread(
        row,
        row.channel === "instagram" ? "instagram" : "messenger",
        index,
      ),
    ),
  ];
  // Two rows can share a key only when the server leaves out the account;
  // the newest stays.
  const seen = new Set<string>();
  const unique = sortThreads(threads).filter((thread) => {
    if (seen.has(thread.key)) return false;
    seen.add(thread.key);
    return true;
  });
  return {
    threads: unique,
    owners: [...socialRows, ...waRows].some((row) => "ownerId" in row),
  };
}

/** The organisation's first-response target, when it has one. */
export async function readSla(): Promise<Sla | null> {
  try {
    return slaOf(await waCall<unknown>("/sla"));
  } catch {
    return null;
  }
}

/* ---------- One conversation ---------- */

export type ChatMessage = {
  id: string;
  direction: "in" | "out";
  kind: string;
  text: string | null;
  template?: string | null;
  status: string;
  error?: string | null;
  auto?: string | null;
  humanAgent?: boolean;
  at: string;
  by?: string | null;
};

export type ChatDetail = {
  channel: ChatChannel;
  place: string;
  accountId: string | null;
  messages: ChatMessage[];
  windowOpen: boolean;
  windowClosesAt: string | null;
  /** Meta's Human Agent tag: a person may still answer within 7 days. */
  humanAgent: boolean;
  /** WhatsApp only: the approved templates and the person's opt-in. */
  templates: WaTemplate[];
  optedIn: boolean;
  optInHow?: string | null;
  /** Other conversations with this lead on the same channel (another Page). */
  others: { accountId: string; place: string }[];
};

function fromSocial(
  chat: SocialConversation,
  channel: ChatChannel,
  accountId?: string | null,
): ChatDetail | null {
  const mine = (chat.threads ?? []).filter(
    (thread) => thread.channel === channel,
  );
  const pick: SocialThread | undefined =
    mine.find((thread) => accountId && thread.accountId === accountId) ??
    mine[0];
  if (!pick) return null;
  return {
    channel,
    place: pick.place,
    accountId: pick.accountId,
    messages: pick.messages.map((message) => ({
      id: message.id,
      direction: message.direction,
      kind: message.kind,
      text: message.text ?? null,
      status: message.status,
      error: message.error ?? null,
      auto: message.auto ?? null,
      humanAgent: Boolean(message.humanAgent),
      at: message.at,
      by: message.by ?? null,
    })),
    windowOpen: pick.windowOpen,
    windowClosesAt: pick.windowClosesAt ?? null,
    humanAgent: pick.humanAgent,
    templates: [],
    optedIn: false,
    others: mine
      .filter((thread) => thread !== pick)
      .map((thread) => ({ accountId: thread.accountId, place: thread.place })),
  };
}

function fromWhatsApp(chat: WaConversation): ChatDetail {
  const number = chat.numbers?.[0];
  return {
    channel: "whatsapp",
    place: number
      ? `WhatsApp · ${number.verifiedName || number.displayNumber}`
      : "WhatsApp",
    accountId: number?.id ?? null,
    messages: (chat.messages ?? []).map((message) => ({
      id: message.id,
      direction: message.direction,
      kind: message.kind,
      text: message.text ?? null,
      template: message.template ?? null,
      status: message.status,
      error: message.error ?? null,
      auto: message.auto ?? null,
      at: message.at,
      by: message.by ?? null,
    })),
    windowOpen: chat.windowOpen,
    windowClosesAt: chat.windowClosesAt ?? null,
    humanAgent: false,
    templates: (chat.templates ?? []).filter(
      (template) => template.status === "APPROVED",
    ),
    optedIn: Boolean(chat.optedIn),
    optInHow: chat.optInHow ?? null,
    others: [],
  };
}

/** One lead's conversation on one channel, oldest message first. */
export async function readThread(
  thread: Pick<ChatThread, "channel" | "leadId" | "accountId">,
  signal?: AbortSignal,
): Promise<ChatDetail | null> {
  if (!thread.leadId) return null;
  const lead = encodeURIComponent(thread.leadId);
  if (thread.channel === "whatsapp") {
    const chat = await waCall<WaConversation>(`/leads/${lead}/whatsapp`, {
      signal,
    });
    return Array.isArray(chat?.messages) ? fromWhatsApp(chat) : null;
  }
  const chat = await waCall<SocialConversation>(`/leads/${lead}/social`, {
    signal,
  });
  return Array.isArray(chat?.threads)
    ? fromSocial(chat, thread.channel, thread.accountId)
    : null;
}

/**
 * Send a written reply. Meta's refusal comes back as the newest message with
 * status "failed" and its reason, so the bubble can say why.
 */
export async function sendText(
  leadId: string,
  detail: ChatDetail,
  text: string,
): Promise<ChatDetail | null> {
  if (detail.channel === "whatsapp")
    return fromWhatsApp(await sendWhatsApp(leadId, { text }));
  const next = await sendSocial(leadId, {
    channel: detail.channel,
    accountId: detail.accountId ?? "",
    text,
    humanAgent: !detail.windowOpen && detail.humanAgent,
  });
  return fromSocial(next, detail.channel, detail.accountId);
}

/** Send an approved WhatsApp template, its parts filled in. */
export async function sendTemplate(
  leadId: string,
  template: Pick<WaTemplate, "name" | "language">,
  values: string[],
): Promise<ChatDetail> {
  return fromWhatsApp(
    await sendWhatsApp(leadId, {
      template: template.name,
      language: template.language,
      values,
    }),
  );
}

/** They said yes to WhatsApp: note how, so a template may go to them. */
export async function recordOptIn(
  leadId: string,
  how: string,
): Promise<ChatDetail> {
  return fromWhatsApp(
    await waCall<WaConversation>(
      `/leads/${encodeURIComponent(leadId)}/whatsapp/opt-in`,
      {
        method: "POST",
        body: JSON.stringify({
          commandId: crypto.randomUUID(),
          agreed: true,
          how: how.trim() || "Told the seller",
        }),
      },
    ),
  );
}

/** Who can write now, and why not when they can't, in plain words. */
export function composerState(
  detail: ChatDetail,
  now: Date = new Date(),
): { canWrite: boolean; line: string; tone: "neutral" | "warn" } {
  if (detail.windowOpen) {
    const closes = detail.windowClosesAt
      ? new Date(detail.windowClosesAt).getTime() - now.getTime()
      : null;
    if (closes !== null && closes < 60 * 60 * 1000) {
      const minutes = Math.max(1, Math.round(closes / 60000));
      return {
        canWrite: true,
        line: `Reply within ${minutes} min, while their last message is under 24 hours old.`,
        tone: "warn",
      };
    }
    return { canWrite: true, line: "", tone: "neutral" };
  }
  if (detail.channel === "whatsapp")
    return {
      canWrite: false,
      line: detail.optedIn
        ? "Their last message is more than 24 hours old, so WhatsApp only lets you send an approved template until they write again."
        : "Their last message is more than 24 hours old. WhatsApp lets you send a template only to someone who agreed to hear from you: when they say yes, note how below.",
      tone: "warn",
    };
  if (detail.humanAgent)
    return {
      canWrite: true,
      line: "Their last message is more than 24 hours old. You can still answer yourself within 7 days.",
      tone: "warn",
    };
  return {
    canWrite: false,
    line: `Their last message is more than 24 hours old, so ${CHANNEL_LABEL[detail.channel]} won't deliver a reply. When they write again, you can answer here.`,
    tone: "warn",
  };
}

/* ---------- Reading the list ---------- */

export type Scope = "all" | "mine" | "unassigned";

export type ChatFilter = {
  scope: Scope;
  channel: ChatChannel | "all";
  waitingOnly: boolean;
  search: string;
};

export const NO_FILTER: ChatFilter = {
  scope: "all",
  channel: "all",
  waitingOnly: false,
  search: "",
};

export function filterThreads(
  threads: ChatThread[],
  filter: ChatFilter,
  me: string | null,
): ChatThread[] {
  const words = filter.search.trim().toLowerCase();
  return threads.filter(
    (thread) =>
      (filter.channel === "all" || thread.channel === filter.channel) &&
      (!filter.waitingOnly || thread.waiting) &&
      (filter.scope === "all" ||
        (filter.scope === "mine" ? thread.ownerId === me : !thread.ownerId)) &&
      (!words || thread.leadName.toLowerCase().includes(words)),
  );
}

/* ---------- Seen marks (this browser only, ids and times) ---------- */

const SEEN_LIMIT = 300;
const seenKey = (personId: string) =>
  `sx.chats.seen:${encodeURIComponent(personId)}`;

export type SeenMarks = Record<string, string>;

export function readSeen(personId: string): SeenMarks {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(seenKey(personId)) ?? "{}",
    );
    if (!value || typeof value !== "object") return {};
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    return {};
  }
}

/** Remember that this person has seen the chat up to its newest message. */
export function markSeen(
  personId: string,
  marks: SeenMarks,
  thread: Pick<ChatThread, "key" | "lastAt">,
): SeenMarks {
  if (marks[thread.key] && marks[thread.key] >= thread.lastAt) return marks;
  const next = Object.fromEntries(
    Object.entries({ ...marks, [thread.key]: thread.lastAt })
      .sort((a, b) => (a[1] < b[1] ? 1 : -1))
      .slice(0, SEEN_LIMIT),
  );
  try {
    localStorage.setItem(seenKey(personId), JSON.stringify(next));
  } catch {
    /* storage off: the dot simply comes back next time */
  }
  return next;
}

/** Unread: they wrote after this person last looked (server marks win when sent). */
export function isUnread(thread: ChatThread, marks: SeenMarks): boolean {
  if (typeof thread.unread === "number") return thread.unread > 0;
  if (!thread.waiting) return false;
  const seen = marks[thread.key];
  return !seen || seen < thread.lastAt;
}

/* ---------- Words and times ---------- */

/** "2 min", "1 h 5 min", "3 d": how long they have waited for an answer. */
export function waitedFor(since: string, now: Date = new Date()): string {
  const minutes = Math.max(
    0,
    Math.floor((now.getTime() - new Date(since).getTime()) / 60000),
  );
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24)
    return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

/** Calm, then amber at half the target, then red once it has passed. */
export function waitTone(
  since: string,
  sla: Sla | null,
  now: Date = new Date(),
): "neutral" | "warn" | "bad" {
  const target = sla?.on ? sla.minutes : 30;
  const minutes = (now.getTime() - new Date(since).getTime()) / 60000;
  if (minutes >= target) return "bad";
  if (minutes >= target / 2) return "warn";
  return "neutral";
}

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** The list's time: 14:05 today, Yesterday, Mon this week, else 12 Oct. */
export function listTime(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  if (sameDay(at, now))
    return at.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(at, yesterday)) return "Yesterday";
  if (now.getTime() - at.getTime() < 6 * 24 * 3600 * 1000)
    return at.toLocaleDateString(undefined, { weekday: "short" });
  return at.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** A bubble's time of day. */
export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** The day separator between messages: Today, Yesterday, Monday, 12 October. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  if (sameDay(at, now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(at, yesterday)) return "Yesterday";
  if (now.getTime() - at.getTime() < 6 * 24 * 3600 * 1000)
    return at.toLocaleDateString(undefined, { weekday: "long" });
  return at.toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Messages in day groups, each run of one side's messages marked for tails. */
export function dayGroups(
  messages: ChatMessage[],
  now: Date = new Date(),
): {
  day: string;
  items: { message: ChatMessage; first: boolean; last: boolean }[];
}[] {
  const groups: {
    day: string;
    items: { message: ChatMessage; first: boolean; last: boolean }[];
  }[] = [];
  const RUN_MS = 5 * 60 * 1000;
  messages.forEach((message, index) => {
    const day = dayLabel(message.at, now);
    let group = groups[groups.length - 1];
    if (!group || group.day !== day) {
      group = { day, items: [] };
      groups.push(group);
    }
    const before = messages[index - 1];
    const after = messages[index + 1];
    const joins = (a?: ChatMessage, b?: ChatMessage) =>
      !!a &&
      !!b &&
      a.direction === b.direction &&
      dayLabel(a.at, now) === dayLabel(b.at, now) &&
      Math.abs(new Date(b.at).getTime() - new Date(a.at).getTime()) <= RUN_MS;
    group.items.push({
      message,
      first: !joins(before, message),
      last: !joins(message, after),
    });
  });
  return groups;
}

const ATTACHMENTS: Record<string, string> = {
  image: "Photo",
  video: "Video",
  audio: "Voice note",
  document: "Document",
  file: "File",
  sticker: "Sticker",
  location: "Location",
  share: "Shared post",
  story_reply: "Replied to your story",
  story_mention: "Mentioned you in their story",
  reaction: "Reaction",
  contacts: "Contact card",
};

/** What a message without words is, in a word or two. */
export function attachmentLabel(kind: string): string | null {
  if (kind === "text" || kind === "comment" || kind === "template") return null;
  return ATTACHMENTS[kind] ?? "Something this app can't show";
}

/** The list's last line: their words or what they sent; ours start "You:". */
export function previewLine(thread: ChatThread): string {
  const words =
    thread.lastText ||
    (thread.lastKind ? attachmentLabel(thread.lastKind) : null) ||
    "A photo, file or sticker";
  return thread.lastDirection === "out" ? `You: ${words}` : words;
}

/** The place under the name, e.g. "Messenger · Fictional Homes". */
export function placeLine(thread: ChatThread): string {
  return thread.place || CHANNEL_LABEL[thread.channel];
}
