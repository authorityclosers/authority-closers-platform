"use client";

import { useEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import styles from "./rail-tip.module.css";

type Tip = { text: string; top: number; left: number };

const tipTarget = (node: EventTarget | null) =>
  node instanceof Element ? node.closest<HTMLElement>("[data-rail-tip]") : null;

/**
 * The icon rail's labels. One label is drawn on the page body beside the icon
 * under the mouse or keyboard focus, so no panel, page or bar can cover or
 * clip it. Each icon keeps its own accessible name; the label is visual only.
 */
export function RailTip({ rail }: { rail: RefObject<HTMLElement | null> }) {
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    const node = rail.current;
    if (!node) return;
    const show = (target: HTMLElement | null) => {
      const text = target?.dataset.railTip;
      if (!target || !text) {
        setTip(null);
        return;
      }
      const box = target.getBoundingClientRect();
      setTip({ text, top: box.top + box.height / 2, left: box.right + 10 });
    };
    const hide = () => setTip(null);
    const over = (event: PointerEvent) => {
      // Touch has no hover: a tap navigates, so it never leaves a label up.
      if (event.pointerType === "mouse") show(tipTarget(event.target));
    };
    const focus = (event: FocusEvent) => {
      const target = tipTarget(event.target);
      show(target?.matches(":focus-visible") ? target : null);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    node.addEventListener("pointerover", over);
    node.addEventListener("pointerleave", hide);
    node.addEventListener("pointerdown", hide);
    node.addEventListener("focusin", focus);
    node.addEventListener("focusout", hide);
    window.addEventListener("keydown", key);
    window.addEventListener("resize", hide);
    window.addEventListener("scroll", hide, true);
    return () => {
      node.removeEventListener("pointerover", over);
      node.removeEventListener("pointerleave", hide);
      node.removeEventListener("pointerdown", hide);
      node.removeEventListener("focusin", focus);
      node.removeEventListener("focusout", hide);
      window.removeEventListener("keydown", key);
      window.removeEventListener("resize", hide);
      window.removeEventListener("scroll", hide, true);
    };
  }, [rail]);

  if (!tip) return null;
  return createPortal(
    <span
      key={tip.text}
      className={styles.tip}
      style={{ top: tip.top, left: tip.left }}
      aria-hidden="true"
      data-rail-label=""
    >
      {tip.text}
    </span>,
    document.body,
  );
}
