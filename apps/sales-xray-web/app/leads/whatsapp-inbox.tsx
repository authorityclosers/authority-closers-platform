"use client";

/**
 * WhatsApp on the desk: conversations waiting for a reply come first. A seller
 * sees their own leads'; a manager sees the team's. Shows nothing until the
 * organisation has connected a number and someone has written.
 */

import { MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "../ui/kit";
import { ago } from "./leads-client";
import styles from "./leads.module.css";
import { waCall, type WaThread } from "./whatsapp-client";

export function WhatsAppInbox({
  onOpen,
}: {
  onOpen: (leadId: string) => void;
}) {
  const [threads, setThreads] = useState<WaThread[] | null>(null);

  useEffect(() => {
    let live = true;
    const load = () =>
      waCall<WaThread[]>("/whatsapp/inbox")
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
    <section className={styles.waInbox} aria-label="WhatsApp">
      <div className={styles.waHead}>
        <MessageCircle size={16} aria-hidden="true" />
        <strong>WhatsApp</strong>
        {waiting ? (
          <Badge tone="warn">{waiting} waiting for a reply</Badge>
        ) : null}
      </div>
      <ul>
        {threads.slice(0, 8).map((thread) => (
          <li key={`${thread.leadId ?? thread.leadName}`}>
            <button
              type="button"
              disabled={!thread.leadId}
              onClick={() => thread.leadId && onOpen(thread.leadId)}
            >
              <span>
                <strong>{thread.leadName}</strong>
                <small>{thread.lastText ?? "A file or a template"}</small>
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
