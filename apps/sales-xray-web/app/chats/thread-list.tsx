"use client";

/**
 * The Chats list: one row per conversation, waiting ones first. Each row has
 * the lead's name with capitals, the newest line, its time, how many of their
 * messages are unread, the app it is on (its mark and name), how long they
 * have waited for an answer and, for managers, the seller (owner, 22 Oct
 * 2026: "hard to tell which chat is which").
 */

import {
  ChevronDown,
  Hourglass,
  Inbox,
  ListFilter,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { useRowKeys } from "../ui/row-keys";
import { ChannelMark, ChatAvatar } from "./channel-mark";
import {
  CHANNEL_LABEL,
  CHANNELS,
  filterThreads,
  isUnread,
  listTime,
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
  { key: "all", label: "Everyone" },
  { key: "mine", label: "Mine" },
  { key: "unassigned", label: "Unassigned" },
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
  /** Managers with owners known: All, Mine, Unassigned. */
  showScopes: boolean;
  counts: { waiting: number };
  /** The channels this organisation's chats use (a choice each). */
  channels: ChatChannel[];
}) {
  // Owner, 22 Oct 2026: one row of small controls, then the chats.
  const [searching, setSearching] = useState(false);
  const shown = CHANNELS.filter((channel) => channels.includes(channel));
  if (searching || filter.search)
    return (
      <div className={styles.filters}>
        <label className={styles.search}>
          <ListFilter size={14} aria-hidden="true" />
          <input
            type="search"
            value={filter.search}
            placeholder="Filter by name"
            aria-label="Filter chats by name"
            autoFocus={!filter.search}
            onChange={(event) =>
              onChange({ ...filter, search: event.target.value })
            }
          />
          <button
            type="button"
            className={styles.searchClose}
            aria-label="Clear the name filter"
            onClick={() => {
              onChange({ ...filter, search: "" });
              setSearching(false);
            }}
          >
            <X size={15} aria-hidden="true" />
          </button>
        </label>
      </div>
    );
  return (
    <div className={styles.filters}>
      <div className={styles.filterRow} role="group" aria-label="Show">
        {/* A filter in words, not a second magnifier: the header's search is
            the app's search (Liquid Glass, 22 Oct 2026). */}
        <button
          type="button"
          className={styles.chip}
          aria-label="Filter chats by name"
          onClick={() => setSearching(true)}
        >
          <ListFilter size={12} aria-hidden="true" />
          Name
        </button>
        {showScopes ? (
          <label className={styles.pickChip}>
            <UserRound size={13} aria-hidden="true" />
            <select
              aria-label="Whose chats"
              value={filter.scope}
              onChange={(event) =>
                onChange({ ...filter, scope: event.target.value as Scope })
              }
            >
              {SCOPES.map((scope) => (
                <option key={scope.key} value={scope.key}>
                  {scope.label}
                </option>
              ))}
            </select>
            <ChevronDown size={13} aria-hidden="true" />
          </label>
        ) : null}
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
        {shown.length > 1 ? (
          <label className={styles.pickChip}>
            {filter.channel === "all" ? null : (
              <ChannelMark channel={filter.channel} size={14} />
            )}
            <select
              aria-label="Channel"
              value={filter.channel}
              onChange={(event) =>
                onChange({
                  ...filter,
                  channel: event.target.value as ChatChannel | "all",
                })
              }
            >
              <option value="all">All channels</option>
              {shown.map((channel) => (
                <option key={channel} value={channel}>
                  {CHANNEL_LABEL[channel]}
                </option>
              ))}
            </select>
            <ChevronDown size={13} aria-hidden="true" />
          </label>
        ) : null}
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
  // Their messages since this person last read the chat, when the server
  // counts them; a dot when only this phone knows it is unread.
  const count = unread && thread.unread ? thread.unread : 0;
  return (
    <li>
      <button
        type="button"
        className={styles.row}
        data-active={active || undefined}
        data-unread={unread || undefined}
        aria-current={active ? "true" : undefined}
        data-row-key={gone ? undefined : thread.key}
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
            {count ? (
              <span className={styles.unreadCount}>
                {count > 99 ? "99+" : count}
                <span className={styles.srOnly}> unread</span>
              </span>
            ) : unread ? (
              <span className={styles.unreadDot}>
                <span className={styles.srOnly}>Unread</span>
              </span>
            ) : null}
          </span>
          <span className={styles.rowMeta}>
            {/* Owner, 22 Oct: which app each chat is on, in words. */}
            <span className={styles.channelTag} data-channel={thread.channel}>
              <ChannelMark channel={thread.channel} size={13} />
              {gone ? "Lead removed" : CHANNEL_LABEL[thread.channel]}
            </span>
            {showOwner ? (
              <span
                className={styles.owner}
                data-none={!thread.ownerId || undefined}
              >
                <UserRound size={11} aria-hidden="true" />
                <span className={styles.ownerName}>
                  {thread.ownerName ?? "Unassigned"}
                </span>
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
  canConnect = false,
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
  /** Owners and admins connect WhatsApp, Messenger and Instagram. */
  canConnect?: boolean;
}) {
  const shown = filterThreads(threads, filter, me);
  // Keys on a computer (J/K, Enter): the next chat without the mouse.
  const list = useRef<HTMLUListElement>(null);
  useRowKeys(list, {
    open: (key) => {
      const thread = shown.find((item) => item.key === key);
      if (thread) onOpen(thread);
    },
  });
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
        {canConnect ? (
          <Link href="/settings/apps" className={styles.linkButton}>
            Connect WhatsApp
          </Link>
        ) : (
          <Link href="/leads" className={styles.linkButton}>
            Message a lead
          </Link>
        )}
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
    <ul className={styles.listBody} aria-label="Chats" ref={list}>
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
