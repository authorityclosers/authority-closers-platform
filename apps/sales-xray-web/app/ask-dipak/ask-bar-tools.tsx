"use client";

/**
 * Ask Dipak's Search and Saved lessons in the phone's app bar (Dipak's spec,
 * section 2: the header's search and bookmark): on the Ask Dipak tab they
 * stand where the bar's search is, and open his library's own Search and
 * Saved lessons. The bookmark is lit while Saved lessons is open.
 */

import { Bookmark, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import styles from "./ask-dipak.module.css";
import { COPY } from "./copy";
import { go, parseView } from "./nav";

function Tools({ className, saved }: { className: string; saved: boolean }) {
  return (
    <>
      <button
        type="button"
        className={`${className} ${styles.barTool}`}
        aria-label={COPY.searchTool}
        onClick={() => go({ kind: "search" })}
      >
        <Search size={20} aria-hidden="true" />
      </button>
      <button
        type="button"
        className={`${className} ${styles.barTool}`}
        aria-label={COPY.savedTool}
        aria-current={saved ? "page" : undefined}
        onClick={() => go({ kind: "saved" })}
      >
        <Bookmark size={20} aria-hidden="true" />
      </button>
    </>
  );
}

function LiveTools({ className }: { className: string }) {
  const saved = parseView(useSearchParams()).kind === "saved";
  return <Tools className={className} saved={saved} />;
}

export function AskBarTools({ className }: { className: string }) {
  return (
    <Suspense fallback={<Tools className={className} saved={false} />}>
      <LiveTools className={className} />
    </Suspense>
  );
}
