"use client";

/**
 * Phones: Leads and Chats share the Leads tab (owner, 20 Oct: "5 tabs, Chats
 * inside Leads"), with this switch at the top of both. Computers keep their own
 * Chats item in the rail, so the switch is hidden there.
 *
 * The hop is the shell's ScreenLink: the other side's outline shows at once.
 * Until it has opened, the page under the finger takes no taps, so a tap
 * meant for a chat row can't land on the old page's buttons (the
 * orchestrator's dev pass: a first tap opened Calling on Leads).
 */

import { useEffect, type MouseEvent } from "react";

import { ScreenLink } from "../shell/screen-link";
import { useWorkspaceAccess } from "../workspace-access";
import { useUnreadChats } from "./chats-badge";
import styles from "./leads-chats-switch.module.css";

const HOLD_MS = 8000;
let release: number | null = null;

/** The page under the shell stops taking taps while the other side opens. */
function hold(on: boolean) {
  const main = document.getElementById("main-content");
  if (release !== null) window.clearTimeout(release);
  release = null;
  if (!main) return;
  if (on) {
    main.setAttribute("inert", "");
    // Never stuck: the next page lets go, and so does this, after a while.
    release = window.setTimeout(() => hold(false), HOLD_MS);
  } else {
    main.removeAttribute("inert");
  }
}

export function LeadsChatsSwitch({ current }: { current: "leads" | "chats" }) {
  const access = useWorkspaceAccess();
  const live =
    access?.authenticated === true &&
    access.status === "ready" &&
    process.env.NODE_ENV !== "test";
  const unread = useUnreadChats(live);

  // This side has opened: the page takes taps again.
  useEffect(() => hold(false), []);

  const leave = (event: MouseEvent<HTMLAnchorElement>, to: string) => {
    if (
      to === current ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.button !== 0
    )
      return;
    hold(true);
  };

  return (
    <nav className={styles.switch} aria-label="Leads or chats">
      <ScreenLink
        href="/leads"
        prefetch={false}
        aria-current={current === "leads" ? "page" : undefined}
        onClick={(event) => leave(event, "leads")}
      >
        Leads
      </ScreenLink>
      <ScreenLink
        href="/chats"
        prefetch={false}
        aria-current={current === "chats" ? "page" : undefined}
        onClick={(event) => leave(event, "chats")}
      >
        Chats
        {unread ? (
          <span className={styles.count}>
            <span aria-hidden="true">{unread > 99 ? "99+" : unread}</span>
            <span className={styles.srOnly}>{`, ${unread} unread`}</span>
          </span>
        ) : null}
      </ScreenLink>
    </nav>
  );
}
