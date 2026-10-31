"use client";

/**
 * The one picker (owner, 31 Oct 2026): a choice from a short list, such as a
 * pipeline stage or a lead source. Phones: the shared bottom sheet rises on its
 * spring. Computers: a popover under the button fades and grows in. Inside a
 * sheet ("inline"), the list opens in place, growing in height as it fades in,
 * and scrolls into view above the sheet's buttons.
 *
 * Each row has its colour dot, name, live count and a check on the chosen one;
 * the row that clears the choice ("All stages") comes first. A listbox: the
 * arrows, Home and End move, Enter or Space picks, Escape closes. Reduce
 * motion: fades only.
 */
import { Check, ChevronDown } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
} from "react";

import styles from "./picker.module.css";
import { SHEET_PHONE_QUERY, Sheet } from "./sheet";

export type PickerOption = {
  key: string;
  label: string;
  /** The row's colour dot, as CSS (a palette token). */
  tone?: string | null;
  /** Its live count; null or undefined shows none. */
  count?: number | null;
};

type Row = Omit<PickerOption, "key"> & { key: string | null };

const watchPhone = (change: () => void) => {
  const query = window.matchMedia?.(SHEET_PHONE_QUERY);
  query?.addEventListener?.("change", change);
  return () => query?.removeEventListener?.("change", change);
};

function usePhone(): boolean {
  return useSyncExternalStore(
    watchPhone,
    () => !!window.matchMedia?.(SHEET_PHONE_QUERY).matches,
    () => false,
  );
}

const reducedMotion = () =>
  !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function focusRow(list: HTMLElement | null, index: number) {
  list
    ?.querySelectorAll<HTMLElement>('[role="option"]')
    [index]?.focus({ preventScroll: false });
}

function Dot({ tone }: { tone?: string | null }) {
  return (
    <span
      className={styles.dot}
      data-none={tone ? undefined : ""}
      style={tone ? ({ "--dot": tone } as CSSProperties) : undefined}
      aria-hidden="true"
    />
  );
}

function Options({
  id,
  title,
  rows,
  value,
  open,
  onPick,
  onEscape,
}: {
  id: string;
  title: string;
  rows: readonly Row[];
  value: string | null;
  open: boolean;
  onPick: (key: string | null) => void;
  /** Escape closes the list; a sheet's own Escape closes the sheet instead. */
  onEscape?: () => void;
}) {
  const list = useRef<HTMLUListElement>(null);
  const chosen = Math.max(
    0,
    rows.findIndex((row) => row.key === value),
  );
  // Each opening starts from the chosen row (the list is drawn afresh).
  const [active, setActive] = useState(chosen);
  const dots = rows.some((row) => row.tone);
  useEffect(() => {
    if (!open) return;
    // Opening puts focus on the chosen row once the list is up.
    const frame = requestAnimationFrame(() => focusRow(list.current, chosen));
    return () => cancelAnimationFrame(frame);
  }, [open, chosen]);
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const last = rows.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, active + 1),
      ArrowUp: Math.max(0, active - 1),
      Home: 0,
      End: last,
    };
    const to = moves[event.key];
    if (to !== undefined) {
      event.preventDefault();
      setActive(to);
      focusRow(list.current, to);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onPick(rows[active].key);
    } else if (event.key === "Escape" && onEscape) {
      event.preventDefault();
      event.stopPropagation();
      onEscape();
    }
  };
  return (
    <ul
      ref={list}
      id={id}
      role="listbox"
      aria-label={title}
      className={styles.list}
      data-plain={dots ? undefined : ""}
      onKeyDown={onKeyDown}
    >
      {rows.map((row, index) => (
        <li
          key={row.key ?? ""}
          role="option"
          aria-selected={row.key === value}
          tabIndex={index === active ? 0 : -1}
          className={styles.option}
          onFocus={() => setActive(index)}
          onClick={() => onPick(row.key)}
        >
          {dots ? <Dot tone={row.tone} /> : null}
          <span className={styles.name}>{row.label}</span>
          {row.count != null ? (
            <span className={styles.count}>
              {row.count.toLocaleString("en-IN")}
            </span>
          ) : (
            <span />
          )}
          <Check size={18} aria-hidden="true" className={styles.check} />
        </li>
      ))}
    </ul>
  );
}

export function Picker({
  title,
  label,
  value,
  options,
  all,
  onChange,
  mode = "auto",
  className,
}: {
  /** The list's name: the sheet's title and the listbox's label. */
  title: string;
  /** Words before the choice on the button ("Pipeline stage:"). */
  label?: string;
  /** The chosen key, or null for the `all` row. */
  value: string | null;
  options: readonly PickerOption[];
  /** The first row, which clears the choice ("All stages"). */
  all?: { label: string; count?: number | null };
  onChange: (key: string | null) => void;
  /** "inline": the list opens in place, for a picker inside a sheet. */
  mode?: "auto" | "inline";
  className?: string;
}) {
  const phone = usePhone();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const inline = mode === "inline";
  const sheet = !inline && phone;
  const rows: Row[] = [
    ...(all ? [{ key: null, label: all.label, count: all.count }] : []),
    ...options,
  ];
  const chosen: Partial<Row> = rows.find((row) => row.key === value) ??
    (value ? { key: value, label: value } : rows[0]) ?? { label: "" };

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus && !sheet) button.current?.focus();
  };
  const pick = (key: string | null) => {
    close();
    if (key !== value) onChange(key);
  };

  // A popover closes on a tap or click anywhere else.
  useEffect(() => {
    if (!open || sheet || inline) return;
    const away = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, sheet, inline]);

  // A list opening in place comes into view, clear of the sheet's buttons.
  useEffect(() => {
    if (!open || !inline) return;
    const timer = window.setTimeout(
      () =>
        root.current?.scrollIntoView?.({
          block: "nearest",
          behavior: reducedMotion() ? "auto" : "smooth",
        }),
      230,
    );
    return () => window.clearTimeout(timer);
  }, [open, inline]);

  const list = (
    <Options
      key={open ? "open" : "shut"}
      id={listId}
      title={title}
      rows={rows}
      value={value}
      open={open}
      onPick={pick}
      onEscape={sheet ? undefined : () => close()}
    />
  );
  return (
    <div
      ref={root}
      className={[styles.root, className].filter(Boolean).join(" ")}
      data-mode={inline ? "inline" : undefined}
      onBlur={(event) => {
        // Tabbing away closes a popover.
        if (
          open &&
          !sheet &&
          !inline &&
          event.relatedTarget &&
          !root.current?.contains(event.relatedTarget as Node)
        )
          setOpen(false);
      }}
    >
      <button
        ref={button}
        type="button"
        className={styles.button}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((now) => !now)}
        onKeyDown={(event) => {
          if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {label ? <span className={styles.label}>{label}</span> : null}
        <span className={styles.value}>
          {chosen.tone ? <Dot tone={chosen.tone} /> : null}
          <span className={styles.valueWords}>{chosen.label}</span>
        </span>
        <ChevronDown size={18} aria-hidden="true" className={styles.mark} />
      </button>
      {inline ? (
        <div
          className={styles.drawer}
          data-open={open ? "" : undefined}
          inert={!open}
        >
          <div className={styles.drawerInner}>{list}</div>
        </div>
      ) : sheet ? (
        <Sheet open={open} onClose={() => close(false)} title={title}>
          {list}
        </Sheet>
      ) : open ? (
        <div className={styles.pop}>{list}</div>
      ) : null}
    </div>
  );
}
