import { DEVANAGARI } from "../lib/script";
import { QUIET_KEYS, humanKey } from "./synthetic-data";
import styles from "./synthetic.module.css";

/** Any answer-key value, readable: objects as labelled rows, lists as lists. */
export function AnswerTree({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === null || value === undefined || value === "")
    return <span className={styles.none}>—</span>;
  if (typeof value === "string")
    return (
      <span data-script={DEVANAGARI.test(value) ? "deva" : undefined}>
        {value}
      </span>
    );
  if (typeof value === "number" || typeof value === "boolean")
    return <span>{String(value)}</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <span className={styles.none}>None</span>;
    if (value.every((item) => typeof item !== "object" || item === null))
      return <span>{value.map(String).join(" · ")}</span>;
    return (
      <ol className={styles.list}>
        {value.map((item, index) => (
          <li key={index}>
            <AnswerTree value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([key]) => !QUIET_KEYS.has(key),
    );
    if (depth > 6) return <span className={styles.none}>…</span>;
    return (
      <dl className={styles.tree}>
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{humanKey(key)}</dt>
            <dd>
              <AnswerTree value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return null;
}
