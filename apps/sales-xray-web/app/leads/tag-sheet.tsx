"use client";

/**
 * The Tag sheet (picks 17 Nov 2026: M2-A "Add tag" on the laptop bar, the
 * phone dock's Tag; migration 0165). Pick the workspace's tags or make one by
 * typing its name; the footer says what happens ("12 leads get Hot") and one
 * pill does it. Many leads go as one bulk job with Undo on its notice; one
 * lead (its page) saves the ticks it changed.
 */

import { Check, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import {
  changeLeadTags,
  commandId,
  createTag,
  readTags,
  type TagChip,
  type TagView,
} from "./leads-client";
import {
  failWords,
  leadsWord,
  selectionCount,
  tagLeads,
  type Selection,
} from "./manage-bar";
import { TagChips, TagDot } from "./tag-chips";
import styles from "./tag-sheet.module.css";

/** The workspace's tags, read once a sheet asks and kept for a minute. */
let tagsRead: { at: number; read: Promise<TagView[]> } | null = null;
const TAGS_FRESH_MS = 60_000;

export function readTagsSoon(): Promise<TagView[]> {
  if (tagsRead && Date.now() - tagsRead.at < TAGS_FRESH_MS)
    return tagsRead.read;
  const read = readTags().then((answer) => answer.tags);
  tagsRead = { at: Date.now(), read };
  read.catch(() => {
    tagsRead = null;
  });
  return read;
}

/** After a change, the next read asks the server again (counts moved). */
export function forgetTags() {
  tagsRead = null;
}

/** Said when a tag is renamed, recoloured or deleted (manage-tags.tsx). */
export const TAGS_CHANGED_EVENT = "sx-leads-tags-changed";

/** Tags a lead may carry, and tags one bulk change may add or take off. */
export const TAGS_AT_MOST = 10;

const joined = (names: string[]) =>
  names.length <= 1
    ? (names[0] ?? "")
    : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/** The footer's words for many leads ("12 leads get Hot"). */
export function tagPreview(
  count: number,
  names: string[],
  mode: "add" | "remove",
): string {
  if (!names.length) return "Choose a tag";
  const leads = leadsWord(count);
  return mode === "add"
    ? `${leads} ${count === 1 ? "gets" : "get"} ${joined(names)}`
    : `${joined(names)} ${names.length === 1 ? "comes" : "come"} off ${leads}`;
}

type Target =
  | { kind: "many"; selection: Selection }
  | { kind: "one"; leadId: string; tags: readonly TagChip[] };

export function TagSheet({
  open,
  target,
  onClose,
  onDone,
}: {
  open: boolean;
  target: Target;
  onClose: () => void;
  /** Done: for one lead, its tags now. */
  onDone: (tags?: TagChip[]) => void;
}) {
  const [tags, setTags] = useState<TagView[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"add" | "remove">("add");
  const start =
    target.kind === "many" ? [] : target.tags.map((tag) => tag.tag_id);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(start));
  const [busy, setBusy] = useState(false);
  const [making, setMaking] = useState(false);
  // One command per confirm: a retry never acts twice.
  const [command] = useState(commandId);

  useEffect(() => {
    if (!open || tags) return;
    let live = true;
    readTagsSoon().then(
      (next) => {
        if (live) setTags(next);
      },
      (reason: unknown) => {
        if (live) setFailed(failWords(reason, "Your tags didn't load."));
      },
    );
    return () => {
      live = false;
    };
  }, [open, tags]);

  const words = query.trim().replace(/\s+/g, " ");
  const shown = useMemo(() => {
    const all = tags ?? [];
    if (!words) return all;
    const needle = words.toLowerCase();
    return all.filter((tag) => tag.name.toLowerCase().includes(needle));
  }, [tags, words]);
  const exact = (tags ?? []).some(
    (tag) => tag.name.toLowerCase() === words.toLowerCase(),
  );
  // Up to 10 on a lead (and in one bulk change): the rest wait, and say why.
  const full = picked.size >= TAGS_AT_MOST;
  const toggle = (tagId: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(tagId)) next.delete(tagId);
      else if (next.size < TAGS_AT_MOST) next.add(tagId);
      return next;
    });

  const make = async () => {
    if (!words || making || full) return;
    setMaking(true);
    try {
      const made = await createTag(words.slice(0, 32));
      forgetTags();
      setTags((current) =>
        current?.some((tag) => tag.tag_id === made.tag_id)
          ? current
          : [...(current ?? []), made],
      );
      setPicked((current) => new Set(current).add(made.tag_id));
      setQuery("");
    } catch (reason) {
      notify({
        id: "tag-make",
        tone: "error",
        title: "That tag wasn't made",
        message: failWords(reason, "Check your connection and try again."),
      });
    } finally {
      setMaking(false);
    }
  };

  const names = (tags ?? [])
    .filter((tag) => picked.has(tag.tag_id))
    .map((tag) => tag.name);
  const many = target.kind === "many";
  const count = many ? selectionCount(target.selection) : 1;
  const added = many ? [] : [...picked].filter((id) => !start.includes(id));
  const removed = many ? [] : start.filter((id) => !picked.has(id));
  const changed = many ? picked.size > 0 : added.length + removed.length > 0;

  const go = async () => {
    if (!changed || busy) return;
    setBusy(true);
    try {
      if (target.kind === "many") {
        await tagLeads(
          { selection: target.selection, tags: [...picked], mode },
          command,
        );
        forgetTags();
        onDone();
      } else {
        const answer = await changeLeadTags(
          target.leadId,
          { add: added, remove: removed },
          command,
        );
        forgetTags();
        notify({
          id: "lead-tags",
          tone: "success",
          title: answer.tags.length
            ? `Tags: ${answer.tags.map((tag) => tag.name).join(", ")}`
            : "No tags on this lead now",
          timeout: 4000,
        });
        onDone(answer.tags);
      }
    } catch (reason) {
      notify({
        id: "bulk-job",
        tone: "error",
        title: "Those tags weren't changed",
        message: failWords(reason, "Check your connection and try again."),
      });
      setBusy(false);
    }
  };

  const pillWords = busy
    ? "Saving…"
    : many
      ? !picked.size
        ? "Choose a tag"
        : mode === "add"
          ? `Tag ${leadsWord(count)}`
          : `Take off ${leadsWord(count)}`
      : changed
        ? "Save tags"
        : "No change";

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={many ? `Tag ${leadsWord(count)}` : "Tags on this lead"}
      description={
        many
          ? "Pick tags, or type a new one."
          : "Tick the tags this lead carries."
      }
      wide="center"
      className={styles.sheet}
      footer={
        <span className={styles.footer}>
          {many && picked.size ? (
            <span className={styles.preview} role="status">
              {tagPreview(count, names, mode)}
            </span>
          ) : null}
          <button
            type="button"
            className={styles.pill}
            disabled={!changed || busy}
            onClick={() => void go()}
          >
            {pillWords}
          </button>
        </span>
      }
    >
      <div className={styles.body} aria-busy={!tags && !failed}>
        {many ? (
          <div className={styles.modes} role="radiogroup" aria-label="Do">
            {(["add", "remove"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={mode === value}
                className={styles.mode}
                data-on={mode === value ? "" : undefined}
                onClick={() => setMode(value)}
              >
                {value === "add" ? "Add tags" : "Take tags off"}
              </button>
            ))}
          </div>
        ) : null}
        <label className={styles.search}>
          <Search size={20} aria-hidden="true" />
          <input
            type="text"
            placeholder="Find or make a tag"
            aria-label="Find or make a tag"
            maxLength={32}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && words && !exact) {
                event.preventDefault();
                void make();
              }
            }}
          />
        </label>
        {failed ? (
          <p className={styles.note}>{failed}</p>
        ) : !tags ? (
          <ul className={styles.list} aria-label="Loading your tags">
            {[0, 1, 2].map((key) => (
              <li key={key} className={styles.ghost} />
            ))}
          </ul>
        ) : (
          <ul className={styles.list} aria-label="Tags">
            {words && !exact && mode === "add" && !full ? (
              <li>
                <button
                  type="button"
                  className={styles.make}
                  disabled={making}
                  onClick={() => void make()}
                >
                  <span className={styles.plus} aria-hidden="true">
                    <Plus size={18} />
                  </span>
                  {making ? "Making…" : `Make “${words.slice(0, 32)}”`}
                </button>
              </li>
            ) : null}
            {shown.map((tag) => {
              const on = picked.has(tag.tag_id);
              const waits = full && !on;
              return (
                <li key={tag.tag_id}>
                  <label
                    className={styles.tag}
                    data-on={on ? "" : undefined}
                    data-waits={waits ? "" : undefined}
                  >
                    <TagDot colour={tag.colour} />
                    <span className={styles.name}>{tag.name}</span>
                    <span className={styles.count}>
                      {tag.leads.toLocaleString("en-IN")}
                    </span>
                    <input
                      type="checkbox"
                      className={styles.box}
                      checked={on}
                      disabled={waits}
                      onChange={() => toggle(tag.tag_id)}
                    />
                    <span className={styles.tick} aria-hidden="true">
                      {on ? <Check size={16} /> : null}
                    </span>
                  </label>
                </li>
              );
            })}
            {full ? (
              <li className={styles.note} role="status">
                {many
                  ? `Up to ${TAGS_AT_MOST} tags in one change.`
                  : `Up to ${TAGS_AT_MOST} tags on a lead. Untick one to add another.`}
              </li>
            ) : null}
            {!tags.length && !words ? (
              <li className={styles.note}>
                No tags yet. Type a name above, like “Nov video ad”.
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </Sheet>
  );
}

/**
 * The lead page's tags (0165): its chips and a quiet "Tag" button for anyone
 * who may change the lead, which opens the sheet for this lead alone.
 */
export function LeadTagsLine({
  leadId,
  tags,
  canEdit,
  onChanged,
}: {
  leadId: string;
  tags: readonly TagChip[] | undefined;
  canEdit: boolean;
  onChanged?: () => void;
}) {
  const [sheet, setSheet] = useState<{ round: number; open: boolean } | null>(
    null,
  );
  const [shown, setShown] = useState<readonly TagChip[] | null>(null);
  const now = shown ?? tags ?? [];
  if (!now.length && !canEdit) return null;
  return (
    <div className={styles.leadLine} data-lead-tags="">
      <TagChips tags={now} max={6} size="md" />
      {canEdit ? (
        <button
          type="button"
          className={styles.leadEdit}
          onClick={() =>
            setSheet((current) => ({
              round: (current?.round ?? 0) + 1,
              open: true,
            }))
          }
        >
          {now.length ? null : <Plus size={14} aria-hidden="true" />}
          {now.length ? "Edit tags" : "Tag"}
        </button>
      ) : null}
      {sheet ? (
        <TagSheet
          key={sheet.round}
          open={sheet.open}
          target={{ kind: "one", leadId, tags: now }}
          onClose={() =>
            setSheet((current) => current && { ...current, open: false })
          }
          onDone={(next) => {
            setSheet((current) => current && { ...current, open: false });
            if (next) setShown(next);
            onChanged?.();
          }}
        />
      ) : null}
    </div>
  );
}
