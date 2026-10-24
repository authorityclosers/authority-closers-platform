"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

import { notify } from "../notice-center";
import { Button } from "../ui/kit";

/** Copies a command or snippet, and says so for two seconds. */
export function CopyButton({
  text,
  label,
  variant = "secondary",
}: {
  text: string;
  label: string;
  /** "primary" when copying is the screen's one main action. */
  variant?: "primary" | "secondary";
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <Button
      variant={variant}
      aria-label={copied ? `${label}: copied` : label}
      onClick={() => {
        const done = navigator.clipboard?.writeText(text);
        if (!done) {
          notify({
            id: "copy",
            tone: "error",
            title: "Couldn’t copy",
            message: "Select the text and copy it yourself.",
          });
          return;
        }
        void done.then(
          () => setCopied(true),
          () =>
            notify({
              id: "copy",
              tone: "error",
              title: "Couldn’t copy",
              message: "Select the text and copy it yourself.",
            }),
        );
      }}
    >
      {copied ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}
