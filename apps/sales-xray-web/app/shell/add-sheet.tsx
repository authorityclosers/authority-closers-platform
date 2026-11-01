"use client";

/**
 * The phone tab bar's + (owner, 22 Oct 2026): "nobody wants call analysis in
 * that way". It opens one small sheet with the two things people add, a lead
 * or a call, instead of jumping straight to call analysis. Owner, confirmed:
 * "the + pop-up has Add lead and Add a call (record or upload a call for
 * analysis)".
 *
 * The 28 Oct 2026 meeting moved the + to the top bar and added Add task: a
 * reminder on a lead. It opens the Add task form over the current screen
 * (owner order, 30 Oct 2026, fix 4: it used to open nothing).
 *
 * Add lead opens the quick form over the current screen; Add a call goes to
 * the record-or-upload page. Outside an organisation there is no lead desk,
 * so Add lead says where leads live and opens Leads, which offers the switch.
 */

import {
  AudioLines,
  ChevronRight,
  FileSpreadsheet,
  ListChecks,
  UserPlus,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Sheet } from "../ui/sheet";
import styles from "./add-sheet.module.css";

function Choice({
  icon,
  tone,
  title,
  text,
  href,
  onClick,
}: {
  icon: ReactNode;
  tone: "lead" | "call" | "task";
  title: string;
  text: string;
  href?: string;
  onClick: () => void;
}) {
  const inner = (
    <>
      <span className={styles.icon} data-tone={tone} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.words}>
        <strong>{title}</strong>
        <small>{text}</small>
      </span>
      <ChevronRight className={styles.chevron} size={18} aria-hidden="true" />
    </>
  );
  return href ? (
    <Link className={styles.choice} href={href} onClick={onClick}>
      {inner}
    </Link>
  ) : (
    <button type="button" className={styles.choice} onClick={onClick}>
      {inner}
    </button>
  );
}

export function AddSheet({
  open,
  onClose,
  onAddLead,
  onAddTask,
  callHref,
  leadsHere,
  canImport = false,
}: {
  open: boolean;
  onClose: () => void;
  /** Opens the quick Add lead form; only inside an organisation. */
  onAddLead: () => void;
  /** Opens the Add task form; only inside an organisation. */
  onAddTask: () => void;
  /** The record-or-upload page. */
  callHref: string;
  /** False outside an organisation: Add lead then opens Leads instead. */
  leadsHere: boolean;
  /** Owners and admins import a file of leads from here (ph1-15, 1 Nov 2026:
   *  it was ten taps deep). */
  canImport?: boolean;
}) {
  // Handing over to a form: the + sheet closes while the form loads, so a
  // clear shield takes the moment's taps (a double tap's second one fell
  // through to the tab bar's Ask Dipak), and the row takes one tap only.
  const [shield, setShield] = useState(false);
  const handing = useRef<string | null>(null);
  useEffect(() => {
    if (!shield) return;
    const timer = window.setTimeout(() => {
      setShield(false);
      handing.current = null;
    }, 600);
    return () => window.clearTimeout(timer);
  }, [shield]);
  const handOver = (row: string, open: () => void) => {
    if (handing.current === row) return;
    handing.current = row;
    setShield(true);
    open();
  };
  return (
    <>
      {shield && typeof document !== "undefined"
        ? createPortal(
            <div
              className={styles.shield}
              data-tap-shield=""
              aria-hidden="true"
            />,
            document.body,
          )
        : null}
      <Sheet open={open} onClose={onClose} title="Add" wide="center">
        <div className={styles.choices}>
          {leadsHere ? (
            <Choice
              icon={<UserPlus size={22} />}
              tone="lead"
              title="Add lead"
              text="A name and a number is enough"
              onClick={() => handOver("lead", onAddLead)}
            />
          ) : (
            <Choice
              icon={<UserPlus size={22} />}
              tone="lead"
              title="Add lead"
              text="Leads live in your organisation"
              href="/leads"
              onClick={onClose}
            />
          )}
          <Choice
            icon={<AudioLines size={22} />}
            tone="call"
            title="Add a call"
            text="Record or upload a call for analysis"
            href={callHref}
            onClick={onClose}
          />
          {leadsHere && canImport ? (
            <Choice
              icon={<FileSpreadsheet size={22} />}
              tone="lead"
              title="Import leads"
              text="A file of leads, up to 2,000 at once"
              href="/leads?import=file"
              onClick={onClose}
            />
          ) : null}
          {leadsHere ? (
            <Choice
              icon={<ListChecks size={22} />}
              tone="task"
              title="Add task"
              text="A reminder on a lead, on its day"
              onClick={() => handOver("task", onAddTask)}
            />
          ) : null}
        </div>
      </Sheet>
    </>
  );
}
