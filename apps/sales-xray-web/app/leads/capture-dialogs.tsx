"use client";

/**
 * Adding leads: one "Add leads" menu with the ways people actually have
 * them — type one in (pasting a WhatsApp message fills the form), pick from
 * the phone's contacts, upload a list, or connect Facebook. Repeat phone
 * numbers join their existing lead instead of making a second one.
 *
 * The page gives each opening a new key, so every dialog starts empty.
 */

import {
  ClipboardPaste,
  Contact,
  FileSpreadsheet,
  Keyboard,
  Megaphone,
  Plus,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Button, Dialog, Field, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  addLead,
  commandId,
  commitImport,
  contactsSupported,
  FIELD_LABELS,
  LeadsError,
  parseContactText,
  pickContacts,
  previewImport,
  SAMPLE_CSV,
  type ImportPreview,
  type ImportResult,
  type NewLead,
  type PickedContact,
  type SharedLead,
} from "./leads-client";
import styles from "./leads.module.css";

export type AddWay = "type" | "contacts" | "file" | "sources";

function WayButton({
  icon,
  title,
  text,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className={styles.wayButton} onClick={onClick}>
      <span className={styles.wayIcon} aria-hidden="true">
        {icon}
      </span>
      <span>
        <strong>{title}</strong>
        <small>{text}</small>
      </span>
    </button>
  );
}

export function AddLeadsMenu({
  open,
  canManage,
  onClose,
  onPick,
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onPick: (way: AddWay) => void;
}) {
  const contacts = contactsSupported();
  return (
    <Dialog open={open} title="Add leads" onClose={onClose}>
      <div className={styles.ways}>
        <WayButton
          icon={<Keyboard size={22} />}
          title="Type one in"
          text="Or paste a WhatsApp message and we fill it in"
          onClick={() => onPick("type")}
        />
        {contacts ? (
          <WayButton
            icon={<Contact size={22} />}
            title="From your phone's contacts"
            text="Pick one or many people you already have"
            onClick={() => onPick("contacts")}
          />
        ) : null}
        {canManage ? (
          <WayButton
            icon={<FileSpreadsheet size={22} />}
            title="Upload a list"
            text="Excel or CSV, up to 2,000 leads at once"
            onClick={() => onPick("file")}
          />
        ) : null}
        {canManage ? (
          <WayButton
            icon={<Megaphone size={22} />}
            title="From your ads"
            text="Connect Facebook and Instagram lead forms"
            onClick={() => onPick("sources")}
          />
        ) : null}
      </div>
    </Dialog>
  );
}

const EMPTY = {
  name: "",
  phone: "",
  email: "",
  company: "",
  city: "",
  language: "",
  interest: "",
  referred_by: "",
  note: "",
};

