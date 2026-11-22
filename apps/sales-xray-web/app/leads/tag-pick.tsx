"use client";

/**
 * The tag filter chip beside the stages (migration 0165; picks 17 Nov 2026):
 * "Any tag", or one of the workspace's tags with its count. A workspace with
 * no tags shows no chip, so the approved row stays as it is until tags exist.
 * Owners, admins and managers find "Manage tags" under the list (v1.94).
 */

import { Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Picker } from "../ui/picker";
import type { ListMore, TagColour, TagView } from "./leads-client";
import { UNDONE_EVENT } from "./manage-bar";
import { ManageTagsSheet } from "./manage-tags";
import { readTagsSoon, TAGS_CHANGED_EVENT } from "./tag-sheet";
import styles from "./tag-sheet.module.css";

/** Each tag's dot in the picker, as a token (tag-chips.module.css). */
export const TAG_TONES: Record<TagColour, string> = {
  mint: "var(--sx-tone-good)",
  sky: "var(--sx-tone-calls)",
  amber: "color-mix(in oklab, var(--sx-warn) 78%, var(--sx-tone-good))",
  rose: "var(--sx-tone-problem)",
  violet: "var(--sx-tone-info)",
  slate: "var(--sx-muted)",
  lime: "color-mix(in oklab, var(--sx-tone-good) 55%, var(--sx-warn))",
  orange: "var(--sx-tone-action)",
};

export function TagPick({
  more,
  onChange,
}: {
  more: ListMore;
  onChange: (next: Partial<ListMore>) => void;
}) {
  const [tags, setTags] = useState<TagView[] | null>(null);
  const [round, setRound] = useState(0);
  const [manage, setManage] = useState<{ round: number; open: boolean } | null>(
    null,
  );
  // A tag made, renamed or deleted elsewhere, or a bulk change: read again.
  useEffect(() => {
    const again = () => setRound((value) => value + 1);
    window.addEventListener(TAGS_CHANGED_EVENT, again);
    window.addEventListener(UNDONE_EVENT, again);
    return () => {
      window.removeEventListener(TAGS_CHANGED_EVENT, again);
      window.removeEventListener(UNDONE_EVENT, again);
    };
  }, []);
  useEffect(() => {
    let live = true;
    readTagsSoon().then(
      (next) => {
        if (live) setTags(next);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [round]);
  const value = more.tag ?? null;
  // The chosen tag was deleted: the list shows every lead again.
  const change = useRef(onChange);
  useEffect(() => {
    change.current = onChange;
  });
  const gone = !!(tags && value && !tags.some((tag) => tag.tag_id === value));
  useEffect(() => {
    if (gone) change.current({ tag: null });
  }, [gone]);
  const canManage = !!tags?.some((tag) => tag.can_change);
  if (!tags?.length && !value) return null;
  const picked = tags?.find((tag) => tag.tag_id === value) ?? null;
  const words = value ? (picked?.name ?? "Tag") : "Any tag";
  return (
    <>
      <Picker
        variant="chip"
        title="Tag"
        ariaLabel={`Tag: ${words}`}
        value={value}
        options={(tags ?? []).map((tag) => ({
          key: tag.tag_id,
          label: tag.name,
          tone: TAG_TONES[tag.colour],
          count: tag.leads,
        }))}
        all={{ label: "Any tag" }}
        display={<span>{words}</span>}
        onChange={(key) => onChange({ tag: key })}
        footer={
          canManage ? (
            <button
              type="button"
              className={styles.manage}
              onClick={() =>
                setManage((current) => ({
                  round: (current?.round ?? 0) + 1,
                  open: true,
                }))
              }
            >
              <Settings2 size={18} aria-hidden="true" />
              Manage tags
            </button>
          ) : undefined
        }
      />
      {manage ? (
        <ManageTagsSheet
          key={manage.round}
          open={manage.open}
          onClose={() =>
            setManage((current) => current && { ...current, open: false })
          }
        />
      ) : null}
    </>
  );
}
