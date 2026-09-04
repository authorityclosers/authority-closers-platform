"use client";

import {
  ArrowRight,
  BarChart2,
  Bell,
  BookOpen,
  CalendarDays,
  Compass,
  HelpCircle,
  LayoutDashboard,
  Search,
  Settings,
  User,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useEffect, useId, useRef, useState } from "react";
import { ROUTES } from "../../lib/routes";
import type { CommandPaletteItem } from "./sidebar-types";

export type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  items?: CommandPaletteItem[];
  learningHref?: string;
  triggerRef?: React.RefObject<HTMLElement | null>;
  invokingElement?: HTMLElement | null;
};

export function resolveCommandPaletteRestoreFocusTarget({
  invokingElement,
  activeElement,
  fallbackTrigger,
}: {
  invokingElement?: HTMLElement | null;
  activeElement?: HTMLElement | null;
  fallbackTrigger?: HTMLElement | null;
}): HTMLElement | null {
  if (invokingElement) return invokingElement;
  if (
    activeElement &&
    (typeof document === "undefined" || activeElement !== document.body)
  ) {
    return activeElement;
  }
  return fallbackTrigger ?? null;
}

export function getDefaultCommandPaletteItems(
  learningHref: string = ROUTES.learning,
): CommandPaletteItem[] {
  return [
    {
      id: "nav-dashboard",
      label: "Dashboard",
      description: "Return to learner command center",
      href: ROUTES.dashboard,
      icon: <LayoutDashboard size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["home", "overview", "start", "command"],
      shortcut: "G H",
    },
    {
      id: "nav-learning",
      label: "My Learning",
      description: "Active courses, enrolled modules, and lessons",
      href: learningHref,
      icon: <BookOpen size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["courses", "study", "curriculum", "lessons"],
      shortcut: "G L",
    },
    {
      id: "nav-discover",
      label: "Discover",
      description: "Explore published programs and training catalogs",
      href: ROUTES.discover,
      icon: <Compass size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["catalog", "explore", "programs", "browse"],
    },
    {
      id: "nav-progress",
      label: "Progress",
      description: "Track completed activities and verifiable milestones",
      href: ROUTES.progress,
      icon: <BarChart2 size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["analytics", "stats", "history", "milestones"],
    },
    {
      id: "nav-calendar",
      label: "Calendar",
      description: "Scheduled sessions and planned learning periods",
      href: ROUTES.calendar,
      icon: <CalendarDays size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["schedule", "plan", "sessions", "dates"],
    },
    {
      id: "nav-notifications",
      label: "Notifications",
      description: "Review assignment updates and system alerts",
      href: ROUTES.notifications,
      icon: <Bell size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["alerts", "updates", "messages"],
    },
    {
      id: "nav-profile",
      label: "Learner Profile",
      description: "Manage personal details, avatar, and credentials",
      href: ROUTES.profile,
      icon: <User size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["account", "avatar", "identity", "me"],
    },
    {
      id: "nav-settings",
      label: "Settings & Appearance",
      description: "Customize theme, preferences, and session controls",
      href: ROUTES.settings,
      icon: <Settings size={18} aria-hidden="true" />,
      category: "Navigation",
      keywords: ["theme", "dark", "light", "appearance", "preferences"],
    },
    {
      id: "help-support",
      label: "Help & Support",
      description: "Email learner support for human guidance",
      href: "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support",
      icon: <HelpCircle size={18} aria-hidden="true" />,
      category: "Help",
      keywords: ["contact", "support", "questions", "email"],
    },
  ];
}

