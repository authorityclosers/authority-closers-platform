"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { displayName, shortName } from "../../display-name";
import styles from "./person-display-name.module.css";

/** One measured, single-line name for person headers and People rows. */
export function PersonDisplayName({ name }: { name: string }) {
  const full = displayName(name);
  const short = shortName(name);
  const initials = full
    .split(/\s+/)
    .map((part) => [...part][0])
    .filter(Boolean)
    .slice(0, 2)
    .join("");
  const [label, setLabel] = useState(full);
  const box = useRef<HTMLSpanElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const measure = () => {
      if (!box.current || !probe.current) return;
      const width = box.current.clientWidth;
      if (!width) return;
      for (const candidate of [full, short, initials]) {
        probe.current.textContent = candidate;
        if (probe.current.offsetWidth <= width) {
          setLabel(candidate);
          return;
        }
      }
      setLabel(initials);
    };
    measure();
    if (typeof ResizeObserver === "undefined" || !box.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(box.current);
    return () => observer.disconnect();
  }, [full, short, initials]);
  return (
    <span ref={box} className={styles.name} aria-label={full} title={full}>
      <span aria-hidden="true">{label}</span>
      <span ref={probe} className={styles.probe} aria-hidden="true" />
    </span>
  );
}
