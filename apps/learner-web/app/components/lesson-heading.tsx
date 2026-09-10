import { CirclePlay } from "lucide-react";
import styles from "./lesson-heading.module.css";

/** A compact lesson identity, shared by live playback and lesson previews. */
export function LessonHeading({
  id,
  title,
  stepLabel,
  stateLabel,
}: {
  id: string;
  title: string;
  stepLabel: string;
  stateLabel: string;
}) {
  return (
    <header className={styles.heading}>
      <div className={styles.meta}>
        <span className={styles.step}>
          <CirclePlay size={18} aria-hidden="true" />
          Video lesson <span aria-hidden="true">·</span> {stepLabel}
        </span>
        <span className={styles.state}>{stateLabel}</span>
      </div>
      <h1 id={id}>{title}</h1>
    </header>
  );
}
