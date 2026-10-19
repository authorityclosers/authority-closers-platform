"use client";

/**
 * One look for the CRM's connection and setup screens (owner, 20 Oct: "many
 * new things need a far better UI"): a card per app with its real logo, a
 * status in plain words, one line on what it does and one main action; Pages
 * and numbers inside as smaller cards; switches instead of checkboxes; and a
 * save bar that appears only when something changed. Same size while loading,
 * so nothing jumps when the answer arrives.
 */

import type { LucideIcon } from "lucide-react";
import type { InputHTMLAttributes, ReactNode } from "react";

import { BRANDS, type Brand } from "../brands/brand-registry";
import { BrandMark } from "../report-entities";
import { Skeleton } from "../ui/kit";
import styles from "./app-card.module.css";

export type CardTone = "good" | "warn" | "bad" | "neutral" | "accent";

const brand = (key: string): Brand | undefined =>
  BRANDS.find((item) => item.key === key);

/** An app's own logo on a soft tile, or a line icon for our own features. */
export function AppLogo({
  brands,
  icon: Icon,
  size = 40,
}: {
  /** Brand keys from the brand library; a second one sits on the corner. */
  brands?: string[];
  icon?: LucideIcon;
  size?: number;
}) {
  const [first, second] = (brands ?? [])
    .map(brand)
    .filter((item): item is Brand => !!item);
  return (
    <span
      className={styles.logo}
      data-kind={first ? "brand" : "icon"}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {first ? (
        <BrandMark brand={first} size={Math.round(size * 0.6)} />
      ) : Icon ? (
        <Icon size={Math.round(size * 0.5)} strokeWidth={1.9} />
      ) : null}
      {second ? (
        <span className={styles.logoBadge}>
          <BrandMark brand={second} size={Math.round(size * 0.34)} />
        </span>
      ) : null}
    </span>
  );
}

/** A status in a few plain words, with a dot that carries its colour. */
export function StatusPill({
  tone = "neutral",
  children,
}: {
  tone?: CardTone;
  children: ReactNode;
}) {
  return (
    <span className={styles.status} data-tone={tone}>
      <span aria-hidden="true" />
      {children}
    </span>
  );
}

export function AppCard({
  logo,
  title,
  status,
  summary,
  action,
  children,
  label,
}: {
  logo: ReactNode;
  title: string;
  status?: ReactNode;
  summary?: ReactNode;
  /** The one main thing to do here. */
  action?: ReactNode;
  children?: ReactNode;
  label?: string;
}) {
  return (
    <section className={styles.card} aria-label={label ?? title}>
      <header className={styles.head}>
        {logo}
        <div className={styles.headText}>
          <div className={styles.titleRow}>
            <h3>{title}</h3>
            {status}
          </div>
          {summary ? <p className={styles.summary}>{summary}</p> : null}
        </div>
        {action ? <div className={styles.action}>{action}</div> : null}
      </header>
      {children ? <div className={styles.body}>{children}</div> : null}
    </section>
  );
}

/** The same card while its status loads: same header, same height. */
export function AppCardSkeleton({
  title,
  logo,
  lines = 1,
}: {
  title: string;
  logo: ReactNode;
  lines?: number;
}) {
  return (
    <section className={styles.card} aria-label={title} aria-busy="true">
      <header className={styles.head}>
        {logo}
        <div className={styles.headText}>
          <div className={styles.titleRow}>
            <h3>{title}</h3>
            <Skeleton width={84} height={20} />
          </div>
          <Skeleton width="72%" height={12} />
        </div>
        <div className={styles.action}>
          <Skeleton width={112} height={34} />
        </div>
      </header>
      {lines > 1 ? (
        <div className={styles.body}>
          {Array.from({ length: lines - 1 }, (_, index) => (
            <Skeleton key={index} height={64} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** A Page, number or account inside an app's card. */
export function SubCard({
  title,
  meta,
  tone,
  actions,
  children,
  off,
}: {
  title: ReactNode;
  meta?: ReactNode;
  tone?: CardTone;
  actions?: ReactNode;
  children?: ReactNode;
  off?: boolean;
}) {
  return (
    <article
      className={styles.sub}
      data-tone={tone}
      data-off={off ? "" : undefined}
    >
      <div className={styles.subHead}>
        <div className={styles.subTitle}>
          <strong>{title}</strong>
          {meta ? <small>{meta}</small> : null}
        </div>
        {actions ? <div className={styles.subActions}>{actions}</div> : null}
      </div>
      {children ? <div className={styles.subBody}>{children}</div> : null}
    </article>
  );
}

/** A titled group of settings inside a card. */
export function Group({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={styles.group}>
      <div className={styles.groupHead}>
        <h4>{title}</h4>
        {hint ? <p>{hint}</p> : null}
      </div>
      {children}
    </div>
  );
}

/**
 * One setting with an on/off switch (a real checkbox, drawn as a switch), its
 * plain explanation, and what it needs once on.
 */
export function SwitchRow({
  label,
  hint,
  checked,
  onChange,
  disabled,
  children,
  ...rest
}: {
  label: ReactNode;
  hint?: ReactNode;
  checked: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  children?: ReactNode;
} & Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "onChange" | "checked" | "type"
>) {
  return (
    <div className={styles.switchRow} data-on={checked ? "" : undefined}>
      <label className={styles.switchLabel}>
        <span className={styles.switchText}>
          <strong>{label}</strong>
          {hint ? <small>{hint}</small> : null}
        </span>
        <input
          {...rest}
          type="checkbox"
          role="switch"
          className={styles.switch}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
      </label>
      {checked && children ? (
        <div className={styles.switchMore}>{children}</div>
      ) : null}
    </div>
  );
}

/**
 * Appears at the foot of a form once something changed: Discard and Save.
 * "Saved." stays a moment after saving; problems go to a corner card.
 */
export function SaveBar({
  dirty,
  busy,
  saved,
  onSave,
  onDiscard,
  label = "Save",
  savedText = "Saved.",
}: {
  dirty: boolean;
  busy: boolean;
  saved?: boolean;
  /** What "saved" says, e.g. "Target saved: 5 minutes." */
  savedText?: string;
  onSave: () => void;
  onDiscard?: () => void;
  label?: string;
}) {
  if (!dirty && !saved) return null;
  return (
    <div
      className={styles.saveBar}
      data-saved={!dirty && saved ? "" : undefined}
    >
      <span role="status">
        {dirty ? "You have changes that aren't saved yet." : savedText}
      </span>
      {dirty ? (
        <span className={styles.saveActions}>
          {onDiscard ? (
            <button
              type="button"
              className={styles.quiet}
              disabled={busy}
              onClick={onDiscard}
            >
              Discard
            </button>
          ) : null}
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={onSave}
          >
            {busy ? "Saving…" : label}
          </button>
        </span>
      ) : null}
    </div>
  );
}

export const cardStyles = styles;
