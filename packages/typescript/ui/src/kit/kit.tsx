"use client";

/**
 * The Sales Xray page kit, ported from Pulse's UI kit (EA Pulse, 10 Oct 2026)
 * and adapted to teal and the --sx-* tokens. One set of calm, dense pieces for
 * every strike: headers, panels, KPI tiles, badges, tables with phone cards,
 * list rows, fields and inline editing. No raw colours; text 12-15 px plus
 * 20/24 px titles and figures; controls 32 px (44 px on touch).
 *
 *   import { Panel, Kpi, Tiles, InlineEdit } from "../ui/kit";
 */
import { Anchor, type KitLink } from "../sx/link";
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Info,
  Minus,
  Pencil,
  X,
  type IconComponent,
} from "./icons";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { useBackClose } from "./back-close";
import styles from "./kit.module.css";

export { styles as kitStyles };

export type Tone = "neutral" | "accent" | "good" | "warn" | "bad";

const cx = (...names: (string | false | null | undefined)[]) =>
  names.filter(Boolean).join(" ");

/* ---------- Page ---------- */

/** Compact page header: title, one line of context, actions on the right. */
export function PageHeader({
  link: Link = Anchor,
  title,
  context,
  actions,
  back,
  titleInBar = false,
}: {
  link?: KitLink;
  title: string;
  context?: ReactNode[];
  actions?: ReactNode;
  back?: { href: string; label: string };
  /** The phone top bar already shows this title: phones keep it for screen
   *  readers only, so the page doesn't say its name twice. */
  titleInBar?: boolean;
}) {
  const items = (context ?? []).filter(Boolean);
  return (
    <header className={cx(styles.header, titleInBar && styles.titleInBar)}>
      <div className={styles.headerText}>
        {back ? (
          <Link href={back.href} className={styles.back}>
            <ChevronLeft size={13} aria-hidden="true" />
            {back.label}
          </Link>
        ) : null}
        <h1 className={styles.title} title={title}>
          {title}
        </h1>
        {items.length ? (
          <p className={styles.context}>
            {items.map((item, index) => (
              <span key={index}>{item}</span>
            ))}
          </p>
        ) : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  );
}

/** A titled surface. `tools` sit in the head; `action` is one quiet link. */
export function Panel({
  link: Link = Anchor,
  title,
  sub,
  tools,
  action,
  foot,
  children,
  className,
  style,
}: {
  link?: KitLink;
  title: string;
  sub?: ReactNode;
  tools?: ReactNode;
  action?: { href: string; label: string };
  foot?: ReactNode;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  const id = useId();
  return (
    <section
      className={cx(styles.panel, className)}
      style={style}
      aria-labelledby={id}
    >
      <div className={styles.panelHead}>
        <h2 id={id} className={styles.panelTitle}>
          {title}
          {sub !== undefined && sub !== null ? <small>{sub}</small> : null}
        </h2>
        {tools || action ? (
          <span className={styles.panelTools}>
            {tools}
            {action ? (
              <Link href={action.href} className={styles.panelAction}>
                {action.label}
                <ChevronRight size={13} aria-hidden="true" />
              </Link>
            ) : null}
          </span>
        ) : null}
      </div>
      {children}
      {foot ? <div className={styles.panelFoot}>{foot}</div> : null}
    </section>
  );
}

/* ---------- Numbers ---------- */

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <span className={styles.badge} data-tone={tone}>
      {children}
    </span>
  );
}

/** Change against a named baseline, as text and an arrow, never colour alone. */
export function Delta({
  value,
  previous,
}: {
  value: number;
  previous: number;
}) {
  if (!previous && !value)
    return (
      <span className={styles.delta} data-trend="flat">
        <Minus size={12} aria-hidden="true" />0
      </span>
    );
  if (!previous)
    return (
      <span className={styles.delta} data-trend="up">
        <ArrowUpRight size={13} aria-hidden="true" />
        new
      </span>
    );
  const pct = Math.round(((value - previous) / previous) * 100);
  if (pct === 0)
    return (
      <span className={styles.delta} data-trend="flat">
        <Minus size={12} aria-hidden="true" />
        0%
      </span>
    );
  const Icon = pct > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={styles.delta} data-trend={pct > 0 ? "up" : "down"}>
      <Icon size={13} aria-hidden="true" />
      <span className={styles.srOnly}>{pct > 0 ? "up " : "down "}</span>
      {Math.abs(pct)}%
    </span>
  );
}

