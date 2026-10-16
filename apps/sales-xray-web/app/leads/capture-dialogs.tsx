"use client";

/**
 * Add one lead by hand (NeoDove's "Walk-In Lead"), or import a CSV/Excel
 * file: preview, match columns, then import. Repeat phone numbers join their
 * existing lead instead of making a second one.
 */

import { FileSpreadsheet } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button, Dialog, Field, Segmented } from "../ui/kit";
import {
  addLead,
  commandId,
  commitImport,
  FIELD_LABELS,
  LeadsError,
  previewImport,
  type ImportPreview,
  type ImportResult,
  type NewLead,
} from "./leads-client";
import styles from "./leads.module.css";

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
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onAdded: (leadId: string) => void;
}) {
  const [form, setForm] = useState(EMPTY);
  const [source, setSource] = useState<"manual" | "referral">("manual");
  const [assign, setAssign] = useState<"rules" | "me">(canManage ? "rules" : "me");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const command = useRef(commandId());

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY);
    setSource("manual");
    setAssign(canManage ? "rules" : "me");
    setError(null);
    command.current = commandId();
  }, [open, canManage]);

  const set = (key: keyof typeof EMPTY) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

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
      setError(reason instanceof LeadsError ? reason.message : "Not added. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Add a lead"
      description="If this phone number is already a lead, it joins that lead as asked again."
      onClose={onClose}
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Adding…" : "Add lead"}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        <Segmented
          label="Where it came from"
          value={source}
          onChange={setSource}
          items={[
            { key: "manual", label: "Walk-in or call" },
            { key: "referral", label: "Referral" },
          ]}
        />
        <div className={styles.formGrid}>
          <Field label="Name">
            <input value={form.name} maxLength={200} onChange={set("name")} autoComplete="off" />
          </Field>
          <Field label="Phone">
            <input value={form.phone} maxLength={40} inputMode="tel" onChange={set("phone")} autoComplete="off" />
          </Field>
          <Field label="Company">
            <input value={form.company} maxLength={200} onChange={set("company")} />
          </Field>
          <Field label="City">
            <input value={form.city} maxLength={120} onChange={set("city")} />
          </Field>
          <Field label="Language">
            <input value={form.language} maxLength={40} placeholder="Hindi" onChange={set("language")} />
          </Field>
          <Field label="Interested in">
            <input value={form.interest} maxLength={200} onChange={set("interest")} />
          </Field>
          <Field label="Email">
            <input value={form.email} maxLength={320} inputMode="email" onChange={set("email")} />
          </Field>
          {source === "referral" ? (
            <Field label="Referred by">
              <input value={form.referred_by} maxLength={200} onChange={set("referred_by")} />
            </Field>
          ) : null}
        </div>
        <Field label="Note" wide>
          <textarea value={form.note} maxLength={1000} onChange={set("note")} />
        </Field>
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
        ) : (
          <p className={styles.hint}>It goes on your desk.</p>
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

const MAPPABLE = ["name", "phone", "email", "company", "city", "language", "interest"];

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
  const [assign, setAssign] = useState<"rules" | "me">(canManage ? "rules" : "me");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const command = useRef(commandId());

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setMapping({});
    setResult(null);
    setError(null);
    setAssign(canManage ? "rules" : "me");
    command.current = commandId();
  }, [open, canManage]);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const next = await previewImport(file);
      setPreview(next);
      setMapping(next.mapping);
    } catch (reason) {
      setError(reason instanceof LeadsError ? reason.message : "That file couldn't be read.");
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
      setError(reason instanceof LeadsError ? reason.message : "The import didn't finish. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Import leads"
      description="A CSV or Excel (.xlsx) file with a header row, up to 2,000 leads. Every column is kept on the lead."
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
                {busy ? "Importing…" : `Import ${preview.total_rows} lead${preview.total_rows === 1 ? "" : "s"}`}
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
          <label className={styles.drop}>
            <FileSpreadsheet size={20} aria-hidden="true" />
            <span>{busy ? "Reading the file…" : "Choose a .csv or .xlsx file"}</span>
            <input
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              disabled={busy}
              onChange={(event) => void pick(event.target.files?.[0])}
            />
          </label>
        ) : (
          <>
            <p className={styles.hint}>
              {preview.file_name}: {preview.total_rows} rows
              {preview.truncated ? " (only the first 2,000)" : ""}, {preview.with_phone} with a phone
              {preview.repeats_in_file ? `, ${preview.repeats_in_file} repeated in the file` : ""}.
            </p>
            <div className={styles.formGrid}>
              {MAPPABLE.map((field) => (
                <Field key={field} label={FIELD_LABELS[field]}>
                  <select
                    value={mapping[field] ?? ""}
                    onChange={(event) =>
                      setMapping((current) => {
                        const next = { ...current };
                        if (event.target.value) next[field] = event.target.value;
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
