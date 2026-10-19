"use client";

/**
 * The lead beside the chat: who they are, where they came from, who has them,
 * their notes, and one Call button. On a computer it sits to the right of the
 * chat; on a phone it opens as a sheet from the bottom. Calls go through the
 * lead desk (/leads#lead=<id>&call=1), so every call is logged the same way.
 */

import { ExternalLink, Phone, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { sourceText } from "../leads/desk-view";
import {
  addNote,
  ago,
  displayPhone,
  LeadsError,
  readLead,
  reassign,
  when,
  type LeadDetail,
} from "../leads/leads-client";
import { notify } from "../notice-center";
import { Avatar, Badge, Skeleton } from "../ui/kit";
import styles from "./chats.module.css";

const NOTES_SHOWN = 5;

function PanelSkeleton() {
  return (
    <div className={styles.panelBody} aria-hidden="true">
      <div className={styles.panelHead}>
        <Skeleton width={52} height={52} />
        <span>
          <Skeleton width="70%" height={16} />
          <Skeleton width="50%" height={20} />
        </span>
      </div>
      <Skeleton height={48} />
      {[0, 1, 2, 3].map((key) => (
        <Skeleton key={key} height={14} width={`${80 - key * 10}%`} />
      ))}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Owner({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const [busy, setBusy] = useState(false);
  const lead = detail.lead;
  if (!detail.can_assign) return <>{lead.owner_name ?? "Not assigned yet"}</>;
  return (
    <select
      className={styles.ownerSelect}
      aria-label="Who has this lead"
      value={lead.owner_person_id ?? ""}
      disabled={busy}
      onChange={async (event) => {
        setBusy(true);
        try {
          onChanged(await reassign(lead, event.target.value || null));
        } catch (reason) {
          notify({
            id: "chats-reassign",
            tone: "error",
            title: "Not moved",
            message:
              reason instanceof LeadsError
                ? reason.message
                : "That didn't work. Try again.",
          });
        } finally {
          setBusy(false);
        }
      }}
    >
      {!lead.owner_person_id ? (
        <option value="">Not assigned yet</option>
      ) : null}
      {lead.owner_person_id &&
      !detail.reps.some((rep) => rep.person_id === lead.owner_person_id) ? (
        <option value={lead.owner_person_id}>{lead.owner_name}</option>
      ) : null}
      {detail.reps.map((rep) => (
        <option key={rep.person_id} value={rep.person_id}>
          {rep.name}
          {rep.available ? "" : " (away)"}
        </option>
      ))}
    </select>
  );
}

function Notes({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const notes = detail.events
    .filter((event) => event.kind === "note" && event.note)
    .sort((a, b) => (a.at < b.at ? 1 : -1))
    .slice(0, NOTES_SHOWN);
  const save = async () => {
    const words = text.trim();
    if (!words) return;
    setBusy(true);
    try {
      onChanged(await addNote(detail.lead.lead_id, words));
      setText("");
    } catch (reason) {
      notify({
        id: "chats-note",
        tone: "error",
        title: "Note not saved",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={styles.panelNotes} aria-label="Notes">
      <h3>Notes</h3>
      {detail.can_edit ? (
        <div className={styles.noteBox}>
          <textarea
            aria-label="Add a note"
            placeholder="Add a note"
            rows={2}
            maxLength={2000}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          {text.trim() ? (
            <button
              type="button"
              className={styles.noteSave}
              disabled={busy}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save note"}
            </button>
          ) : null}
        </div>
      ) : null}
      {notes.length ? (
        <ol>
          {notes.map((note, index) => (
            <li key={`${note.at}-${index}`}>
              <p>{note.note}</p>
              <small>
                {note.actor_name ? `${note.actor_name} · ` : ""}
                {ago(note.at)}
              </small>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.panelQuiet}>No notes yet.</p>
      )}
    </section>
  );
}

export function LeadPanel({
  leadId,
  onClose,
}: {
  leadId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    readLead(leadId, controller.signal)
      .then((next) => {
        setDetail(next);
        setFailed(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setFailed(
          reason instanceof LeadsError
            ? reason.message
            : "This lead didn't load. Try again.",
        );
      });
    return () => controller.abort();
  }, [leadId, round]);

  const close = (
    <button
      type="button"
      className={styles.panelClose}
      aria-label="Close the lead"
      title="Close"
      onClick={onClose}
    >
      <X size={18} aria-hidden="true" />
    </button>
  );

  if (!detail)
    return (
      <div className={styles.panel}>
        {close}
        {failed ? (
          <div className={styles.listEmpty}>
            <p className={styles.emptyTitle}>{failed}</p>
            <button
              type="button"
              className={styles.linkButton}
              onClick={() => setRound((value) => value + 1)}
            >
              Try again
            </button>
          </div>
        ) : (
          <PanelSkeleton />
        )}
      </div>
    );

  const lead = detail.lead;
  const extra = detail.fields.filter(
    (field) => !["phone", "email", "name"].includes(field.label.toLowerCase()),
  );
  const leadHref = `/leads#lead=${encodeURIComponent(lead.lead_id)}`;
  return (
    <div className={styles.panel}>
      {close}
      <div className={styles.panelBody}>
        <div className={styles.panelHead}>
          <Avatar name={lead.name} size={52} />
          <span>
            <strong>{lead.name}</strong>
            <span className={styles.panelBadges}>
              <Badge
                tone={
                  lead.stage === "won"
                    ? "good"
                    : lead.stage === "lost"
                      ? "bad"
                      : "accent"
                }
              >
                {lead.stage_label}
              </Badge>
              {lead.test_data ? <Badge>Test lead</Badge> : null}
            </span>
          </span>
        </div>

        {detail.phone ? (
          <Link
            className={styles.callAction}
            href={`${leadHref}&call=1`}
            prefetch={false}
          >
            <Phone size={18} aria-hidden="true" />
            <span>
              <strong>Call</strong>
              <small>{displayPhone(detail.phone)}</small>
            </span>
          </Link>
        ) : (
          <p className={styles.panelQuiet}>
            No phone number yet. Ask for it in the chat, then add it on the
            lead.
          </p>
        )}

        <dl className={styles.facts}>
          {detail.phone ? (
            <Fact label="Phone">
              <a href={`tel:${detail.phone}`}>{displayPhone(detail.phone)}</a>
            </Fact>
          ) : null}
          {detail.email ? (
            <Fact label="Email">
              <a href={`mailto:${detail.email}`}>{detail.email}</a>
            </Fact>
          ) : null}
          <Fact label="Came from">{sourceText(lead)}</Fact>
          <Fact label="With">
            <Owner detail={detail} onChanged={setDetail} />
          </Fact>
          {lead.next_action_at ? (
            <Fact label="Next call">{when(lead.next_action_at)}</Fact>
          ) : null}
          {extra.slice(0, 6).map((field) => (
            <Fact key={field.label} label={field.label}>
              {field.value}
            </Fact>
          ))}
        </dl>

        <Notes detail={detail} onChanged={setDetail} />

        <Link className={styles.panelLink} href={leadHref} prefetch={false}>
          <ExternalLink size={14} aria-hidden="true" />
          Open the full lead
        </Link>
      </div>
    </div>
  );
}

/** On a phone: the same panel in a sheet from the bottom of the screen. */
export function LeadSheetDialog({
  leadId,
  onClose,
}: {
  leadId: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className={styles.sheet}
      aria-label="Lead"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <span className={styles.sheetGrip} aria-hidden="true" />
      <LeadPanel leadId={leadId} onClose={onClose} />
    </dialog>
  );
}