/** Mini columns on one shared scale; under three busy points it says nothing. */
export function Spark({
  values,
  label,
  on,
}: {
  values: number[];
  label: string;
  on?: (index: number) => boolean;
}) {
  if (values.filter((value) => value > 0).length < 3) return null;
  const max = Math.max(1, ...values);
  return (
    <span className={styles.spark} role="img" aria-label={label}>
      {values.map((value, index) => (
        <i
          key={index}
          data-on={
            (on ? on(index) : index === values.length - 1) ? "" : undefined
          }
          style={{
            height: `${Math.max(value ? 12 : 0, (value / max) * 100)}%`,
          }}
        />
      ))}
    </span>
  );
}

/** A row of KPI tiles that reflows from 4 across to 2 on phones. */
export function Tiles({
  children,
  label = "Key numbers",
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <section className={styles.tiles} aria-label={label}>
      {children}
    </section>
  );
}

export function Kpi({
  link: Link = Anchor,
  label,
  value,
  unit,
  delta,
  note,
  spark,
  href,
  tone,
}: {
  link?: KitLink;
  label: string;
  value: ReactNode;
  unit?: string;
  delta?: ReactNode;
  note?: ReactNode;
  spark?: ReactNode;
  href?: string;
  tone?: Tone;
}) {
  const body = (
    <>
      <span className={styles.tileLabel}>
        {tone ? <span className={styles.dot} data-tone={tone} /> : null}
        {label}
      </span>
      <span className={styles.tileMain}>
        <strong className={styles.tileValue}>
          {value}
          {unit ? <small>{unit}</small> : null}
        </strong>
        {delta}
        {spark ? <span className={styles.tileSpark}>{spark}</span> : null}
      </span>
      {note ? <span className={styles.tileNote}>{note}</span> : null}
    </>
  );
  return href ? (
    <Link href={href} className={styles.tile}>
      {body}
    </Link>
  ) : (
    <div className={styles.tile}>{body}</div>
  );
}

/** A thin bar for a share; the number beside it says the value. */
export function Meter({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label?: string;
}) {
  const share = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <span
      className={styles.meter}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <i style={{ width: `${share * 100}%` }} />
    </span>
  );
}

/* ---------- States ---------- */

/** One empty state with at most one action. */
export function Empty({
  link: Link = Anchor,
  icon: Icon,
  title,
  text,
  action,
}: {
  link?: KitLink;
  icon: IconComponent;
  title: string;
  text?: string;
  action?:
    | { href: string; label: string }
    | { onClick: () => void; label: string };
}) {
  return (
    <div className={styles.empty}>
      <span className={styles.emptyIcon} aria-hidden="true">
        <Icon size={16} strokeWidth={1.75} />
      </span>
      <p className={styles.emptyTitle}>{title}</p>
      {text ? <p className={styles.emptyText}>{text}</p> : null}
      {action ? (
        "href" in action ? (
          <Link href={action.href} className={styles.button}>
            {action.label}
          </Link>
        ) : (
          <button
            type="button"
            className={styles.button}
            onClick={action.onClick}
          >
            {action.label}
          </button>
        )
      ) : null}
    </div>
  );
}

/** "How we know this": a small (i) that opens the source of a figure. */
export function Why({
  detail,
  more,
  label = "How we know this",
}: {
  detail: string;
  more?: string;
  label?: string;
}) {
  return (
    <details className={styles.why}>
      <summary aria-label={label} title={label}>
        <Info size={14} aria-hidden="true" />
      </summary>
      <div className={styles.whyPanel}>
        <p>{detail}</p>
        {more ? <p>{more}</p> : null}
      </div>
    </details>
  );
}

