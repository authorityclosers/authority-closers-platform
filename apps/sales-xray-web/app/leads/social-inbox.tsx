"use client";

/**
 * Messenger and Instagram on the desk: conversations waiting for a reply come
 * first. A seller sees their own leads'; a manager sees the team's. Shows nothing
 * until the organisation has connected a Page and someone has written.
 */

import { MessageSquare } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "../ui/kit";
import { ago } from "./leads-client";
import styles from "./leads.module.css";
import { CHANNEL_NAMES, type SocialInboxThread } from "./social-client";
import { waCall } from "./whatsapp-client";

export function SocialInbox({ onOpen }: { onOpen: (leadId: string) => void }) {
  const [threads, setThreads] = useState<SocialInboxThread[] | null>(null);

  useEffect(() => {
    let live = true;
    const load = () =>
      waCall<SocialInboxThread[]>("/social/inbox")
        .then((data) => live && setThreads(Array.isArray(data) ? data : []))
        .catch(() => live && setThreads([]));
    void load();
    const timer = setInterval(() => void load(), 60000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  if (!threads?.length) return null;
  const waiting = threads.filter((thread) => thread.waiting).length;
  return (
    <section className={styles.waInbox} aria-label="Messenger and Instagram">
      <div className={styles.waHead}>
        <MessageSquare size={16} aria-hidden="true" />
        <strong>Messenger &amp; Instagram</strong>
        {waiting ? (
          <Badge tone="warn">{waiting} waiting for a reply</Badge>
        ) : null}
      </div>
      <ul>
        {threads.slice(0, 8).map((thread, index) => (
          <li
            key={`${thread.leadId ?? thread.leadName}|${thread.channel}|${index}`}
          >
            <button
              type="button"
              disabled={!thread.leadId}
              onClick={() => thread.leadId && onOpen(thread.leadId)}
            >
              <span>
                <strong>{thread.leadName}</strong>
                <small>
                  {CHANNEL_NAMES[thread.channel]} ·{" "}
                  {thread.lastText ?? "A photo or a file"}
                </small>
              </span>
              <small>
                {thread.waiting ? "Waiting · " : ""}
                {ago(thread.lastAt)}
              </small>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
