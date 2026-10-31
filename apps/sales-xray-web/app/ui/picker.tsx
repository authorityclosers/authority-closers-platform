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
 *
 * It stands in for every native select (picker sweep, 31 Oct 2026): it can be
 * disabled, show a placeholder, carry a form field's value and sit inside a
 * label, where a tap on a row must not reach the label and reopen the list.
 */
import { Check, ChevronDown } from "lucide-react";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
  type Ref,
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
          data-key={row.key ?? ""}
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
  defaultOpen = false,
  className,
  id,
  ariaLabel,
  describedBy,
  invalid,
  disabled,
  placeholder,
  name,
  buttonRef,
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
  /** "inline": the list opens in place, for a picker inside a sheet. "cell": a
      table cell's editor, whose list floats above the page (no table box clips
      it) and is never a sheet. */
  mode?: "auto" | "inline" | "cell";
  /** Open from the start, as when a click opened the editor holding it. */
  defaultOpen?: boolean;
  className?: string;
  /** The button's id, for a label elsewhere (`htmlFor`). */
  id?: string;
  /** The button's name for screen readers when no words show before the choice. */
  ariaLabel?: string;
  describedBy?: string;
  invalid?: boolean;
  disabled?: boolean;
  /** Shown, muted, while no row is chosen and there is no `all` row. */
  placeholder?: string;
  /** A form field's name: a hidden input carries the chosen key. */
  name?: string;
  buttonRef?: Ref<HTMLButtonElement | null>;
}) {
  const phone = usePhone();
  const [open, setOpen] = useState(defaultOpen);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useImperativeHandle(buttonRef, () => button.current as HTMLButtonElement, []);
  const listId = useId();
  const inline = mode === "inline";
  const cell = mode === "cell";
  const sheet = !inline && !cell && phone;
  const rows: Row[] = [
    ...(all ? [{ key: null, label: all.label, count: all.count }] : []),
    ...options,
  ];
  const chosen: Partial<Row> & { empty?: boolean } = rows.find(
    (row) => row.key === value,
  ) ??
    (placeholder !== undefined
      ? { label: placeholder, empty: true }
      : value
        ? { key: value, label: value }
        : rows[0]) ?? { label: "" };

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

  // A cell's list floats in the top layer, under its cell (or above it when
  // the screen has no room below), and closes when the page scrolls under it.
  useLayoutEffect(() => {
    const floating = pop.current;
    const anchor = button.current;
    if (!open || !cell || !floating || !anchor) return;
    floating.showPopover?.();
    const box = anchor.getBoundingClientRect();
    floating.style.minWidth = `${box.width}px`;
    const below = window.innerHeight - box.bottom - 8;
    const up = floating.offsetHeight > below && box.top > below;
    const left = Math.min(
      box.left,
      window.innerWidth - floating.offsetWidth - 8,
    );
    floating.style.left = `${Math.max(8, left)}px`;
    floating.style.top = `${
      up ? Math.max(8, box.top - floating.offsetHeight - 6) : box.bottom + 6
    }px`;
    const scrolled = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && floating.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener("scroll", scrolled, true);
    return () => window.removeEventListener("scroll", scrolled, true);
  }, [open, cell]);

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
      data-mode={inline ? "inline" : cell ? "cell" : undefined}
      onClick={(event) => {
        // Inside a label, a tap on a row would reach the label, which clicks
        // the button and opens the list again.
        if (!button.current?.contains(event.target as Node))
          event.preventDefault();
      }}
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
        id={id}
        type="button"
        className={styles.button}
        data-value={value ?? ""}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-describedby={describedBy}
        // A button can't carry aria-invalid; the words it points at say what's wrong.
        data-invalid={invalid ? "" : undefined}
        onClick={() => setOpen((now) => !now)}
        onKeyDown={(event) => {
          if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {ariaLabel ? (
          <span className={styles.srOnly}>{`${ariaLabel} `}</span>
        ) : null}
        {label ? <span className={styles.label}>{label}</span> : null}
        <span className={styles.value}>
          {chosen.tone ? <Dot tone={chosen.tone} /> : null}
          <span
            className={styles.valueWords}
            data-empty={chosen.empty ? "" : undefined}
          >
            {chosen.label}
          </span>
        </span>
        <ChevronDown size={18} aria-hidden="true" className={styles.mark} />
      </button>
      {name ? <input type="hidden" name={name} value={value ?? ""} /> : null}
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
        <div
          ref={pop}
          className={styles.pop}
          popover={cell ? "manual" : undefined}
        >
          {list}
        </div>
      ) : null}
    </div>
  );
}