/** A value, or a quiet prompt when the record doesn't have it yet. */
export function Fact({
  value,
  missing = "Not set",
}: {
  value?: ReactNode;
  missing?: string;
}) {
  return value === null || value === undefined || value === "" ? (
    <span className={styles.muted}>{missing}</span>
  ) : (
    <>{value}</>
  );
}

/** A placeholder the size of what will arrive, so nothing moves. */
export function Skeleton({
  width = "100%",
  height = 12,
  radius,
}: {
  width?: number | string;
  height?: number;
  /** "pill" for chips and tabs, "circle" for avatars, or pixels. */
  radius?: "pill" | "circle" | number;
}) {
  return (
    <span
      className={styles.skeleton}
      style={{
        width,
        height,
        borderRadius:
          radius === "pill" ? 999 : radius === "circle" ? "50%" : radius,
      }}
      aria-hidden="true"
    />
  );
}

/**
 * A list row's outline at the row's own height (Liquid Glass polish, 22 Oct
 * 2026: the outline is the final layout, so nothing moves when rows arrive):
 * an avatar, a name and its context lines, and a chip at the end.
 */
export function SkeletonRow({
  avatar = 40,
  lines = 2,
  end = true,
}: {
  /** The avatar's size, or false for a row without one. */
  avatar?: number | false;
  lines?: 1 | 2 | 3;
  end?: boolean;
}) {
  return (
    <span className={styles.skeletonRow} aria-hidden="true">
      {avatar ? (
        <Skeleton width={avatar} height={avatar} radius="circle" />
      ) : null}
      <span className={styles.skeletonLines}>
        <Skeleton width="46%" height={14} />
        {lines > 1 ? <Skeleton width="68%" height={11} /> : null}
        {lines > 2 ? <Skeleton width="38%" height={11} /> : null}
      </span>
      {end ? <Skeleton width={52} height={22} radius="pill" /> : null}
    </span>
  );
}

/* ---------- Navigation ---------- */

