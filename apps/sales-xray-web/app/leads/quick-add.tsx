"use client";

/**
 * Quick add (owner P0, 23 Oct 2026: "typing to add"): a name, Tab, a number,
 * Enter, and the lead is in; the line empties for the next one. In the table it
 * is the last line, its boxes under Name and Phone; on phones (and an empty
 * list) it sits above the list. A number that is already a lead says so while
 * it is typed, as Add lead does, and the lead rules pick the owner.
 */

import { Plus } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { LeadsError, addLead, matchLead, type LeadMatch } from "./leads-client";
import styles from "./leads-table.module.css";

type QuickAdd = {
  name: string;
  phone: string;
  setName: (value: string) => void;
  setPhone: (value: string) => void;
  busy: boolean;
  /** Already a lead: why Add waits. */
  hint: string | null;
  canAdd: boolean;
  submit: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
};

function useQuickAdd(
  pipeline: string | null,
  onAdded: () => void,
): [QuickAdd, RefObject<HTMLInputElement | null>] {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [match, setMatch] = useState<{
    phone: string;
    value: LeadMatch;
  } | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const digits = phone.replace(/\D/g, "").length;
  useEffect(() => {
    if (digits < 10) return;
    const asked = phone;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      matchLead(asked, controller.signal).then(
        (value) => setMatch({ phone: asked, value }),
        () => undefined,
      );
    }, 400);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [phone, digits]);
  const existing =
    match && match.phone === phone && match.value.found ? match.value : null;
  const hint = existing
    ? existing.name
      ? `Already a lead: ${displayName(existing.name)}${existing.stage_label ? ` · ${existing.stage_label}` : ""}`
      : "Already a teammate's lead"
    : null;
  const canAdd = !busy && name.trim().length > 0 && existing === null;

  const submit = () => {
    if (!canAdd) return;
    setBusy(true);
    addLead({
      source: "manual",
      name: name.trim(),
      phone: phone.trim() || undefined,
      assign: "rules",
      ...(pipeline ? { pipeline } : {}),
    })
      .then(
        () => {
          setName("");
          setPhone("");
          setMatch(null);
          onAdded();
          nameRef.current?.focus();
        },
        (reason: unknown) =>
          notify({
            id: "quick-add",
            tone: "error",
            title: "That lead wasn't added",
            message:
              reason instanceof LeadsError ? reason.message : "Try again.",
          }),
      )
      .finally(() => setBusy(false));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape" && (name || phone)) {
      event.preventDefault();
      setName("");
      setPhone("");
    }
  };

  return [
    { name, phone, setName, setPhone, busy, hint, canAdd, submit, onKeyDown },
    nameRef,
  ];
}

function NameBox({
  add,
  inputRef,
}: {
  add: QuickAdd;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  return (
    <input
      ref={inputRef}
      className={styles.quickInput}
      value={add.name}
      onChange={(event) => add.setName(event.target.value)}
      onKeyDown={add.onKeyDown}
      placeholder="New lead's name"
      aria-label="New lead's name"
      autoComplete="off"
      maxLength={200}
    />
  );
}

function PhoneBox({ add }: { add: QuickAdd }) {
  return (
    <input
      className={styles.quickInput}
      value={add.phone}
      onChange={(event) => add.setPhone(event.target.value)}
      onKeyDown={add.onKeyDown}
      placeholder="Phone"
      aria-label="New lead's phone"
      type="tel"
      inputMode="tel"
      autoComplete="off"
      maxLength={40}
    />
  );
}

function AddButton({ add }: { add: QuickAdd }) {
  return (
    <button
      type="button"
      className={styles.quickButton}
      onClick={add.submit}
      disabled={!add.canAdd}
    >
      <Plus size={14} aria-hidden="true" />
      {add.busy ? "Adding…" : "Add"}
    </button>
  );
}

/** The table's last line: boxes under Name and Phone, Add at its end. */
export function QuickAddRow({
  pipeline,
  onAdded,
  before,
  after,
}: {
  pipeline: string | null;
  onAdded: () => void;
  /** Columns ahead of Name (the tick column while selecting). */
  before: number;
  /** Columns after Phone and Stage (the phone box spans both: a whole
      number needs more room than the Phone column's last four digits). */
  after: number;
}) {
  const [add, nameRef] = useQuickAdd(pipeline, onAdded);
  return (
    <tr className={styles.quickRow}>
      {before ? <td colSpan={before} /> : null}
      <td data-column="name">
        <NameBox add={add} inputRef={nameRef} />
      </td>
      <td colSpan={2}>
        <PhoneBox add={add} />
      </td>
      <td colSpan={after}>
        <span className={styles.quickEnd}>
          {add.hint ? (
            <small className={styles.quickHint} role="status">
              {add.hint}
            </small>
          ) : null}
          <AddButton add={add} />
        </span>
      </td>
    </tr>
  );
}

/** Above the list (phones, or nothing listed yet): the same boxes in a line. */
export function QuickAddBar({
  pipeline,
  onAdded,
}: {
  pipeline: string | null;
  onAdded: () => void;
}) {
  const [add, nameRef] = useQuickAdd(pipeline, onAdded);
  return (
    <div className={styles.quickAdd} role="group" aria-label="Add a lead">
      <NameBox add={add} inputRef={nameRef} />
      <PhoneBox add={add} />
      <AddButton add={add} />
      {add.hint ? (
        <small className={styles.quickHint} role="status">
          {add.hint}
        </small>
      ) : null}
    </div>
  );
}