export function CommandPalette({
  open,
  onClose,
  items,
  learningHref = ROUTES.learning,
  triggerRef,
  invokingElement,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const inputId = useId();
  const listboxId = useId();
  let router: ReturnType<typeof useRouter> | null = null;
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    router = useRouter();
  } catch {
    // Graceful fallback in environments where useRouter is not provided
  }

  const allItems = items ?? getDefaultCommandPaletteItems(learningHref);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const filteredItems = query.trim()
    ? allItems.filter((item) => {
        const q = query.toLowerCase();
        const matchesLabel = item.label.toLowerCase().includes(q);
        const matchesDesc = item.description?.toLowerCase().includes(q);
        const matchesCat = item.category.toLowerCase().includes(q);
        const matchesKey = item.keywords?.some((k) =>
          k.toLowerCase().includes(q),
        );
        return matchesLabel || matchesDesc || matchesCat || matchesKey;
      })
    : allItems;
  const activeOption = filteredItems[activeIndex];
  const activeOptionId = activeOption
    ? `${listboxId}-option-${encodeURIComponent(activeOption.id)}`
    : undefined;

  const [prevOpen, setPrevOpen] = useState(open);
  const [prevQuery, setPrevQuery] = useState(query);

  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setQuery("");
      setActiveIndex(0);
    }
  }

  if (query !== prevQuery) {
    setPrevQuery(query);
    setActiveIndex(0);
  }

  useEffect(() => {
    if (!open) return;

    const active =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    restoreFocusRef.current = resolveCommandPaletteRestoreFocusTarget({
      invokingElement,
      activeElement: active,
      fallbackTrigger: (triggerRef?.current as HTMLElement | null) ?? null,
    });

    const shell = overlayRef.current?.closest<HTMLElement>(
      ".site-frame--learner",
    );
    const background = shell
      ? Array.from(shell.children).filter(
          (element): element is HTMLElement =>
            element instanceof HTMLElement && element !== overlayRef.current,
        )
      : [];
    const previouslyInert = new Map<HTMLElement, string | null>();
    background.forEach((element) => {
      previouslyInert.set(element, element.getAttribute("inert"));
      element.setAttribute("inert", "");
    });

    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusInput = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });

    const handleModalKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = dialogRef.current
        ? Array.from(
            dialogRef.current.querySelectorAll<HTMLElement>(focusableSelector),
          )
        : [];
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener("keydown", handleModalKeyDown);
    try {
      window.dispatchEvent(
        new CustomEvent("ac:ui-command-palette", {
          detail: { action: "open" },
        }),
      );
    } catch {
      // The palette remains functional when CustomEvent is unavailable.
    }

    return () => {
      window.cancelAnimationFrame(focusInput);
      document.removeEventListener("keydown", handleModalKeyDown);
      previouslyInert.forEach((value, element) => {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      });
      const restoreTarget = restoreFocusRef.current;
      restoreFocusRef.current = null;
      restoreTarget?.focus();
    };
  }, [open, invokingElement, triggerRef]);

  // Scroll active item into view if necessary
  useEffect(() => {
    if (!open || !listRef.current) return;
    const activeElement = listRef.current.children[activeIndex] as
      | HTMLElement
      | undefined;
    activeElement?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  const handleSelect = (item: CommandPaletteItem) => {
    onClose();
    if (item.onSelect) {
      item.onSelect();
    } else if (item.href) {
      if (item.href.startsWith("mailto:") || item.href.startsWith("http")) {
        window.location.assign(item.href);
      } else if (router) {
        router.push(item.href);
      } else {
        window.location.assign(item.href);
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!filteredItems.length) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) =>
        prev < filteredItems.length - 1 ? prev + 1 : 0,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) =>
        prev > 0 ? prev - 1 : filteredItems.length - 1,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      const selected = filteredItems[activeIndex];
      if (selected) {
        handleSelect(selected);
      }
    }
  };

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="command-palette-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        id="learner-command-palette"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="command-palette-dialog"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId} className="sr-only">
          Search and navigate the learner workspace
        </h2>
        <div className="command-palette-search-bar">
          <Search
            size={18}
            className="command-palette-search-icon"
            aria-hidden="true"
          />
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            role="combobox"
            className="command-palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a destination or search..."
            aria-label="Navigation search"
            aria-controls={listboxId}
            aria-expanded={open}
            aria-autocomplete="list"
            aria-activedescendant={activeOptionId}
            autoComplete="off"
            spellCheck={false}
          />
          {query ? (
            <button
              type="button"
              className="command-palette-clear-btn"
              onClick={() => {
                setQuery("");
                inputRef.current?.focus();
              }}
              aria-label="Clear search"
            >
              <X size={16} aria-hidden="true" />
            </button>
          ) : (
            <kbd className="command-palette-kbd">ESC</kbd>
          )}
        </div>

        <div className="command-palette-body">
          <ul
            id={listboxId}
            ref={listRef}
            className="command-palette-list"
            role="listbox"
            aria-label="Navigation results"
          >
            {filteredItems.map((item, index) => {
              const isSelected = index === activeIndex;
              return (
                <li
                  key={item.id}
                  id={`${listboxId}-option-${encodeURIComponent(item.id)}`}
                  role="option"
                  aria-selected={isSelected}
                  className={`command-palette-item${
                    isSelected ? " is-active" : ""
                  }`}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setActiveIndex(index)}
                >
                  <span
                    className="command-palette-item__icon"
                    aria-hidden="true"
                  >
                    {item.icon}
                  </span>
                  <div className="command-palette-item__text">
                    <strong className="command-palette-item__label">
                      {item.label}
                    </strong>
                    {item.description ? (
                      <span className="command-palette-item__description">
                        {item.description}
                      </span>
                    ) : null}
                  </div>
                  {item.shortcut ? (
                    <kbd className="command-palette-item__shortcut">
                      {item.shortcut}
                    </kbd>
                  ) : (
                    <ArrowRight
                      size={14}
                      className="command-palette-item__arrow"
                      aria-hidden="true"
                    />
                  )}
                </li>
              );
            })}
          </ul>
          {filteredItems.length === 0 ? (
            <div className="command-palette-empty" role="status">
              <p>No matching destinations found for &ldquo;{query}&rdquo;</p>
              <span>
                Try searching for &ldquo;dashboard&rdquo;,
                &ldquo;learning&rdquo;, or &ldquo;settings&rdquo;
              </span>
            </div>
          ) : null}
        </div>

        <div className="command-palette-footer">
          <div className="command-palette-footer__hints">
            <span>
              <kbd>↑</kbd> <kbd>↓</kbd> navigate
            </span>
            <span>
              <kbd>↵</kbd> select
            </span>
            <span>
              <kbd>esc</kbd> close
            </span>
          </div>
          <span className="command-palette-footer__hint-gh">
            <kbd>G</kbd> then <kbd>H</kbd> / <kbd>L</kbd> quick jump
          </span>
        </div>
      </div>
    </div>
  );
}

