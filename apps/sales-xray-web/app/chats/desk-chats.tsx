"use client";

/**
 * Chats on the lead desk: one card for WhatsApp, Messenger and Instagram, the
 * chats waiting for a reply first. Each row opens that chat in Chats, the one
 * place for conversations (owner, 20 Oct: "not everything confused on one
 * panel"). Shows nothing until someone has written.
 */

import { ChevronRight, Hourglass, MessagesSquare } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { publishChats } from "./chats-badge";
import { ChatAvatar } from "./channel-mark";
import {
  chatHref,
  CHATS_PATH,
  listTime,
  previewLine,
  readChats,
  waitedFor,
  waitTone,
  type ChatThread,
} from "./chats-client";
import styles from "./chats.module.css";

const SHOWN = 4;
const EVERY_MS = 60 * 1000;

export function DeskChats() {
  const [threads, setThreads] = useState<ChatThread[] | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let live = true;
    const load = () =>
      readChats()
        .then((list) => {
          if (!live) return;
          setThreads(list.threads);
          setNow(new Date());
          publishChats(list.threads);
        })
        .catch(() => live && setThreads([]));
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, EVERY_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const open = (threads ?? []).filter((thread) => thread.leadId);
  if (!open.length) return null;
  const waiting = open.filter((thread) => thread.waiting);
  const shown = (waiting.length ? waiting : open).slice(0, SHOWN);
  return (
    <section className={styles.deskChats} aria-label="Chats">
      <header>
        <MessagesSquare size={16} aria-hidden="true" />
        <strong>Chats</strong>
        {waiting.length ? (
          <span className={styles.deskWaiting}>
            {waiting.length} waiting for a reply
          </span>
        ) : null}
        <Link className={styles.deskOpen} href={CHATS_PATH} prefetch={false}>
          Open Chats
          <ChevronRight size={14} aria-hidden="true" />
        </Link>
      </header>
      <ul>
        {shown.map((thread) => (
          <li key={thread.key}>
            <Link
              className={styles.deskRow}
              href={chatHref(thread.channel, thread.leadId!, thread.accountId)}
              prefetch={false}
            >
              <ChatAvatar
                name={thread.leadName}
                channel={thread.channel}
                size={32}
              />
              <span>
                <strong>{thread.leadName}</strong>
                <small>{previewLine(thread)}</small>
              </span>
              {thread.waiting ? (
                <span
                  className={styles.wait}
                  data-tone={waitTone(
                    thread.waitingSince ?? thread.lastAt,
                    null,
                    now,
                  )}
                >
                  <Hourglass size={11} aria-hidden="true" />
                  {waitedFor(thread.waitingSince ?? thread.lastAt, now)}
                </span>
              ) : (
                <time dateTime={thread.lastAt}>
                  {listTime(thread.lastAt, now)}
                </time>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
