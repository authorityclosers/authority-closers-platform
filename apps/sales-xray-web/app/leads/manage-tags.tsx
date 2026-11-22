"use client";

/**
 * Manage tags (v1.94, owner 22 Nov 2026: "do lead tags as v1.94"): owners,
 * admins and managers rename, recolour and delete the team's tags, from the
 * tag filter's list. One tag opens at a time; Save is the one main button.
 * Deleting asks once and says how many leads lose it; each lead's history
 * keeps what it said. A stale tag (changed elsewhere) reloads with the words.
 */

import { ChevronDown, Pencil } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import {
  deleteTag,
  editTag,
  LeadsError,
  type TagColour,
  type TagView,
} from "./leads-client";
import { failWords, UNDONE_EVENT } from "./manage-bar";
import { TAG_COLOURS, TagDot } from "./tag-chips";
import { forgetTags, readTagsSoon, TAGS_CHANGED_EVENT } from "./tag-sheet";
import styles from "./manage-tags.module.css";

const COLOUR_WORDS: Record<TagColour, string> = {
  mint: "Green",
  sky: "Blue",
  amber: "Amber",
  rose: "Red",
  violet: "Violet",
  slate: "Grey",
  lime: "Olive",
  orange: "Orange",
};

const leadsOn = (count: number) =>
  `${count.toLocaleString("en-IN")} ${count === 1 ? "lead" : "leads"}`;

/** Tags changed: the list, its chips and the tag filter read again. */
export function sayTagsChanged() {
  forgetTags();
  window.dispatchEvent(new Event(TAGS_CHANGED_EVENT));
  window.dispatchEvent(new Event(UNDONE_EVENT));
}

export function ManageTagsSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [tags, setTags] = useState<TagView[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [colour, setColour] = useState<TagColour>("mint");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    forgetTags();
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
  }, [open, round]);

  const start = (tag: TagView) => {
    if (editing === tag.tag_id) {
      setEditing(null);
      return;
    }
    setEditing(tag.tag_id);
    setName(tag.name);
    setColour(tag.colour);
    setAsking(false);
  };

  const stale = (reason: unknown, fallback: string) => {
    notify({
      id: "tag-manage",
      tone: "error",
      title: fallback,
      message: failWords(reason, "Check your connection and try again."),
    });
    // Changed elsewhere: read the tags again, so the next try is on top.
    if (reason instanceof LeadsError && reason.status === 409) {
      setEditing(null);
      setRound((value) => value + 1);
    }
  };

  const save = async (tag: TagView) => {
    const words = name.trim().replace(/\s+/g, " ").slice(0, 32);
    if (!words || busy) return;
    setBusy(true);
    try {
      const saved = await editTag(tag.tag_id, {
        expected_revision: tag.revision,
        ...(words !== tag.name ? { name: words } : {}),
        ...(colour !== tag.colour ? { colour } : {}),
      });
      setTags(
        (current) =>
          current?.map((item) =>
            item.tag_id === saved.tag_id ? { ...item, ...saved } : item,
          ) ?? null,
      );
      setEditing(null);
      sayTagsChanged();
      notify({
        id: "tag-manage",
        tone: "success",
        title: `Saved “${saved.name}”`,
        timeout: 4000,
      });
    } catch (reason) {
      stale(reason, "That tag wasn't saved");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (tag: TagView) => {
    if (busy) return;
    setBusy(true);
    try {
      const answer = await deleteTag(tag.tag_id, tag.revision);
      setTags(answer.tags);
      setEditing(null);
      sayTagsChanged();
      notify({
        id: "tag-manage",
        tone: "success",
        title: `Deleted “${tag.name}”`,
        message: tag.leads ? `It came off ${leadsOn(tag.leads)}.` : undefined,
        timeout: 5000,
      });
    } catch (reason) {
      stale(reason, "That tag wasn't deleted");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Manage tags"
      description="Rename, recolour or delete your team's tags."
      wide="center"
      className={styles.sheet}
    >
      {failed ? (
        <p className={styles.note}>{failed}</p>
      ) : !tags ? (
        <ul className={styles.list} aria-label="Loading your tags" aria-busy>
          {[0, 1, 2].map((key) => (
            <li key={key} className={styles.ghost} />
          ))}
        </ul>
      ) : !tags.length ? (
        <p className={styles.note}>
          No tags yet. Tag a lead to make the first one.
        </p>
      ) : (
        <ul className={styles.list} aria-label="Your tags">
          {tags.map((tag) => {
            const on = editing === tag.tag_id;
            const words = name.trim().replace(/\s+/g, " ");
            const changed =
              on && !!words && (words !== tag.name || colour !== tag.colour);
            return (
              <li
                key={tag.tag_id}
                className={styles.item}
                data-open={on ? "" : undefined}
              >
                <button
                  type="button"
                  className={styles.row}
                  aria-expanded={on}
                  onClick={() => start(tag)}
                >
                  <TagDot colour={on ? colour : tag.colour} />
                  <span className={styles.name}>{tag.name}</span>
                  <span className={styles.count}>{leadsOn(tag.leads)}</span>
                  <span className={styles.icon} aria-hidden="true">
                    {on ? <ChevronDown size={18} /> : <Pencil size={16} />}
                  </span>
                </button>
                {on ? (
                  <div className={styles.editor}>
                    <label className={styles.field}>
                      <span>Name</span>
                      <input
                        type="text"
                        maxLength={32}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && changed) {
                            event.preventDefault();
                            void save(tag);
                          }
                        }}
                      />
                    </label>
                    <div
                      className={styles.swatches}
                      role="radiogroup"
                      aria-label="Colour"
                    >
                      {TAG_COLOURS.map((value) => (
                        <button
                          key={value}
                          type="button"
                          role="radio"
                          aria-checked={colour === value}
                          aria-label={COLOUR_WORDS[value]}
                          title={COLOUR_WORDS[value]}
                          className={styles.swatch}
                          data-on={colour === value ? "" : undefined}
                          onClick={() => setColour(value)}
                        >
                          <TagDot colour={value} />
                        </button>
                      ))}
                    </div>
                    {asking ? (
                      <div className={styles.ask} role="alert">
                        <p>
                          {`Delete “${tag.name}”?`}{" "}
                          {tag.leads
                            ? `It comes off ${leadsOn(tag.leads)}; their history keeps it.`
                            : "No lead has it."}
                        </p>
                        <div className={styles.actions}>
                          <button
                            type="button"
                            className={styles.quiet}
                            onClick={() => setAsking(false)}
                          >
                            Keep it
                          </button>
                          <button
                            type="button"
                            className={styles.danger}
                            disabled={busy}
                            onClick={() => void remove(tag)}
                          >
                            {busy ? "Deleting…" : "Delete tag"}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={styles.delete}
                          onClick={() => setAsking(true)}
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          className={styles.save}
                          disabled={!changed || busy}
                          onClick={() => void save(tag)}
                        >
                          {busy ? "Saving…" : "Save"}
                        </button>
                      </div>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Sheet>
  );
}
