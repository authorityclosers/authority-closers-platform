"use client";

import { Ellipsis, ExternalLink, Link2, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type FormEvent,
} from "react";

import { acquisition, record, submissionPath } from "../acquisition-client";
import { renameCall } from "../call-label-client";
import { clearCallFacts } from "../call-facts";
import { clearSpeakerProfiles } from "../speaker-profiles";
import type { ShellRecentCall } from "./shell-store";
import styles from "./recent-call-item.module.css";

const UNTITLED = "Untitled call";
const noSubscription = () => () => {};

/**
 * One call in the sidebar's Recents: hover reveals a ⋯ menu (rename, copy
 * link, open in a new tab, delete). Rename opens an inline editor.
 * Rename and delete use the same owner-scoped API as the rest of the app.
 */
export function RecentCallItem({
  call,
  href,
  onChange,
  index = 0,
}: {
  call: ShellRecentCall;
  href: string;
  /** Position in the list, for the staggered entrance. */
  index?: number;
  /** The updated call, or null once it has been deleted. */
  onChange: (next: ShellRecentCall | null) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  // The open call's row is highlighted; the path is read on every render.
  const pathname = useSyncExternalStore(
    noSubscription,
    () => window.location.pathname,
    () => null,
  );
  const current =
    pathname !== null &&
    href.includes(call.id) &&
    pathname === new URL(href, "https://sales-xray.invalid").pathname;
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [copied, setCopied] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  // Enter submits and the input then loses focus: save only once.
  const saving = useRef(false);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !rowRef.current?.contains(event.target)
      ) {
        setMenuOpen(false);
        setConfirmingDelete(false);
      }
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      setConfirmingDelete(false);
      moreRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!editing) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  function startRename() {
    setMenuOpen(false);
    setConfirmingDelete(false);
    setProblem("");
    setEditing(true);
  }

  async function saveRename(event?: FormEvent) {
    event?.preventDefault();
    if (saving.current) return;
    const typed = inputRef.current?.value.trim() ?? "";
    const current = call.name === UNTITLED ? "" : call.name;
    if (typed === current) {
      setEditing(false);
      return;
    }
    saving.current = true;
    setBusy(true);
    try {
      const label = await renameCall(
        call.id,
        typed || null,
        call.revision ?? 0,
      );
      onChange({
        ...call,
        name: label.displayName ?? UNTITLED,
        revision: label.revision,
      });
      setEditing(false);
      setProblem("");
    } catch {
      setProblem("Couldn’t rename this call. Try again.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(
        new URL(href, window.location.origin).toString(),
      );
      setCopied(true);
      window.setTimeout(() => {
        setCopied(false);
        setMenuOpen(false);
      }, 900);
    } catch {
      setProblem("Couldn’t copy the link.");
    }
  }

  async function deleteCall() {
    if (busy) return;
    setBusy(true);
    try {
      const deleted = record(
        await acquisition(submissionPath(call.id), {
          method: "DELETE",
          headers: { "Idempotency-Key": `delete:${call.id}` },
        }),
      );
      if (!["deleting", "deleted"].includes(String(deleted.state)))
        throw new Error("delete_unconfirmed");
      clearCallFacts(call.id);
      clearSpeakerProfiles(call.id);
      setMenuOpen(false);
      // A full navigation discards the deleted report and its playback state.
      if (
        window.location.pathname ===
        new URL(href, window.location.origin).pathname
      )
        window.location.replace("/analysis/calls");
      onChange(null);
    } catch {
      setProblem("Couldn’t delete this call. Try again.");
      setBusy(false);
    }
  }

  return (
    <div
      ref={rowRef}
      className={styles.row}
      style={{ "--i": index } as CSSProperties}
      data-menu-open={menuOpen || undefined}
      data-editing={editing || undefined}
    >
      {editing ? (
        <form className={styles.renameForm} onSubmit={saveRename}>
          <span
            className={styles.mark}
            data-tone={call.tone ?? "idle"}
            aria-hidden="true"
          >
            {call.tone === "active" ? (
              <>
                <i />
                <i />
                <i />
              </>
            ) : (
              <i />
            )}
          </span>
          <input
            ref={inputRef}
            className={styles.renameInput}
            defaultValue={call.name === UNTITLED ? "" : call.name}
            placeholder={UNTITLED}
            maxLength={120}
            aria-label="Call name"
            aria-invalid={problem ? true : undefined}
            disabled={busy}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setEditing(false);
                setProblem("");
              }
            }}
            onBlur={() => void saveRename()}
          />
        </form>
      ) : (
        <Link
          href={href}
          className={styles.link}
          title={call.status ? `${call.name} · ${call.status}` : call.name}
          data-current={current ? "" : undefined}
          aria-current={current ? "page" : undefined}
        >
          <span
            className={styles.mark}
            data-tone={call.tone ?? "idle"}
            aria-hidden="true"
          >
            {call.tone === "active" ? (
              <>
                <i />
                <i />
                <i />
              </>
            ) : (
              <i />
            )}
          </span>
          <span className={styles.name}>{call.name}</span>
          {call.status && <span className={styles.srOnly}>{call.status}</span>}
          <span className={styles.date}>{call.date}</span>
        </Link>
      )}
      {!editing && (
        <button
          ref={moreRef}
          type="button"
          className={styles.more}
          aria-label={`More options for ${call.name}`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => {
            setMenuOpen((open) => !open);
            setConfirmingDelete(false);
            setProblem("");
          }}
        >
          <Ellipsis size={16} aria-hidden="true" />
        </button>
      )}
      {menuOpen && (
        <div className={styles.menu} role="menu" aria-label={call.name}>
          {confirmingDelete ? (
            <div className={styles.confirm}>
              <p>Delete this call and its report?</p>
              <div className={styles.confirmActions}>
                <button
                  type="button"
                  role="menuitem"
                  className={styles.danger}
                  disabled={busy}
                  onClick={() => void deleteCall()}
                >
                  {busy ? "Deleting…" : "Delete"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={busy}
                  onClick={() => setConfirmingDelete(false)}
                >
                  Keep
                </button>
              </div>
            </div>
          ) : (
            <>
              <button type="button" role="menuitem" onClick={startRename}>
                <Pencil size={14} aria-hidden="true" />
                Rename
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => void copyLink()}
              >
                <Link2 size={14} aria-hidden="true" />
                {copied ? "Link copied" : "Copy link"}
              </button>
              <a
                role="menuitem"
                href={href}
                target="_blank"
                rel="noreferrer"
                onClick={() => setMenuOpen(false)}
              >
                <ExternalLink size={14} aria-hidden="true" />
                Open in new tab
              </a>
              <span className={styles.separator} aria-hidden="true" />
              <button
                type="button"
                role="menuitem"
                className={styles.dangerItem}
                onClick={() => setConfirmingDelete(true)}
              >
                <Trash2 size={14} aria-hidden="true" />
                Delete…
              </button>
            </>
          )}
        </div>
      )}
      {problem && (
        <p className={styles.problem} role="status">
          {problem}
        </p>
      )}
    </div>
  );
}
