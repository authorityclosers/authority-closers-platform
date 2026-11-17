"use client";

/** Small parts Ask Dipak's screens share: links that move in place, the breadcrumb, saving. */

import type { MouseEvent, ReactNode } from "react";

import { notify } from "../notice-center";
import styles from "./ask-dipak.module.css";
import { AskIcon } from "./icons";
import { viewHref, type AskView } from "./nav";
import { setItem } from "./progress";

export type Open = (view: AskView) => void;

/** A row or card that opens a screen: a real link, moved in place. */
export function ScreenButton({
  view,
  open,
  className,
  children,
  label,
}: {
  view: AskView;
  open: Open;
  className: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <a
      className={className}
      href={viewHref(view)}
      aria-label={label}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        event.preventDefault();
        open(view);
      }}
    >
      {children}
    </a>
  );
}

export function Breadcrumb({
  onBack,
  children,
}: {
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className={styles.breadcrumb} onClick={onBack}>
      <AskIcon name="left" size={19} />
      {children}
    </button>
  );
}

function saveFailed(retry: () => void) {
  notify({
    id: "ask-dipak-save",
    tone: "error",
    title: "Couldn’t save that",
    message: "Check your connection, then try again.",
    action: { label: "Try again", run: retry },
  });
}

export function toggle(id: string, item: "saved" | "mission", on: boolean) {
  void setItem(id, item, on).then((done) => {
    if (!done) saveFailed(() => toggle(id, item, on));
  });
}