export function AddLeadDialog({
  open,
  canManage,
  onClose,
  onAdded,
  initial = null,
  initialNote = "From the Sales Xray extension. Check the details, then add the lead.",
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onAdded: (leadId: string) => void;
  /** Details handed over by the Chrome extension; the person still checks and adds. */
  initial?: SharedLead | null;
  /** Where the filled-in details came from (the extension, or a work call on the phone). */
  initialNote?: string;
}) {
  const [form, setForm] = useState(() =>
    initial ? { ...EMPTY, ...initial } : EMPTY,
  );
  const [source, setSource] = useState<"manual" | "referral">("manual");
  const [assign, setAssign] = useState<"rules" | "me">(
    canManage ? "rules" : "me",
  );
  const [more, setMore] = useState(Boolean(initial?.email || initial?.note));
  const [pasting, setPasting] = useState(false);
  const [paste, setPaste] = useState("");
  const [pasteNote, setPasteNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const command = useRef(commandId());
  const nameRef = useRef<HTMLInputElement>(null);
  const formId = useId();
  const contacts = contactsSupported();

  // Owner, 22 Oct: adding a lead must be low effort. An empty form starts in
  // the name box with the keyboard up; a filled-in one waits to be checked.
  useEffect(() => {
    if (!open || initial) return;
    const frame = window.requestAnimationFrame(() => nameRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, initial]);

  const set =
    (key: keyof typeof EMPTY) => (event: { target: { value: string } }) =>
      setForm((current) => ({ ...current, [key]: event.target.value }));

  const fillFrom = (text: string) => {
    const found = parseContactText(text);
    const filled = Object.entries(found).filter(([, value]) => value);
    if (!filled.length) {
      setPasteNote("No name, phone or email found in that text.");
      return;
    }
    setForm((current) => ({
      ...current,
      name: found.name ?? current.name,
      phone: found.phone ?? current.phone,
      email: found.email ?? current.email,
    }));
    if (found.email) setMore(true);
    setPasteNote(`Filled in ${filled.map(([key]) => key).join(", ")}.`);
  };

  // One person from the phone's contacts fills the form; nothing is saved
  // until Add lead.
  const fromContacts = () => {
    pickContacts()
      .then(([person]) => {
        if (!person) return;
        setForm((current) => ({
          ...current,
          name: person.name || current.name,
          phone: person.phone || current.phone,
          email: person.email ?? current.email,
        }));
      })
      .catch(() => undefined);
  };

  const save = async () => {
    if (!form.name.trim() && !form.phone.trim()) {
      setError("Add a name or a phone number.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const lead: NewLead = {
        ...form,
        name: form.name.trim() || form.phone.trim(),
        source,
        assign,
        referred_by: source === "referral" ? form.referred_by : undefined,
      };
      const detail = await addLead(lead, command.current);
      onAdded(detail.lead.lead_id);
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not added. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet
      open={open}
      title="Add a lead"
      onClose={onClose}
      wide="center"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            type="submit"
            form={formId}
            disabled={saving}
          >
            {saving ? "Adding…" : "Add lead"}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {initial ? (
          <p className={styles.hint} role="status">
            {initialNote}
          </p>
        ) : null}
        <div className={styles.quickFields}>
          <Field label="Name">
            <input
              ref={nameRef}
              value={form.name}
              maxLength={200}
              onChange={set("name")}
              autoComplete="off"
              autoCapitalize="words"
              enterKeyHint="next"
            />
          </Field>
          <Field label="Phone">
            <input
              value={form.phone}
              maxLength={40}
              type="tel"
              inputMode="tel"
              placeholder="98765 43210"
              onChange={set("phone")}
              autoComplete="off"
              enterKeyHint="done"
            />
          </Field>
        </div>
        <div className={styles.quickHelpers}>
          {contacts ? (
            <button
              type="button"
              className={styles.helperChip}
              onClick={fromContacts}
            >
              <Contact size={15} aria-hidden="true" />
              From contacts
            </button>
          ) : null}
          <button
            type="button"
            className={styles.helperChip}
            aria-expanded={pasting}
            onClick={() => setPasting((value) => !value)}
          >
            <ClipboardPaste size={15} aria-hidden="true" />
            Paste a message
          </button>
          {more ? null : (
            <button
              type="button"
              className={styles.helperChip}
              onClick={() => setMore(true)}
            >
              <Plus size={15} aria-hidden="true" />
              More details
            </button>
          )}
        </div>
        {pasting ? (
          <div className={styles.pasteBox}>
            <textarea
              aria-label="Paste a contact or message"
              rows={2}
              value={paste}
              maxLength={2000}
              placeholder="Paste a WhatsApp message or contact card here"
              onChange={(event) => {
                setPaste(event.target.value);
                setPasteNote(null);
              }}
              onPaste={(event) => {
                const text = event.clipboardData.getData("text");
                if (text) window.setTimeout(() => fillFrom(text), 0);
              }}
            />
            <Button onClick={() => fillFrom(paste)} disabled={!paste.trim()}>
              Fill in
            </Button>
            {pasteNote ? (
              <p className={styles.hint} role="status">
                {pasteNote}
              </p>
            ) : null}
          </div>
        ) : null}
        {more ? (
          <div className={styles.formGrid}>
            <Field label="Interested in">
              <input
                value={form.interest}
                maxLength={200}
                onChange={set("interest")}
              />
            </Field>
            <Field label="City">
              <input value={form.city} maxLength={120} onChange={set("city")} />
            </Field>
            <Field label="Email">
              <input
                value={form.email}
                maxLength={320}
                inputMode="email"
                onChange={set("email")}
              />
            </Field>
            <Field label="Company">
              <input
                value={form.company}
                maxLength={200}
                onChange={set("company")}
              />
            </Field>
            <Field label="Language">
              <input
                value={form.language}
                maxLength={40}
                placeholder="Hindi"
                onChange={set("language")}
              />
            </Field>
            {source === "referral" ? (
              <Field label="Referred by">
                <input
                  value={form.referred_by}
                  maxLength={200}
                  onChange={set("referred_by")}
                />
              </Field>
            ) : null}
            <Field label="Note" wide>
              <textarea
                value={form.note}
                maxLength={1000}
                onChange={set("note")}
              />
            </Field>
            <div className={styles.formWide}>
              <Segmented
                label="Where it came from"
                value={source}
                onChange={setSource}
                items={[
                  { key: "manual", label: "Walk-in or call" },
                  { key: "referral", label: "Referral" },
                ]}
              />
            </div>
          </div>
        ) : null}
        {canManage ? (
          <Segmented
            label="Who gets it"
            value={assign}
            onChange={setAssign}
            items={[
              { key: "rules", label: "Best fit by the rules" },
              { key: "me", label: "Me" },
            ]}
          />
        ) : null}
        <p className={styles.hint}>
          {canManage
            ? "A number you already have joins that lead."
            : "It goes on your desk. A number you already have joins that lead."}
        </p>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </Sheet>
  );
}

export function ContactsDialog({
  open,
  picked,
  canManage,
  onClose,
  onDone,
}: {
  open: boolean;
  picked: PickedContact[];
  canManage: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [chosen, setChosen] = useState(() => picked.map(() => true));
  const [assign, setAssign] = useState<"rules" | "me">(
    canManage ? "rules" : "me",
  );
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<number | null>(null);
  const [failed, setFailed] = useState<string[]>([]);
  const count = chosen.filter(Boolean).length;

  const run = async () => {
    setBusy(true);
    const misses: string[] = [];
    let made = 0;
    for (const [index, person] of picked.entries()) {
      if (!chosen[index]) continue;
      try {
        await addLead({
          ...EMPTY,
          name: person.name || person.phone,
          phone: person.phone,
          email: person.email ?? "",
          source: "manual",
          assign,
        });
        made += 1;
      } catch {
        misses.push(person.name || person.phone);
      }
    }
    setAdded(made);
    setFailed(misses);
    setBusy(false);
    onDone();
  };

  return (
    <Dialog
      open={open}
      title={added === null ? "Add from your contacts" : "Added"}
      onClose={onClose}
      actions={
        added === null ? (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              onClick={run}
              disabled={busy || count === 0}
            >
              {busy ? "Adding…" : `Add ${count} lead${count === 1 ? "" : "s"}`}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        )
      }
    >
      {added === null ? (
        <div className={styles.form}>
          <ul className={styles.pickList} aria-label="Contacts">
            {picked.map((person, index) => (
              <li key={`${person.phone}-${index}`}>
                <label>
                  <input
                    type="checkbox"
                    checked={chosen[index]}
                    onChange={(event) =>
                      setChosen((current) =>
                        current.map((value, at) =>
                          at === index ? event.target.checked : value,
                        ),
                      )
                    }
                  />
                  <span>
                    <strong>{person.name || "No name"}</strong>
                    <small>{person.phone || "No phone number"}</small>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {canManage ? (
            <Segmented
              label="Who gets them"
              value={assign}
              onChange={setAssign}
              items={[
                { key: "rules", label: "Best fit by the rules" },
                { key: "me", label: "Me" },
              ]}
            />
          ) : (
            <p className={styles.hint}>They go on your desk.</p>
          )}
        </div>
      ) : (
        <div className={styles.form}>
          <p>
            {added} lead{added === 1 ? "" : "s"} added. Anyone already a lead
            joined their existing lead.
          </p>
          {failed.length ? (
            <p className={styles.error} role="alert">
              Not added: {failed.join(", ")}.
            </p>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

const MAPPABLE = [
  "name",
  "phone",
  "email",
  "company",
  "city",
  "language",
  "interest",
];

export function ImportDialog({
  open,
  canManage,
  onClose,
  onDone,
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [assign, setAssign] = useState<"rules" | "me">(
    canManage ? "rules" : "me",
  );
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const command = useRef(commandId());

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const next = await previewImport(file);
      setPreview(next);
      setMapping(next.mapping);
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "That file couldn't be read.",
      );
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!preview) return;
    if (!mapping.name && !mapping.phone) {
      setError("Choose the column with the name or the phone number.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await commitImport(preview, mapping, assign, command.current));
      onDone();
    } catch (reason) {
      setError(
        reason instanceof LeadsError
          ? reason.message
          : "The import didn't finish. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Import leads"
      description="Excel (.xlsx) or CSV with a header row, up to 2,000 leads. We match the columns for you, and every column is kept on the lead."
      onClose={onClose}
      actions={
        result ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            {preview ? (
              <Button variant="primary" onClick={run} disabled={busy}>
                {busy
                  ? "Importing…"
                  : `Import ${preview.total_rows} lead${preview.total_rows === 1 ? "" : "s"}`}
              </Button>
            ) : null}
          </>
        )
      }
    >
      <div className={styles.form}>
        {result ? (
          <dl className={styles.result}>
            <div>
              <dt>New leads</dt>
              <dd>{result.created}</dd>
            </div>
            <div>
              <dt>Already leads</dt>
              <dd>{result.repeats}</dd>
            </div>
            <div>
              <dt>Given an owner</dt>
              <dd>{result.assigned}</dd>
            </div>
            <div>
              <dt>Waiting for an owner</dt>
              <dd>{result.waiting}</dd>
            </div>
            {result.skipped ? (
              <div>
                <dt>Skipped (no name or phone)</dt>
                <dd>{result.skipped}</dd>
              </div>
            ) : null}
          </dl>
        ) : !preview ? (
          <>
            <label
              className={styles.drop}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                void pick(event.dataTransfer.files?.[0]);
              }}
            >
              <FileSpreadsheet size={20} aria-hidden="true" />
              <span>
                {busy
                  ? "Reading the file…"
                  : "Drop a file here, or tap to choose one"}
              </span>
              <input
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                disabled={busy}
                onChange={(event) => void pick(event.target.files?.[0])}
              />
            </label>
            <a
              className={styles.linkButton}
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`}
              download="sales-xray-leads-sample.csv"
            >
              Download a sample file
            </a>
          </>
        ) : (
          <>
            <p className={styles.hint}>
              {preview.file_name}: {preview.total_rows} rows
              {preview.truncated ? " (only the first 2,000)" : ""},{" "}
              {preview.with_phone} with a phone
              {preview.repeats_in_file
                ? `, ${preview.repeats_in_file} repeated in the file`
                : ""}
              .
            </p>
            <div className={styles.formGrid}>
              {MAPPABLE.map((field) => (
                <Field key={field} label={FIELD_LABELS[field]}>
                  <select
                    value={mapping[field] ?? ""}
                    onChange={(event) =>
                      setMapping((current) => {
                        const next = { ...current };
                        if (event.target.value)
                          next[field] = event.target.value;
                        else delete next[field];
                        return next;
                      })
                    }
                  >
                    <option value="">Not in this file</option>
                    {preview.headers.map((header) => (
                      <option key={header} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                </Field>
              ))}
            </div>
            <div className={styles.previewTable}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    {preview.headers.slice(0, 6).map((header) => (
                      <th key={header}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 3).map((row, index) => (
                    <tr key={index}>
                      {preview.headers.slice(0, 6).map((header) => (
                        <td key={header}>{row[header] ?? ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canManage ? (
              <Segmented
                label="Who gets them"
                value={assign}
                onChange={setAssign}
                items={[
                  { key: "rules", label: "Best fit by the rules" },
                  { key: "me", label: "Me" },
                ]}
              />
            ) : (
              <p className={styles.hint}>They go on your desk.</p>
            )}
          </>
        )}
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
