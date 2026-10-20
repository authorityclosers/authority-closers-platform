"use client";

/**
 * The Chats list: one row per conversation, waiting ones first. Each row has
 * the channel on the avatar, the name, the newest line, its time, an unread
 * dot, how long they have waited for an answer and, for managers, the seller.
 */

import { Hourglass, Inbox, Search, UserRound } from "lucide-react";

import { ChatAvatar } from "./channel-mark";
import {
  CHANNEL_LABEL,
  CHANNELS,
  filterThreads,
  isUnread,
  listTime,
  placeLine,
  previewLine,
  waitedFor,
  waitTone,
  type ChatChannel,
  type ChatFilter,
  type ChatThread,
  type Scope,
  type SeenMarks,
  type Sla,
} from "./chats-client";
import styles from "./chats.module.css";
import { Ticks } from "./ticks";

const SCOPES: { key: Scope; label: string }[] = [
  { key: "mine", label: "Mine" },
  { key: "unassigned", label: "Unassigned" },
  { key: "all", label: "All" },
];

// The list's skeleton lives in the light chats-skeleton.tsx (root loading).
export { ThreadListSkeleton } from "./chats-skeleton";

export function ThreadFilters({
  filter,
  onChange,
  showScopes,
  counts,
  channels,
}: {
  filter: ChatFilter;
  onChange: (next: ChatFilter) => void;
  /** Managers with owners known: Mine, Unassigned, All. */
  showScopes: boolean;
  counts: { waiting: number };
  /** The channels this organisation's chats use (a filter chip each). */
  channels: ChatChannel[];
}) {
  const shown = CHANNELS.filter((channel) => channels.includes(channel));
  return (
    <div className={styles.filters}>
      <label className={styles.search}>
        <Search size={14} aria-hidden="true" />
        <input
          type="search"
          value={filter.search}
          placeholder="Search names"
          aria-label="Search chats by name"
          onChange={(event) =>
            onChange({ ...filter, search: event.target.value })
          }
        />
      </label>
      {showScopes ? (
        <div className={styles.scopes} role="group" aria-label="Whose chats">
          {SCOPES.map((scope) => (
            <button
              key={scope.key}
              type="button"
              aria-pressed={filter.scope === scope.key}
              onClick={() => onChange({ ...filter, scope: scope.key })}
            >
              {scope.label}
            </button>
          ))}
        </div>
      ) : null}
      <div className={styles.chips} role="group" aria-label="Show">
        <button
          type="button"
          className={styles.chip}
          aria-pressed={filter.waitingOnly}
          onClick={() =>
            onChange({ ...filter, waitingOnly: !filter.waitingOnly })
          }
        >
          <Hourglass size={12} aria-hidden="true" />
          Waiting{counts.waiting ? ` ${counts.waiting}` : ""}
        </button>
        {shown.length > 1
          ? (["all", ...shown] as const).map((channel) => (
              <button
                key={channel}
                type="button"
                className={styles.chip}
                data-channel={channel}
                aria-pressed={filter.channel === channel}
                onClick={() => onChange({ ...filter, channel })}
              >
                {channel === "all" ? "All" : CHANNEL_LABEL[channel]}
              </button>
            ))
          : null}
      </div>
    </div>
  );
}

function ThreadRow({
  thread,
  active,
  unread,
  sla,
  showOwner,
  now,
  onOpen,
}: {
  thread: ChatThread;
  active: boolean;
  unread: boolean;
  sla: Sla | null;
  showOwner: boolean;
  now: Date;
  onOpen: (thread: ChatThread) => void;
}) {
  const since = thread.waiting ? (thread.waitingSince ?? thread.lastAt) : null;
  const gone = !thread.leadId;
  return (
    <li>
      <button
        type="button"
        className={styles.row}
        data-active={active || undefined}
        data-unread={unread || undefined}
        aria-current={active ? "true" : undefined}
        disabled={gone}
        onClick={() => onOpen(thread)}
      >
        <ChatAvatar name={thread.leadName} channel={thread.channel} />
        <span className={styles.rowMain}>
          <span className={styles.rowTop}>
            <strong>{thread.leadName}</strong>
            <time dateTime={thread.lastAt}>{listTime(thread.lastAt, now)}</time>
          </span>
          <span className={styles.rowText}>
            {thread.lastDirection === "out" ? (
              <Ticks status={thread.lastStatus ?? "sent"} size={14} />
            ) : null}
            <span>{previewLine(thread)}</span>
            {unread ? (
              <span className={styles.unreadDot}>
                <span className={styles.srOnly}>Unread</span>
              </span>
            ) : null}
          </span>
          <span className={styles.rowMeta}>
            <span className={styles.rowPlace}>
              {gone ? "Lead removed" : placeLine(thread)}
            </span>
            {showOwner ? (
              <span
                className={styles.owner}
                data-none={!thread.ownerId || undefined}
              >
                <UserRound size={11} aria-hidden="true" />
                {thread.ownerName ?? "Unassigned"}
              </span>
            ) : null}
            {since ? (
              <span
                className={styles.wait}
                data-tone={waitTone(since, sla, now)}
                title="Waiting for a reply"
              >
                <Hourglass size={11} aria-hidden="true" />
                {waitedFor(since, now)}
              </span>
            ) : null}
          </span>
        </span>
      </button>
    </li>
  );
}

export function ThreadList({
  threads,
  filter,
  me,
  marks,
  sla,
  activeKey,
  showOwner,
  now,
  onOpen,
  onClear,
}: {
  threads: ChatThread[];
  filter: ChatFilter;
  me: string | null;
  marks: SeenMarks;
  sla: Sla | null;
  activeKey: string | null;
  showOwner: boolean;
  now: Date;
  onOpen: (thread: ChatThread) => void;
  onClear: () => void;
}) {
  const shown = filterThreads(threads, filter, me);
  if (!threads.length)
    return (
      <div className={styles.listEmpty}>
        <span className={styles.emptyMark} aria-hidden="true">
          <Inbox size={18} />
        </span>
        <p className={styles.emptyTitle}>No chats yet</p>
        <p className={styles.emptyText}>
          When a lead writes on WhatsApp, Messenger or Instagram, the chat shows
          here.
        </p>
      </div>
    );
  if (!shown.length)
    return (
      <div className={styles.listEmpty}>
        <p className={styles.emptyTitle}>Nothing matches</p>
        <button type="button" className={styles.linkButton} onClick={onClear}>
          Show all chats
        </button>
      </div>
    );
  return (
    <ul className={styles.listBody} aria-label="Chats">
      {shown.map((thread) => (
        <ThreadRow
          key={thread.key}
          thread={thread}
          active={thread.key === activeKey}
          unread={thread.key !== activeKey && isUnread(thread, marks)}
          sla={sla}
          showOwner={showOwner}
          now={now}
          onOpen={onOpen}
        />
      ))}
    </ul>
  );
}
