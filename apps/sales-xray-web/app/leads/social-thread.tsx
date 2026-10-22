"use client";

/**
 * One lead's Messenger and Instagram conversations in the lead sheet, each with a
 * reply box that follows Meta's rules: replies for 24 hours after the person's
 * last message; after that, when the organisation has it on, the seller may still
 * answer personally within 7 days (Meta's Human Agent tag).
 */

import { AtSign, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { chatHref } from "../chats/chats-client";
import { Button } from "../ui/kit";
import { AiHelp, useLeadAi } from "./ai-replies";
import type { AiLeadState } from "./ai-replies-client";
import { ago, LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import {
  CHANNEL_NAMES,
  sendSocial,
  socialText,
  socialWindowLine,
  type SocialConversation,
  type SocialMessage,
  type SocialThread as Thread,
} from "./social-client";
import { waCall } from "./whatsapp-client";

const STATUS: Record<string, string> = {
  queued: "Sending",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Not sent",
};
// The drawer keeps the latest few; the whole chat lives in Chats (owner, 20 Oct).
const RECENT = 3;

const AUTO: Record<string, string> = {
  first_reply: "Automatic first reply",
  out_of_hours: "Automatic after-hours reply",
  comment_reply: "Private reply to their comment",
};

function Bubble({ message }: { message: SocialMessage }) {
  return (
    <li className={styles.waBubble} data-direction={message.direction}>
      <p>{socialText(message)}</p>
      <small>
        {ago(message.at)}
        {message.direction === "out"
          ? ` · ${message.auto ? (AUTO[message.auto] ?? "Automatic") : (message.by ?? "Sent from Meta")} · ${STATUS[message.status] ?? message.status}`
          : null}
        {message.humanAgent ? " · answered personally" : null}
        {message.error ? ` · ${message.error}` : null}
      </small>
    </li>
  );
}

function Composer({
  leadId,
  ai,
  thread,
  onSent,
}: {
  leadId: string;
  ai: AiLeadState | null;
  thread: Thread;
  onSent: (next: SocialConversation) => void;
}) {
  const [text, setText] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const can = thread.windowOpen || thread.humanAgent;
  const send = async () => {
    setBusy(true);
    setNote(null);
    try {
      const next = await sendSocial(leadId, {
        channel: thread.channel,
        accountId: thread.accountId,
        text: text.trim(),
        humanAgent: !thread.windowOpen && thread.humanAgent,
      });
      const same = next.threads.find(
        (t) => t.accountId === thread.accountId && t.channel === thread.channel,
      );
      const last = same?.messages[same.messages.length - 1];
      if (last?.status === "failed")
        setNote(last.error ?? "Meta didn't take it.");
      else setText("");
      onSent(next);
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <p className={styles.hint}>{socialWindowLine(thread)}</p>
      {can ? (
        <AiHelp
          ai={ai}
          leadId={leadId}
          channel={thread.channel}
          accountId={thread.accountId}
          onDraft={setText}
        />
      ) : null}
      {can ? (
        <div className={styles.waCompose}>
          <textarea
            aria-label={`${CHANNEL_NAMES[thread.channel]} message`}
            value={text}
            maxLength={thread.channel === "instagram" ? 1000 : 2000}
            rows={2}
            placeholder="Write a reply"
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            variant="primary"
            disabled={busy || !text.trim()}
            onClick={send}
          >
            Send
          </Button>
        </div>
      ) : null}
      {note ? (
        <p className={styles.error} role="alert">
          {note}
        </p>
      ) : null}
    </>
  );
}

export function SocialThread({
  leadId,
  canSend,
  onChanged,
  shared,
}: {
  leadId: string;
  canSend: boolean;
  onChanged?: () => void;
  /** The lead page's own read of this chat (shared with its timeline); without
      it, this reads the chat itself. `chat` undefined: still reading. */
  shared?: { chat: SocialConversation | null | undefined };
}) {
  // What this section read or sent, for the lead it was for.
  const [own, setOwn] = useState<{
    leadId: string;
    chat: SocialConversation | null;
  } | null>(null);
  const setChat = (next: SocialConversation | null) =>
    setOwn({ leadId, chat: next });
  const reads = !shared;
  const chat =
    own?.leadId === leadId ? own.chat : shared ? (shared.chat ?? null) : null;
  const ai = useLeadAi(leadId);

  useEffect(() => {
    if (!reads) return;
    let live = true;
    waCall<SocialConversation>(`/leads/${leadId}/social`)
      .then(
        (data) => live && setChat(Array.isArray(data?.threads) ? data : null),
      )
      .catch(() => live && setChat(null));
    return () => {
      live = false;
    };
    // setChat only writes this lead's own state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadId, reads]);

  if (!chat?.configured || !chat.threads.length) return null;

  return (
    <>
      {chat.threads.map((thread) => {
        const Icon = thread.channel === "instagram" ? AtSign : MessageSquare;
        const shown = thread.messages.slice(-RECENT);
        const earlier = thread.messages.length - shown.length;
        return (
          <section
            key={`${thread.accountId}|${thread.channel}|${thread.messages[0]?.id}`}
            className={styles.waThread}
            aria-label={CHANNEL_NAMES[thread.channel]}
          >
            <div className={styles.waHead}>
              <Icon size={16} aria-hidden="true" />
              <h3 className={styles.stepLabel}>{thread.place}</h3>
              <Link
                className={styles.openChats}
                href={chatHref(thread.channel, leadId, thread.accountId)}
                prefetch={false}
              >
                Open in Chats
              </Link>
            </div>
            {earlier ? (
              <p className={styles.hint}>
                {earlier} earlier message{earlier === 1 ? "" : "s"} in Chats
              </p>
            ) : null}
            <ol className={styles.waMessages}>
              {shown.map((message) => (
                <Bubble key={message.id} message={message} />
              ))}
            </ol>
            {canSend ? (
              <Composer
                ai={ai}
                leadId={leadId}
                thread={thread}
                onSent={(next) => {
                  setChat(next);
                  onChanged?.();
                }}
              />
            ) : null}
          </section>
        );
      })}
    </>
  );
}
