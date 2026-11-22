/**
 * Tag chips (migration 0165; picks 17 Nov 2026: small chips on the table row
 * and the lead page that never crowd the row). A row shows at most `max`
 * chips and "+N" for the rest; each chip wears its tag's tint from the app's
 * tokens (tag-chips.module.css), light and dark.
 */

import type { TagChip, TagColour } from "./leads-client";
import styles from "./tag-chips.module.css";

export const TAG_COLOURS: readonly TagColour[] = [
  "mint",
  "sky",
  "amber",
  "rose",
  "violet",
  "slate",
  "lime",
  "orange",
];

export function TagDot({ colour }: { colour: TagColour }) {
  return (
    <span className={styles.dot} data-colour={colour} aria-hidden="true" />
  );
}

export function TagChips({
  tags,
  max = 2,
  size = "sm",
  inline = false,
  className,
}: {
  tags: readonly TagChip[] | null | undefined;
  /** Chips shown before "+N". */
  max?: number;
  /** "sm" on rows, "md" on the lead page. */
  size?: "sm" | "md";
  /** After words on a line: a small gap before the first chip. */
  inline?: boolean;
  className?: string;
}) {
  if (!tags?.length) return null;
  const shown = tags.slice(0, Math.max(1, max));
  const rest = tags.length - shown.length;
  return (
    <span
      className={[styles.chips, className].filter(Boolean).join(" ")}
      data-size={size}
      data-inline={inline ? "" : undefined}
      title={tags.map((tag) => tag.name).join(", ")}
    >
      {shown.map((tag) => (
        <span key={tag.tag_id} className={styles.chip} data-colour={tag.colour}>
          {tag.name}
        </span>
      ))}
      {rest > 0 ? <span className={styles.more}>{`+${rest}`}</span> : null}
    </span>
  );
}
