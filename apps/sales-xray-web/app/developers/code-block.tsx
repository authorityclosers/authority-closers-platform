"use client";

/**
 * A code sample on /developers with a Copy button, and a set of samples in
 * tabs (curl, JavaScript, …) when there is more than one way to say it.
 */
import { useEffect, useId, useState } from "react";
import { Check, Copy } from "lucide-react";

import styles from "./developers.module.css";

function CopyCode({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      className={styles.copy}
      aria-label={copied ? `${label}: copied` : label}
      onClick={() =>
        void navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        )
      }
    >
      {copied ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function CodeBlock({ code, label }: { code: string; label: string }) {
  return (
    <div className={styles.block}>
      <div className={styles.blockHead}>
        <span>{label}</span>
        <CopyCode text={code} label={`Copy: ${label}`} />
      </div>
      <pre className={styles.code} tabIndex={0} aria-label={label}>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function CodeTabs({
  label,
  samples,
}: {
  label: string;
  samples: { key: string; label: string; code: string; note?: string }[];
}) {
  const id = useId();
  const [chosen, setChosen] = useState(samples[0]?.key);
  const sample = samples.find((item) => item.key === chosen) ?? samples[0];
  return (
    <div className={styles.block}>
      <div className={styles.blockHead}>
        <div className={styles.tabs} role="tablist" aria-label={label}>
          {samples.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              id={`${id}-${item.key}`}
              aria-selected={item.key === sample.key}
              aria-controls={`${id}-panel`}
              className={styles.tab}
              onClick={() => setChosen(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <CopyCode
          text={sample.code}
          label={`Copy: ${label}, ${sample.label}`}
        />
      </div>
      <div
        role="tabpanel"
        id={`${id}-panel`}
        aria-labelledby={`${id}-${sample.key}`}
      >
        {sample.note ? <p className={styles.tabNote}>{sample.note}</p> : null}
        <pre
          className={styles.code}
          tabIndex={0}
          aria-label={`${label}, ${sample.label}`}
        >
          <code>{sample.code}</code>
        </pre>
      </div>
    </div>
  );
}
