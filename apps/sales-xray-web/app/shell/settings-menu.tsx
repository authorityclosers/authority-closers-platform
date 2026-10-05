"use client";

import {
  ChevronLeft,
  ChevronRight,
  CircleUserRound,
  Clock3,
  Compass,
  CreditCard,
  Gem,
  Globe,
  LifeBuoy,
  Settings2,
  Sparkles,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";

import type { Allowance } from "../acquisition-client";
import { formatAnalysisTime } from "../analysis-time";
import { useFirstCallGuideSwitch } from "../guide-toggle";
import { openSettings } from "../settings-open";
import { CHANGELOG } from "./changelog";
import styles from "./settings-menu.module.css";

type View = "main" | "language" | "news";

const SEEN_KEY = "ac.xray.news-seen";
const SEEN_EVENT = "sales-xray:news-seen";

function readSeen(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY);
  } catch {
    return null;
  }
}

function subscribeSeen(callback: () => void) {
  window.addEventListener(SEEN_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(SEEN_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

/** How many changelog entries are newer than the last one this viewer saw. */
export function useUnseenNews(): number {
  const seen = useSyncExternalStore(subscribeSeen, readSeen, () => null);
  const index = CHANGELOG.findIndex((entry) => entry.id === seen);
  return index === -1 ? CHANGELOG.length : index;
}

function markNewsSeen() {
  try {
    localStorage.setItem(SEEN_KEY, CHANGELOG[0]?.id ?? "");
  } catch {
    // Private windows may refuse storage; the badge simply stays.
  }
  window.dispatchEvent(new Event(SEEN_EVENT));
}

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function initials(name: string | null, email: string | null) {
  const source = name?.trim() || email?.split("@")[0] || "";
  const parts = source.split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2);
  return letters.toUpperCase() || "·";
}

function minutesLine(allowance: Allowance | null) {
  if (!allowance || allowance.unlimited) return null;
  const left = formatAnalysisTime(allowance.available_seconds);
  const total = formatAnalysisTime(allowance.allowance_seconds);
  const share =
    allowance.allowance_seconds > 0
      ? Math.min(1, allowance.available_seconds / allowance.allowance_seconds)
      : 0;
  return { text: `${left} of ${total} left`, share };
}

function Row({
  icon,
  label,
  value,
  badge,
  next,
  checked,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value?: string;
  badge?: string;
  next?: boolean;
  /** Renders the row as an on/off switch. */
  checked?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.row}
      onClick={onClick}
      {...(checked === undefined
        ? {}
        : { role: "switch", "aria-checked": checked })}
    >
      <span className={styles.rowIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.rowLabel}>{label}</span>
      {badge ? <span className={styles.badge}>{badge}</span> : null}
      {value ? <span className={styles.rowValue}>{value}</span> : null}
      {next ? (
        <ChevronRight size={15} className={styles.chev} aria-hidden="true" />
      ) : null}
    </button>
  );
}

function Back({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <button type="button" className={styles.back} onClick={onBack}>
      <ChevronLeft size={16} aria-hidden="true" />
      {label}
    </button>
  );
}

/**
 * The account card that opens from the gear: who is signed in, the minutes
 * left, and one list for settings, language, usage, plans and what's new.
 */
export function SettingsMenu({
  open,
  anchorRef,
  onClose,
  name,
  email,
  allowance,
}: {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  name: string | null;
  email: string | null;
  allowance: Allowance | null;
}) {
  const [view, setView] = useState<View>("main");
  const [place, setPlace] = useState<{ left: number; bottom: number } | null>(
    null,
  );
  const card = useRef<HTMLDivElement>(null);
  const unseen = useUnseenNews();
  const minutes = minutesLine(allowance);
  const guide = useFirstCallGuideSwitch();

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      const mobile = window.innerWidth < 900;
      const width = Math.min(300, window.innerWidth - 16);
      const anchorVisible = Boolean(
        rect &&
          rect.width > 0 &&
          rect.height > 0 &&
          rect.right > 0 &&
          rect.left < window.innerWidth &&
          rect.bottom > 0 &&
          rect.top < window.innerHeight,
      );
      if (!rect || !anchorVisible) {
        setPlace({
          left: Math.max(8, Math.round((window.innerWidth - width) / 2)),
          bottom: 16,
        });
        return;
      }
      if (mobile) {
        const height =
          card.current?.getBoundingClientRect().height ??
          Math.min(620, window.innerHeight - 32);
        const maxBottom = Math.max(8, window.innerHeight - height - 8);
        setPlace({
          left: Math.max(8, Math.round((window.innerWidth - width) / 2)),
          bottom: Math.min(
            Math.max(8, Math.round(window.innerHeight - rect.top + 8)),
            maxBottom,
          ),
        });
        return;
      }
      const right = rect.right + 10;
      const left =
        right + width <= window.innerWidth - 8
          ? right
          : Math.max(8, rect.left - width - 10);
      setPlace({
        left: Math.round(left),
        bottom: Math.max(8, Math.round(window.innerHeight - rect.bottom)),
      });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [anchorRef, open]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !card.current?.contains(target) &&
        !anchorRef.current?.contains(target)
      )
        onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onClose();
      anchorRef.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    card.current?.querySelector<HTMLElement>("button")?.focus();
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchorRef, onClose, open]);

  useEffect(() => {
    // The shell mounts the card only while open, so each open starts at main.
    if (open && view === "news") markNewsSeen();
  }, [open, view]);

  if (!open || typeof document === "undefined") return null;

  const settings = (section: string) => {
    onClose();
    openSettings(section);
  };

  return createPortal(
    <div
      ref={card}
      className={styles.card}
      role="dialog"
      aria-label="Account menu"
      style={place ? { left: place.left, bottom: place.bottom } : undefined}
    >
      <div key={view} className={styles.view}>
        {view === "main" && (
          <>
            <div className={styles.who}>
              <span className={styles.avatar} aria-hidden="true">
                {initials(name, email)}
              </span>
              <span className={styles.whoText}>
                <b>{name || "Your account"}</b>
                {email ? <small>{email}</small> : null}
              </span>
            </div>
            {minutes ? (
              <button
                type="button"
                className={styles.usage}
                onClick={() => settings("usage")}
              >
                <span className={styles.usageTop}>
                  <span>Analysis time</span>
                  <b>{minutes.text}</b>
                </span>
                {minutes.share !== null ? (
                  <span className={styles.meter} aria-hidden="true">
                    <i style={{ width: `${minutes.share * 100}%` }} />
                  </span>
                ) : null}
              </button>
            ) : null}
            <div className={styles.list}>
              <Row
                icon={<Settings2 size={16} />}
                label="Settings"
                onClick={() => settings("general")}
              />
              <Row
                icon={<CircleUserRound size={16} />}
                label="Profile"
                onClick={() => settings("profile")}
              />
              <Row
                icon={<Globe size={16} />}
                label="Language"
                value="English"
                next
                onClick={() => setView("language")}
              />
              <Row
                icon={<Clock3 size={16} />}
                label="Usage"
                value={
                  minutes && minutes.share !== null
                    ? `${Math.round(minutes.share * 100)}% left`
                    : undefined
                }
                onClick={() => settings("usage")}
              />
              <Link href="/plans" className={styles.row} onClick={onClose}>
                <span className={styles.rowIcon} aria-hidden="true">
                  <Gem size={16} />
                </span>
                <span className={styles.rowLabel}>Plans</span>
                <ChevronRight
                  size={15}
                  className={styles.chev}
                  aria-hidden="true"
                />
              </Link>
              <Row
                icon={<CreditCard size={16} />}
                label="Plan & billing"
                onClick={() => settings("billing")}
              />
              <Row
                icon={<Sparkles size={16} />}
                label="What's new"
                badge={unseen > 0 ? `${unseen} new` : undefined}
                next
                onClick={() => setView("news")}
              />
              <span className={styles.divider} />
              <Row
                icon={<LifeBuoy size={16} />}
                label="Help & support"
                onClick={() => settings("help")}
              />
              {guide ? (
                <Row
                  icon={<Compass size={16} />}
                  label="First call guide"
                  value={guide.on ? "On" : "Off"}
                  checked={guide.on}
                  onClick={() => {
                    guide.set(!guide.on);
                    // Turning it on closes the menu so the guide is in view.
                    if (!guide.on) onClose();
                  }}
                />
              ) : null}
            </div>
          </>
        )}

        {view === "language" && (
          <>
            <Back label="Language" onBack={() => setView("main")} />
            <p className={styles.note}>App language</p>
            <div className={styles.choices}>
              <span className={styles.choice} data-on="">
                <i aria-hidden="true" />
                English
              </span>
              <span className={styles.choice} aria-disabled="true">
                <i aria-hidden="true" />
                हिन्दी
                <small>Coming soon</small>
              </span>
              <span className={styles.choice} aria-disabled="true">
                <i aria-hidden="true" />
                मराठी
                <small>Coming soon</small>
              </span>
            </div>
            <p className={styles.note}>
              Reports: pick English, Hindi + English or Marathi + English when
              you start an analysis.
            </p>
          </>
        )}

        {view === "news" && (
          <>
            <Back label="What's new" onBack={() => setView("main")} />
            <ol className={styles.news}>
              {CHANGELOG.map((entry, index) => (
                <li
                  key={entry.id}
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <time dateTime={entry.date}>
                    {DAY.format(new Date(`${entry.date}T00:00:00Z`))}
                  </time>
                  <b>
                    {entry.title}
                    {index < unseen ? (
                      <span className={styles.dot} aria-label="New" />
                    ) : null}
                  </b>
                  <ul>
                    {entry.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