export function useCommandPaletteShortcuts({
  onOpenPalette,
  onNavigateHome,
  onNavigateLearning,
}: {
  onOpenPalette: () => void;
  onNavigateHome?: () => void;
  onNavigateLearning?: () => void;
}) {
  useEffect(() => {
    let pendingGTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingG = false;

    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const isEditable =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);

      // Cmd+K or Ctrl+K opens palette
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "k" &&
        !e.defaultPrevented
      ) {
        e.preventDefault();
        onOpenPalette();
        return;
      }

      // G then H / G then L outside editable fields
      if (isEditable || e.metaKey || e.ctrlKey || e.altKey) {
        pendingG = false;
        if (pendingGTimer) clearTimeout(pendingGTimer);
        return;
      }

      const key = e.key.toLowerCase();

      if (pendingG) {
        pendingG = false;
        if (pendingGTimer) clearTimeout(pendingGTimer);

        if (key === "h") {
          e.preventDefault();
          onNavigateHome?.();
        } else if (key === "l") {
          e.preventDefault();
          onNavigateLearning?.();
        }
        return;
      }

      if (key === "g") {
        pendingG = true;
        pendingGTimer = setTimeout(() => {
          pendingG = false;
        }, 500);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (pendingGTimer) clearTimeout(pendingGTimer);
    };
  }, [onOpenPalette, onNavigateHome, onNavigateLearning]);
}