/** Tabs that live in the address (?tab=), so reload and links keep them. */
export function QueryTabs({
  link: Link = Anchor,
  base,
  items,
  current,
  param = "tab",
  keep,
}: {
  link?: KitLink;
  base: string;
  items: { key: string; label: ReactNode; count?: number }[];
  current: string;
  param?: string;
  keep?: string;
}) {
  return (
    <nav className={styles.tabs} aria-label="Sections">
      {items.map((item, index) => {
        const query = [keep ?? "", index ? `${param}=${item.key}` : ""]
          .filter(Boolean)
          .join("&");
        return (
          <Link
            key={item.key}
            href={query ? `${base}?${query}` : base}
            scroll={false}
            className={styles.tab}
            aria-current={item.key === current ? "page" : undefined}
          >
            {item.label}
            {item.count !== undefined ? (
              <span className={styles.tabCount}>{item.count}</span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** A second level of choice, drawn as a segmented control. */
export function Segmented<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: { key: T; label: ReactNode }[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  // The chosen segment's pill slides to the next one (owner bug #45, 27 Oct
  // 2026: "nice perfectly made micro interactions"). It is placed straight on
  // the element, before paint; until it is, the chosen segment keeps its own
  // lift, so the first paint looks the same.
  const group = useRef<HTMLDivElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const root = group.current;
    const mark = pill.current;
    if (!root || !mark) return;
    const place = () => {
      const chosen = root.querySelector<HTMLElement>('[aria-pressed="true"]');
      if (!chosen) {
        delete root.dataset.pill;
        return;
      }
      mark.style.width = `${chosen.offsetWidth}px`;
      mark.style.transform = `translateX(${chosen.offsetLeft}px)`;
      root.dataset.pill = "";
    };
    place();
    // Slides from the next change on, never into its first place.
    const frame = requestAnimationFrame(() => {
      root.dataset.slide = "";
    });
    const resize =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    resize?.observe(root);
    return () => {
      cancelAnimationFrame(frame);
      resize?.disconnect();
    };
  }, [value, items.length]);
  return (
    <div
      ref={group}
      className={styles.segmented}
      role="group"
      aria-label={label}
    >
      <span ref={pill} className={styles.segmentPill} aria-hidden="true" />
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className={styles.segment}
          aria-pressed={item.key === value}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- People ---------- */

const hue = (text: string) => {
  let value = 0;
  for (const ch of text) value = (value * 31 + ch.charCodeAt(0)) % 360;
  return value;
};

/** A text's characters as a reader sees them: a Devanagari letter with its
 *  vowel sign is one (सु, not स), so an initial never splits one. */
export function graphemes(text: string): string[] {
  if (typeof Intl.Segmenter !== "function") return Array.from(text);
  const parts = new Intl.Segmenter(undefined, { granularity: "grapheme" });
  return Array.from(parts.segment(text), (part) => part.segment);
}

const LETTER = /^[\p{L}\p{N}]/u;

/** Each of the first two words' first letter, by grapheme; an emoji or a
 *  symbol is never an initial ("?" when the name has no letter at all). Phone
 *  personas ph1-34, 1 Nov 2026: सुरेश पाटील read "सप", and "Priya 🌸" got a
 *  flower for an initial. */
export const initials = (name: string) =>
  name
    .replace(/^(mr|mrs|ms|dr|miss)\.?\s+/i, "")
    .split(/\s+/)
    .map((part) => graphemes(part).find((one) => LETTER.test(one)))
    .filter((one): one is string => !!one)
    .slice(0, 2)
    .join("")
    .toUpperCase() || "?";

/** A name with no letter in it gets a person, never "?" or an emoji. */
function NoInitials() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="58%"
      height="58%"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </svg>
  );
}

/** A photo, or initials on a tint that stays the same for the same name. */
export function Avatar({
  name,
  photoUrl,
  size = 24,
  shape,
}: {
  name: string;
  photoUrl?: string | null;
  size?: number;
  shape?: "square";
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={styles.avatar}
      data-shape={shape}
      style={{ "--size": `${size}px`, "--hue": hue(name) } as CSSProperties}
      aria-hidden="true"
    >
      {photoUrl && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- Private, session-bound images; already sized.
        <img
          src={photoUrl}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : initials(name) === "?" ? (
        <NoInitials />
      ) : size < 22 ? (
        // Initials stay at 12 px or more: a small avatar has room for one.
        graphemes(initials(name))[0]
      ) : (
        initials(name)
      )}
    </span>
  );
}

/* ---------- Lists, tables and cards ---------- */

export function List({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <ul className={styles.list} aria-label={label}>
      {children}
    </ul>
  );
}

/** One 40 px+ row: icon, title with its meta line, and an end slot. */
export function Row({
  link: Link = Anchor,
  icon,
  title,
  href,
  meta,
  end,
}: {
  link?: KitLink;
  icon?: ReactNode;
  title: ReactNode;
  href?: string;
  meta?: ReactNode[];
  end?: ReactNode;
}) {
  const items = (meta ?? []).filter(Boolean);
  return (
    <li className={styles.row}>
      {icon ? <span className={styles.rowIcon}>{icon}</span> : null}
      <span className={styles.rowMain}>
        {href ? (
          <Link href={href} className={styles.rowTitle}>
            {title}
          </Link>
        ) : (
          <span className={styles.rowTitle}>{title}</span>
        )}
        {items.length ? (
          <span className={styles.rowMeta}>
            {items.map((item, index) => (
              <span key={index}>{item}</span>
            ))}
          </span>
        ) : null}
      </span>
      {end ? <span className={styles.rowEnd}>{end}</span> : null}
    </li>
  );
}

/**
 * A list of things to do or open: menus, settings lists, action sheets
 * (design system, 22 Oct 2026). Each row is one tap target at least 56 px
 * tall: an icon tile in a tone, a title with one line of note, an optional
 * end (a count, a value) and a chevron.
 *
 *   <ActionList label="Leads settings">
 *     <ActionRow icon={<Users size={20} />} title="Team" note="Who takes leads" href="/leads?tab=team" />
 *     <ActionRow icon={<Upload size={20} />} title="Import" note="A file of leads" onClick={openImport} />
 *   </ActionList>
 */
export function ActionList({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <ul className={styles.actionList} aria-label={label}>
      {children}
    </ul>
  );
}

export function ActionRow({
  link: Link = Anchor,
  icon,
  title,
  note,
  href,
  onClick,
  tone = "accent",
  end,
  trailing,
  disabled = false,
  chevron = true,
}: {
  link?: KitLink;
  icon?: ReactNode;
  title: ReactNode;
  note?: ReactNode;
  /** A place to go: the row is a link. Otherwise it is a button. */
  href?: string;
  onClick?: () => void;
  tone?: Tone;
  end?: ReactNode;
  /**
   * An action of its own beside the row (remove a saved view), outside the
   * row's button so the two never nest; give it its own label.
   */
  trailing?: ReactNode;
  disabled?: boolean;
  chevron?: boolean;
}) {
  const inside = (
    <>
      {icon ? (
        <span className={styles.actionIcon} data-tone={tone} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className={styles.actionWords}>
        <strong>{title}</strong>
        {note ? <small>{note}</small> : null}
      </span>
      {end ? <span className={styles.actionEnd}>{end}</span> : null}
      {chevron ? (
        <ChevronRight
          className={styles.actionChevron}
          size={18}
          aria-hidden="true"
        />
      ) : null}
    </>
  );
  return (
    <li className={styles.actionItem} data-trailing={trailing ? "" : undefined}>
      {href && !disabled ? (
        <Link href={href} className={styles.actionRow} onClick={onClick}>
          {inside}
        </Link>
      ) : (
        <button
          type="button"
          className={styles.actionRow}
          onClick={onClick}
          disabled={disabled}
        >
          {inside}
        </button>
      )}
      {trailing ? (
        <span className={styles.actionTrailing}>{trailing}</span>
      ) : null}
    </li>
  );
}

/**
 * A Linear-style table on wide screens. Pass `cards` to show the same rows
 * as cards on phones (below 760 px) instead of a sideways-scrolling table.
 */
export function Table({
  label,
  children,
  cards,
}: {
  label: string;
  children: ReactNode;
  cards?: ReactNode;
}) {
  return (
    <>
      <div className={styles.tableWrap} data-has-cards={cards ? "" : undefined}>
        <table className={styles.table} aria-label={label}>
          {children}
        </table>
      </div>
      {cards ? (
        <div className={styles.cards} aria-label={label} role="list">
          {cards}
        </div>
      ) : null}
    </>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return (
    <article className={styles.card} role="listitem">
      {children}
    </article>
  );
}

/* ---------- Controls ---------- */

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "icon";
}) {
  return (
    <button
      type="button"
      {...props}
      className={cx(styles.button, className)}
      data-variant={variant}
    />
  );
}

/** A labelled field with its hint or error underneath, at one fixed height. */
export function Field({
  label,
  hint,
  error,
  children,
  wide,
}: {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={styles.field} data-wide={wide ? "" : undefined}>
      <span className={styles.fieldLabel}>{label}</span>
      {children}
      {error ? (
        <small className={styles.fieldError} role="alert">
          {error}
        </small>
      ) : hint ? (
        <small className={styles.fieldHint}>{hint}</small>
      ) : null}
    </label>
  );
}

/**
 * Click (or Enter) to edit in place. Enter or leaving the box saves, Escape
 * keeps the old value. A failed save keeps the draft and says why; nothing
 * changes on screen until `onSave` resolves.
 */
export function InlineEdit({
  value,
  onSave,
  label,
  placeholder = "Add",
  maxLength,
  disabled = false,
}: {
  value: string;
  onSave: (next: string) => Promise<void>;
  label: string;
  placeholder?: string;
  maxLength?: number;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  // Set while the box closes, so a blur from closing never saves (or re-saves).
  const closing = useRef(false);
  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  const start = () => {
    if (disabled) return;
    closing.current = false;
    setDraft(value);
    setState("idle");
    setError("");
    setEditing(true);
  };
  const stop = () => {
    closing.current = true;
    setEditing(false);
    requestAnimationFrame(() => trigger.current?.focus());
  };
  const commit = async () => {
    if (state === "saving" || closing.current) return;
    const next = draft.trim();
    if (next === value.trim()) {
      stop();
      return;
    }
    setState("saving");
    setError("");
    try {
      await onSave(next);
      setState("idle");
      stop();
    } catch (reason) {
      setState("error");
      setError(
        reason instanceof Error && reason.message
          ? reason.message
          : "Not saved. Try again.",
      );
    }
  };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closing.current = true;
      setDraft(value);
      setState("idle");
      setError("");
      stop();
    }
  };

  if (!editing)
    return (
      <button
        ref={trigger}
        type="button"
        className={styles.inline}
        onClick={start}
        disabled={disabled}
        aria-label={`${label}: ${value || placeholder}. Edit`}
      >
        <span className={value ? undefined : styles.muted}>
          {value || placeholder}
        </span>
        {disabled ? null : <Pencil size={12} aria-hidden="true" />}
      </button>
    );
  return (
    <span className={styles.inlineEditing}>
      <input
        ref={input}
        className={styles.inlineInput}
        value={draft}
        maxLength={maxLength}
        aria-label={label}
        aria-invalid={state === "error" || undefined}
        disabled={state === "saving"}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKey}
        onBlur={() => void commit()}
      />
      <small
        className={state === "error" ? styles.fieldError : styles.fieldHint}
        role={state === "error" ? "alert" : "status"}
      >
        {state === "saving" ? "Saving…" : error}
      </small>
    </span>
  );
}

/* ---------- Dialog ---------- */

/**
 * A small modal: one title, a line of context, the body and its actions.
 * Native <dialog>, so focus stays inside and Escape closes it.
 */
/**
 * A press on a modal dialog's backdrop lands on the dialog element itself,
 * outside its box. Keyboard clicks carry no position and never count.
 */
export function onBackdrop(event: {
  target: EventTarget;
  currentTarget: Element;
  clientX: number;
  clientY: number;
}): boolean {
  if (event.target !== event.currentTarget) return false;
  const box = event.currentTarget.getBoundingClientRect();
  return (
    event.clientX < box.left ||
    event.clientX > box.right ||
    event.clientY < box.top ||
    event.clientY > box.bottom
  );
}

export function Dialog({
  open,
  title,
  description,
  onClose,
  actions,
  children,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // Owner, 18 Oct: Escape alone is hard to find on a computer. A press that
  // starts and ends on the dimmed backdrop closes too; a text selection
  // dragged out of the box does not.
  const pressedOutside = useRef(false);
  const titleId = useId();
  // Back (the button, the phone's gesture or key) closes it (owner, 22 Oct).
  useBackClose(open, onClose);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onPointerDown={(event) => {
        pressedOutside.current = onBackdrop(event);
      }}
      onClick={(event) => {
        const started = pressedOutside.current;
        pressedOutside.current = false;
        if (started && onBackdrop(event)) onClose();
      }}
    >
      {open ? (
        <>
          <div className={styles.dialogHead}>
            <h2 id={titleId} className={styles.dialogTitle}>
              {title}
            </h2>
            <button
              type="button"
              className={styles.dialogClose}
              aria-label="Close"
              title="Close"
              onClick={onClose}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          {description ? (
            <p className={styles.dialogText}>{description}</p>
          ) : null}
          {children}
          {actions ? (
            <div className={styles.dialogActions}>{actions}</div>
          ) : null}
        </>
      ) : null}
    </dialog>
  );
}
