"use client";

/**
 * Notes (owner, 24 Oct 2026: "she has to see notes ... she just can't"; v0.89):
 * everything written on the seller's leads, newest first, a note on its own or
 * the remark saved with a call's outcome, with who wrote it and when. A few
 * words find the notes that say them. A tap opens the lead at that note.
 */

import { NotebookPen, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Button, Empty, Skeleton } from "../ui/kit";
import { LeadsError, ago, readNotes, type ActivityItem } from "./leads-client";
import styles from "./notes.module.css";

type Loaded = {
  q: string;
  items: ActivityItem[];
  next: string | null;
};

/** The words looked for: two letters at least, else none. */
export function notesQuery(text: string): string {
  const words = text.trim();
  return words.length >= 2 ? words : "";
}

export function NotesView({
  onOpen,
  now = () => new Date(),
}: {
  /** Open the lead at the note written at this time. */
  onOpen: (leadId: string, at: string) => void;
  now?: () => Date;
}) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [older, setOlder] = useState(false);

  // A short pause after typing, so each letter is not a read.
  useEffect(() => {
    const timer = window.setTimeout(() => setQ(notesQuery(text)), 300);
    return () => window.clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    const controller = new AbortController();
    readNotes(q || null, null, controller.signal).then(
      (page) => setLoaded({ q, items: page.items, next: page.next_before }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        notify({
          id: "notes-failed",
          tone: "error",
          title: "Notes didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [q]);

  const shown = loaded && loaded.q === q ? loaded : null;

  const showOlder = async () => {
    if (!shown?.next) return;
    setOlder(true);
    try {
      const page = await readNotes(q || null, shown.next);
      setLoaded((value) =>
        value && value.q === q
          ? {
              ...value,
              items: [...value.items, ...page.items],
              next: page.next_before,
            }
          : value,
      );
    } catch (reason) {
      notify({
        id: "notes-older-failed",
        tone: "error",
        title: "Older notes didn't load",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
    } finally {
      setOlder(false);
    }
  };

  const items = shown?.items ?? [];
  return (
    <section className={styles.notes} aria-label="Notes">
      <label className={styles.find}>
        <Search size={16} aria-hidden="true" />
        <input
          type="search"
          value={text}
          placeholder="Search notes"
          aria-label="Search notes"
          maxLength={80}
          enterKeyHint="search"
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      {!shown ? (
        <ol className={styles.list} aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <li key={index} className={styles.skeleton}>
              <Skeleton width={32} height={32} />
              <Skeleton width="60%" height={14} />
            </li>
          ))}
        </ol>
      ) : items.length === 0 ? (
        <Empty
          icon={NotebookPen}
          title={q ? "No notes say that" : "No notes yet"}
          text={
            q
              ? "Try other words, or a lead's name."
              : "Notes you write on a lead, and after a call, show here, newest first."
          }
        />
      ) : (
        <ol className={styles.list} aria-label="Notes, newest first">
          {items.map((item) => (
            <li key={item.event_id}>
              <button
                type="button"
                className={styles.row}
                data-lead-row=""
                onClick={() => onOpen(item.lead_id, item.event.at)}
              >
                <span
                  className={styles.icon}
                  data-kind="note"
                  aria-hidden="true"
                >
                  <NotebookPen size={16} />
                </span>
                <span className={styles.text}>
                  <strong>{displayName(item.lead_name)}</strong>
                  <small>{item.event.note}</small>
                  <span>
                    {[
                      item.event.actor_name
                        ? displayName(item.event.actor_name)
                        : null,
                      item.stage_label,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <time dateTime={item.event.at}>
                  {ago(item.event.at, now())}
                </time>
              </button>
            </li>
          ))}
        </ol>
      )}
      {shown?.next ? (
        <Button variant="ghost" onClick={showOlder} disabled={older}>
          {older ? "Loading…" : "Show older"}
        </Button>
      ) : null}
    </section>
  );
}
