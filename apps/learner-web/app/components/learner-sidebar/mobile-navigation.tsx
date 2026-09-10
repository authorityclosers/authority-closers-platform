"use client";

import {
  BarChart2,
  Bell,
  BookOpen,
  CalendarDays,
  Compass,
  Gamepad2,
  HelpCircle,
  LayoutDashboard,
  MoreHorizontal,
  Settings,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import React, { useEffect, useRef } from "react";
import { ROUTES } from "../../lib/routes";
import { SignOutControl } from "../sign-out-control";

const SUPPORT_MAILTO =
  "mailto:admin@authorityclosers.com?subject=Authority%20Closers%20Learner%20Support";

export type MobileBottomNavProps = {
  current?: string;
  learningHref?: string;
  practiceAvailable?: boolean;
  moreOpen: boolean;
  onToggleMore: () => void;
  moreButtonRef: React.RefObject<HTMLButtonElement | null>;
};

export function MobileBottomNav({
  current = "dashboard",
  learningHref = ROUTES.learning,
  practiceAvailable = false,
  moreOpen,
  onToggleMore,
  moreButtonRef,
}: MobileBottomNavProps) {
  const isHome = current === "dashboard" || current === "home";
  const isLearning = current === "learning" || current === "course";
  const isDiscover = current === "discover";
  const isProgress = current === "progress";
  const isCalendar = current === "calendar";
  const isNotifications = current === "notifications";
  const isProfile = current === "profile";
  const isSettings = current === "settings";
  const isMore =
    isCalendar ||
    isNotifications ||
    isProfile ||
    isSettings ||
    (practiceAvailable && isDiscover);
  const isThirdCurrent = practiceAvailable
    ? current === "practice"
    : isDiscover;

  return (
    <nav className="learner-bottom-nav" aria-label="Learner mobile navigation">
      <Link
        className={`learner-nav__link${isHome ? " is-current" : ""}`}
        href={ROUTES.dashboard}
        prefetch={false}
        aria-current={isHome ? "page" : undefined}
      >
        <span className="learner-nav__icon" aria-hidden="true">
          <LayoutDashboard size={20} />
        </span>
        <span className="learner-nav__label">Home</span>
      </Link>

      <Link
        className={`learner-nav__link${isLearning ? " is-current" : ""}`}
        href={learningHref}
        prefetch={false}
        aria-current={isLearning ? "page" : undefined}
      >
        <span className="learner-nav__icon" aria-hidden="true">
          <BookOpen size={20} />
        </span>
        <span className="learner-nav__label">Learning</span>
      </Link>

      <Link
        className={`learner-nav__link${isThirdCurrent ? " is-current" : ""}`}
        href={practiceAvailable ? ROUTES.arcade : ROUTES.discover}
        prefetch={false}
        aria-current={isThirdCurrent ? "page" : undefined}
        aria-label={practiceAvailable ? "Practice Arcade" : undefined}
      >
        <span className="learner-nav__icon" aria-hidden="true">
          {practiceAvailable ? <Gamepad2 size={20} /> : <Compass size={20} />}
        </span>
        <span className="learner-nav__label">
          {practiceAvailable ? "Arcade" : "Discover"}
        </span>
      </Link>

      <Link
        className={`learner-nav__link${isProgress ? " is-current" : ""}`}
        href={ROUTES.progress}
        prefetch={false}
        aria-current={isProgress ? "page" : undefined}
      >
        <span className="learner-nav__icon" aria-hidden="true">
          <BarChart2 size={20} />
        </span>
        <span className="learner-nav__label">Progress</span>
      </Link>

      <button
        ref={moreButtonRef}
        type="button"
        className={`learner-nav__link${isMore || moreOpen ? " is-current" : ""}`}
        onClick={onToggleMore}
        aria-expanded={moreOpen}
        aria-controls="learner-more-drawer"
        aria-current={isMore ? "page" : undefined}
        aria-haspopup="dialog"
        aria-label="More navigation options"
      >
        <span className="learner-nav__icon" aria-hidden="true">
          <MoreHorizontal size={20} />
        </span>
        <span className="learner-nav__label">More</span>
      </button>
    </nav>
  );
}

export type MobileMoreSheetProps = {
  open: boolean;
  practiceAvailable?: boolean;
  current?: string;
  onClose: () => void;
  userDisplayName?: string;
  avatarSlot?: React.ReactNode;
  moreButtonRef?: React.RefObject<HTMLButtonElement | null>;
};

export function MobileMoreSheet({
  open,
  practiceAvailable = false,
  current,
  onClose,
  userDisplayName = "Learner",
  avatarSlot,
  moreButtonRef,
}: MobileMoreSheetProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;

    restoreFocusRef.current =
      moreButtonRef?.current ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);

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
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusFirst = window.requestAnimationFrame(() => {
      const first =
        sheetRef.current?.querySelector<HTMLElement>(focusableSelector);
      (first ?? sheetRef.current)?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") return;

      const focusable = sheetRef.current
        ? Array.from(
            sheetRef.current.querySelectorAll<HTMLElement>(focusableSelector),
          )
        : [];
      if (focusable.length === 0) {
        event.preventDefault();
        sheetRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFirst);
      document.removeEventListener("keydown", handleKeyDown);
      previouslyInert.forEach((value, element) => {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      });
      const restoreTarget = restoreFocusRef.current;
      restoreFocusRef.current = null;
      restoreTarget?.focus();
    };
  }, [open, moreButtonRef]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="mobile-drawer-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        id="learner-more-drawer"
        ref={sheetRef}
        className="mobile-drawer-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="learner-more-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mobile-drawer-header">
          <div className="mobile-drawer-user">
            {avatarSlot}
            <div>
              <strong id="learner-more-title">{userDisplayName}</strong>
              <span>Learner workspace</span>
            </div>
          </div>
          <button
            type="button"
            className="mobile-drawer-close"
            onClick={onClose}
            aria-label="Close menu"
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <nav className="mobile-drawer-nav" aria-label="More learner navigation">
          {practiceAvailable ? (
            <Link
              href={ROUTES.discover}
              prefetch={false}
              className="mobile-drawer-link"
              aria-current={current === "discover" ? "page" : undefined}
              onClick={onClose}
            >
              <Compass size={18} aria-hidden="true" />
              <span>Discover courses</span>
            </Link>
          ) : null}
          <Link
            href={ROUTES.profile}
            prefetch={false}
            className="mobile-drawer-link"
            onClick={onClose}
          >
            <User size={18} aria-hidden="true" />
            <span>Profile & Identity</span>
          </Link>
          <Link
            href={ROUTES.notifications}
            prefetch={false}
            className="mobile-drawer-link"
            onClick={onClose}
          >
            <Bell size={18} aria-hidden="true" />
            <span>Notifications</span>
          </Link>
          <Link
            href={ROUTES.calendar}
            prefetch={false}
            className="mobile-drawer-link"
            onClick={onClose}
          >
            <CalendarDays size={18} aria-hidden="true" />
            <span>Calendar</span>
          </Link>
          <Link
            href={ROUTES.settings}
            prefetch={false}
            className="mobile-drawer-link"
            onClick={onClose}
          >
            <Settings size={18} aria-hidden="true" />
            <span>Settings & Appearance</span>
          </Link>
          <a
            href={SUPPORT_MAILTO}
            className="mobile-drawer-link"
            onClick={onClose}
          >
            <HelpCircle size={18} aria-hidden="true" />
            <span>Help & Support</span>
          </a>
          <SignOutControl className="mobile-drawer-link mobile-drawer-link--danger" />
        </nav>
      </div>
    </div>
  );
}
