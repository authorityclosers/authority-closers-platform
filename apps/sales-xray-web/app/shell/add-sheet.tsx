"use client";

/**
 * The phone tab bar's + (owner, 22 Oct 2026): "nobody wants call analysis in
 * that way". It opens one small sheet with the two things people add, a lead
 * or a call, instead of jumping straight to call analysis.
 *
 * Add lead opens the quick form over the current screen; Add a call goes to
 * the record-or-upload page. Outside an organisation there is no lead desk,
 * so Add lead says where leads live and opens Leads, which offers the switch.
 */

import { AudioLines, ChevronRight, UserPlus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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
  tone: "lead" | "call";
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
  callHref,
  leadsHere,
}: {
  open: boolean;
  onClose: () => void;
  /** Opens the quick Add lead form; only inside an organisation. */
  onAddLead: () => void;
  /** The record-or-upload page. */
  callHref: string;
  /** False outside an organisation: Add lead then opens Leads instead. */
  leadsHere: boolean;
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Add" wide="center">
      <div className={styles.choices}>
        {leadsHere ? (
          <Choice
            icon={<UserPlus size={22} />}
            tone="lead"
            title="Add lead"
            text="A name and a number is enough"
            onClick={onAddLead}
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
          text="Record or upload a call for its report"
          href={callHref}
          onClick={onClose}
        />
      </div>
    </Sheet>
  );
}
