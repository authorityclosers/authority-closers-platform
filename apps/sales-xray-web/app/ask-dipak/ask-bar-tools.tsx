"use client";

/**
 * Ask Dipak's Search in the phone's app bar (Dipak's spec, section 2: the
 * header's search): on the Ask Dipak tab it stands where the bar's search
 * is and opens his library's own Search. The bar keeps Home's set (+,
 * search, alerts), so the workspace's name has Home's room (owner, 16 Nov
 * 2026: "the name of the organization is lost" when a bookmark squeezed it
 * to "AC… S…"); Saved lessons opens from the greeting tile instead.
 */

import { Search } from "lucide-react";

import styles from "./ask-dipak.module.css";
import { COPY } from "./copy";
import { go } from "./nav";

export function AskBarTools({ className }: { className: string }) {
  return (
    <button
      type="button"
      className={`${className} ${styles.barTool}`}
      aria-label={COPY.searchTool}
      onClick={() => go({ kind: "search" })}
    >
      <Search size={20} aria-hidden="true" />
    </button>
  );
}
