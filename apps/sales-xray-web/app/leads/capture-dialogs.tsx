"use client";

/**
 * Adding leads: one "Add leads" menu with the ways people actually have
 * them — type one in (pasting a WhatsApp message fills the form), pick from
 * the phone's contacts, upload a list, or connect Facebook. Repeat phone
 * numbers join their existing lead instead of making a second one.
 *
 * The page gives each opening a new key, so every dialog starts empty.
 */

import { viewedLeadsSide } from "../shell/shell-store";
import {
  ClipboardPaste,
  Contact,
  FileSpreadsheet,
  Keyboard,
  Megaphone,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { useFlow } from "../telemetry-flows";
import { Button, Dialog, Field, kitStyles, Segmented } from "../ui/kit";
import { Picker } from "../ui/picker";
import { Sheet } from "../ui/sheet";
import { several, usePipelines } from "./use-pipelines";
import { ImportHistory, UndoImportButton } from "./import-undo";
import { ImportCheck, resultLines, SkippedDownload } from "./import-check";
import checkStyles from "./import-check.module.css";
import {
  addLead,
  matchLead,
  commandId,
  commitImport,
  contactsSupported,
  FIELD_LABELS,
  LeadsError,
  parseContactText,
  pickContacts,
  previewImport,
  readTeam,
  SAMPLE_CSV,
  type Duplicates,
  type ImportPreview,
  type ImportResult,
  type LeadMatch,
  type NewLead,
  type PickedContact,
  type RepView,
  type SharedLead,
} from "./leads-client";
import {
  countsFor,
  firstChoices,
  freshRows,
  sharesFor,
  type UploadChoices,
} from "./bulk-upload";
import {
  overLimitLines,
  sharesLine,
  UploadChoicesFields,
} from "./upload-choices";
import { askFeedback } from "../feedback/ask";
import { BrandTile } from "../ui/brand-tile";
import {
  GoogleFilesError,
  previewGoogleSheet,
  readGoogleFiles,
  type GoogleFiles,
} from "./google-files-client";
import { PICKER_FAILED, pickGoogleSheet } from "./google-picker";
import { inPhoneApp, openConnect } from "./native-phone";
import { PASTED_FILE, pastedFile, readPasted } from "./paste-import";
import { settingsPath } from "../settings/settings-sections";
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

/**
 * Which pipeline new leads go to, when the organisation runs several (owner, 22 Oct
 * 2026). Left alone, the pipeline that takes their source gets them.
 */
function PipelinePick({
  open,
  value,
  onChange,
  plural = false,
}: {
  open: boolean;
  value: string;
  onChange: (next: string) => void;
  plural?: boolean;
}) {
  const pipes = usePipelines(open);
  if (!several(pipes)) return null;
  return (
    <Field label="Pipeline">
      <Picker
        title="Pipeline"
        mode="inline"
        value={value || null}
        all={{
          label: plural ? "Where file imports go" : "Where added leads go",
        }}
        options={pipes.pipelines.map((item) => ({
          key: item.key,
          label: item.name,
        }))}
        onChange={(key) => onChange(key ?? "")}
      />
    </Field>
  );
}

export function AddLeadDialog({
  open,
  canManage,
  onClose,
  onAdded,
  initial = null,
  initialNote = "From the Sales X-Ray extension. Check the details, then add the lead.",
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
  // Inbound by default: a lead typed in is usually a real enquiry (section 5);
  // Cold when Leads shows the Cold list (ph2-21, 1 Nov 2026).
  const [side, setSide] = useState<"live" | "cold">(() =>
    viewedLeadsSide() === "cold" ? "cold" : "live",
  );
  const [assign, setAssign] = useState<"rules" | "me">(
    canManage ? "rules" : "me",
  );
  const [pipeline, setPipeline] = useState("");
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
  // What the form held when it opened: anything typed since asks before it
  // is thrown away (Back, the scrim, Cancel).
  const [start] = useState(form);
  const [discarding, setDiscarding] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(start);
  const close = () => {
    if (dirty && !discarding && !saving) {
      setDiscarding(true);
      return;
    }
    onClose();
  };
  // A number that is already a lead says so while it is typed (22 Oct 2026).
  const [match, setMatch] = useState<{
    phone: string;
    value: LeadMatch;
  } | null>(null);
  const digits = form.phone.replace(/\D/g, "").length;
  useEffect(() => {
    if (!open || digits < 10) return;
    const phone = form.phone;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      matchLead(phone, controller.signal).then(
        (value) => setMatch({ phone, value }),
        () => undefined,
      );
    }, 400);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, form.phone, digits]);
  const existing =
    match && match.phone === form.phone && match.value.found
      ? match.value
      : null;
  // A teammate's lead: Add lead would refuse it, so it isn't offered.
  const teammates = existing !== null && !existing.lead_id;

  // Adding a lead in the weekly friction report: opened, typed, told it is
  // already a lead, Add refused for something missing, added or closed.
  const flow = useFlow("add_lead", { active: open, via: "sheet" });
  const leadStep = existing ? "duplicate" : dirty ? "form" : null;
  useEffect(() => {
    if (open && leadStep) flow.step(leadStep);
  }, [flow, open, leadStep]);
  useEffect(() => {
    if (!open) flow.cancel();
  }, [flow, open]);

  // Owner, 22 Oct: adding a lead must be low effort. An empty form starts in
  // the name box with the keyboard up; a filled-in one waits to be checked.
  useEffect(() => {
    if (!open || initial) return;
    const frame = window.requestAnimationFrame(() => nameRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, initial]);

  const set =
    (key: keyof typeof EMPTY) => (event: { target: { value: string } }) => {
      setDiscarding(false);
      setForm((current) => ({ ...current, [key]: event.target.value }));
    };

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
      flow.blocked("form");
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
        pipeline: pipeline || undefined,
        side,
      };
      const detail = await addLead(lead, command.current);
      flow.done({ step: "save" });
      // A number already a lead joins it (the API's 201): say so, and open it
      // (simulation lab d208a435; orchestrator, 1 Nov 2026).
      if (detail.events?.[0]?.kind === "repeat")
        notify({
          id: `already-${detail.lead.lead_id}`,
          tone: "info",
          title: `Already a lead: ${displayName(detail.lead.name)} · ${detail.lead.stage_label}`,
          message: "Opened it instead of adding a new one.",
        });
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
      onClose={close}
      wide="center"
      footer={
        discarding ? (
          <div className={styles.discardAsk} role="alert">
            <span>Discard this lead?</span>
            <Button onClick={() => setDiscarding(false)}>Keep editing</Button>
            <Button variant="primary" onClick={onClose}>
              Discard
            </Button>
          </div>
        ) : (
          <>
            <Button onClick={close}>Cancel</Button>
            <Button
              variant="primary"
              type="submit"
              form={formId}
              disabled={saving || teammates}
            >
              {saving ? "Adding…" : "Add lead"}
            </Button>
          </>
        )
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
          <Field
            label="Phone"
            hint={
              existing ? (
                <span className={styles.matchNote} role="status">
                  {existing.lead_id ? (
                    <>
                      <span>
                        Already a lead:{" "}
                        <strong>{displayName(existing.name ?? "")}</strong>
                        {existing.stage_label
                          ? ` · ${existing.stage_label}`
                          : ""}
                        {existing.yours
                          ? " · yours"
                          : existing.owner_name
                            ? ` · with ${displayName(existing.owner_name)}`
                            : ""}
                      </span>
                      <button
                        type="button"
                        className={styles.matchOpen}
                        onClick={() => onAdded(existing.lead_id!)}
                      >
                        Open
                      </button>
                    </>
                  ) : (
                    "Already a lead on a teammate's desk."
                  )}
                </span>
              ) : undefined
            }
          >
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
        <div className={styles.whoGets}>
          <span className={kitStyles.fieldLabel} aria-hidden="true">
            Inbound or Cold
          </span>
          <Segmented
            label="Inbound or Cold"
            value={side}
            onChange={setSide}
            items={[
              { key: "live", label: "Inbound Leads" },
              { key: "cold", label: "Cold Leads" },
            ]}
          />
        </div>
        {canManage ? (
          <PipelinePick open={open} value={pipeline} onChange={setPipeline} />
        ) : null}
        {canManage ? (
          <div className={styles.whoGets}>
            <span className={kitStyles.fieldLabel} aria-hidden="true">
              Who gets it
            </span>
            <Segmented
              label="Who gets it"
              value={assign}
              onChange={setAssign}
              items={[
                { key: "rules", label: "Best fit by the rules" },
                { key: "me", label: "Me" },
              ]}
            />
          </div>
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

/** A file's stage and owner columns (owner P0, 23 Oct 2026): names, matched by the server. */
const COLUMN_LABELS: Record<string, string> = {
  ...FIELD_LABELS,
  stage: "Stage",
  owner: "Owner",
  source: "Source",
};

/** The import's steps (competitor teardown 5, 1 Nov 2026). */
type ImportStep = "file" | "columns" | "check" | "who";
const IMPORT_STEPS: { key: ImportStep; label: string }[] = [
  { key: "file", label: "File" },
  { key: "columns", label: "Columns" },
  { key: "check", label: "Check" },
  { key: "who", label: "Who gets them" },
];

/** The columns matched and nearly every row makes a lead: the file opens on
 *  Check, its column list one tap away (universal intake, 25 Oct 2026). */
function columnsMatched(
  preview: ImportPreview,
  mapping: Record<string, string>,
): boolean {
  return (
    preview.importable !== undefined &&
    Boolean(mapping.name || mapping.phone) &&
    preview.importable >= Math.ceil(preview.total_rows * 0.9)
  );
}

/** Up to three of a column's values, to see it is the right one. */
function samplesOf(preview: ImportPreview, header: string | undefined) {
  if (!header) return "";
  return preview.rows
    .map((row) => row[header]?.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join(" · ");
}

export function ImportDialog({
  open,
  canManage,
  onClose,
  onDone,
  onLanded,
  pasted = null,
  google = false,
}: {
  open: boolean;
  canManage: boolean;
  onClose: () => void;
  onDone: () => void;
  /** Done: show the side the new leads went to (ph1-17: it opened Inbound). */
  onLanded?: (side: "inbound" | "cold") => void;
  /** Rows pasted into the list's quick add: read as soon as it opens. */
  pasted?: string | null;
  /** Opened to import a Google Sheet (Lead sources → Import from Google
   *  Sheet): Google's Picker opens as soon as Google is known connected. */
  google?: boolean;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  // Bulk upload (stages-views-sources.md section 5): Cold Leads by default, who receives
  // the new leads and how many each, and the stage they start in.
  const [choices, setChoices] = useState<UploadChoices>(() =>
    firstChoices(canManage),
  );
  const [team, setTeam] = useState<RepView[] | null>(null);
  useEffect(() => {
    if (!open || !canManage) return;
    let live = true;
    readTeam().then(
      (next) => {
        if (live) setTeam(next.reps);
      },
      () => {
        if (live) setTeam([]);
      },
    );
    return () => {
      live = false;
    };
  }, [open, canManage]);
  const [pipeline, setPipeline] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const command = useRef(commandId());
  // Rows pasted from a sheet, a CSV or a chat (owner P0, 23 Oct 2026).
  const [text, setText] = useState("");
  const [dropped, setDropped] = useState(0);
  // File, Columns, Check, Who gets them (competitor teardown 5): a file whose
  // columns matched opens on Check, Import there with the defaults (the owner's
  // one click, 25 Oct 2026); otherwise Columns first. Numbers already leads are
  // skipped unless an owner or admin picks Fill blanks or Replace.
  const [step, setStep] = useState<ImportStep>("file");
  const [duplicates, setDuplicates] = useState<Duplicates>("skip");
  const landed = (next: ImportPreview) => {
    setPreview(next);
    setMapping(next.mapping);
    setStep(columnsMatched(next, next.mapping) ? "check" : "columns");
  };

  // A Sheet picked in Google's Picker (Lead OS, 27 Oct 2026): owners and
  // admins, once Google Sheets and Drive is connected.
  const [googleFiles, setGoogleFiles] = useState<GoogleFiles | null>(null);
  useEffect(() => {
    if (!open || !canManage) return;
    const controller = new AbortController();
    readGoogleFiles(controller.signal).then(setGoogleFiles, () =>
      setGoogleFiles(null),
    );
    return () => controller.abort();
  }, [open, canManage]);
  const googleReady = Boolean(googleFiles?.connected && googleFiles.picker);
  // The Picker found Google no longer connected: say where to connect it.
  const [googleLost, setGoogleLost] = useState(false);
  const fromGoogle = async () => {
    // The Picker needs a real browser page: the phone app opens one.
    if (inPhoneApp()) {
      void openConnect(
        new URL("/leads?import=google", window.location.origin).href,
      );
      return;
    }
    setBusy(true);
    setError(null);
    let sheet: string | null = null;
    try {
      sheet = await pickGoogleSheet();
      if (!sheet) return;
      landed(await previewGoogleSheet(sheet));
    } catch (reason) {
      // 409 from the Picker's setup: Google isn't connected (any more).
      if (
        !sheet &&
        reason instanceof GoogleFilesError &&
        reason.status === 409
      ) {
        setGoogleLost(true);
        setGoogleFiles(
          (current) => current && { ...current, connected: false },
        );
        return;
      }
      setError(
        reason instanceof GoogleFilesError || reason instanceof LeadsError
          ? reason.message
          : PICKER_FAILED,
      );
    } finally {
      setBusy(false);
    }
  };
  const fromGoogleLatest = useRef(fromGoogle);
  useEffect(() => {
    fromGoogleLatest.current = fromGoogle;
  });
  // Arrived for a Google Sheet: the Picker opens once Google is known ready;
  // without Google connected, the dialog says where to connect it.
  const googleMissing =
    (google || googleLost) &&
    canManage &&
    googleFiles !== null &&
    !(googleFiles.connected && googleFiles.picker);
  const googleAsked = useRef(false);
  useEffect(() => {
    if (!open || !google || !googleReady || googleAsked.current) return;
    if (inPhoneApp()) return;
    googleAsked.current = true;
    void fromGoogleLatest.current();
  }, [open, google, googleReady]);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      landed(await previewImport(file));
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

  const readText = (value: string) => {
    const rows = readPasted(value);
    if (!rows) {
      setError(
        "There are no rows in that. Copy the rows from your sheet, with their headings if it has them.",
      );
      return;
    }
    setDropped(rows.dropped);
    void pick(pastedFile(rows));
  };
  const reading = useRef(readText);
  useEffect(() => {
    reading.current = readText;
  });
  const handed = useRef(false);
  useEffect(() => {
    if (!open || !pasted || handed.current) return;
    handed.current = true;
    setText(pasted);
    reading.current(pasted);
  }, [open, pasted]);

  const fresh = preview ? freshRows(preview) : 0;
  const overGiven =
    choices.assign === "people" &&
    team !== null &&
    Object.values(countsFor(choices, team, fresh)).reduce(
      (sum, count) => sum + count,
      0,
    ) > fresh;
  // An even split needs the team: Import waits for it.
  const teamPending = canManage && choices.assign === "people" && team === null;
  const noColumn = !mapping.name && !mapping.phone;
  const limits = canManage ? overLimitLines(choices, team, fresh) : [];

  const run = async () => {
    if (!preview) return;
    if (noColumn) {
      setError("Choose the column with the name or the phone number.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(
        await commitImport(
          preview,
          mapping,
          choices.assign,
          command.current,
          pipeline || null,
          {
            side: choices.side,
            ...(choices.assign === "people" && team
              ? { shares: sharesFor(choices, team, fresh) }
              : {}),
            ...(choices.step ? { step: choices.step } : {}),
            ...(duplicates !== "skip" ? { duplicates } : {}),
          },
        ),
      );
      onDone();
      // Reviews engine: how the first import went, asked once.
      askFeedback("first_import", { subject: "first-import" });
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

  const back = () => {
    setError(null);
    if (step === "who") setStep("check");
    else if (step === "check") setStep("columns");
    else {
      // Back from Columns: choose another file.
      setPreview(null);
      setMapping({});
      setDropped(0);
      setStep("file");
    }
  };

  // The file in a line: whose export, its name and how many rows.
  const fileLine = preview ? (
    <p className={styles.hint}>
      {preview.detected ? `${preview.detected} export. ` : ""}
      {preview.file_name === PASTED_FILE ? "Pasted" : preview.file_name}:{" "}
      {preview.total_rows} rows
      {preview.truncated || dropped ? " (only the first 2,000)" : ""}.
    </p>
  ) : null;
  const limitBox = limits.length ? (
    // Said before the import, never only after (ph1-17).
    <div className={styles.importWarnings} role="status" data-import-limit="">
      {limits.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  ) : null;

  return (
    <Dialog
      open={open}
      title="Import leads"
      description={
        step === "file" && !result
          ? "An Excel (.xlsx) or CSV file, or rows pasted from a sheet or a chat, up to 2,000 leads. We match the columns for you, and every column is kept on the lead."
          : undefined
      }
      onClose={onClose}
      actions={
        result ? (
          <Button
            variant="primary"
            onClick={() => {
              if (result.side && onLanded)
                onLanded(result.side === "cold" ? "cold" : "inbound");
              onClose();
            }}
          >
            Done
          </Button>
        ) : step === "file" || !preview ? (
          <Button onClick={onClose}>Cancel</Button>
        ) : (
          <>
            <Button onClick={back} disabled={busy}>
              Back
            </Button>
            {step === "columns" ? (
              <Button
                variant="primary"
                onClick={() => setStep("check")}
                disabled={noColumn}
              >
                Next
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={run}
                disabled={busy || overGiven || teamPending || noColumn}
              >
                {busy
                  ? "Importing…"
                  : fresh
                    ? `Import ${fresh} lead${fresh === 1 ? "" : "s"}`
                    : "Import"}
              </Button>
            )}
          </>
        )
      }
    >
      <div className={styles.form}>
        {result ? null : (
          <ol className={checkStyles.steps} aria-label="Import steps">
            {IMPORT_STEPS.map((item, index) => (
              <li
                key={item.key}
                aria-current={item.key === step ? "step" : undefined}
              >
                <span aria-hidden="true">{index + 1}</span>
                {item.label}
              </li>
            ))}
          </ol>
        )}
        {result ? (
          <dl className={styles.result}>
            {/* The rows by what became of them, in the check's words. */}
            {resultLines(result, duplicates).map((line) => (
              <div key={line.key} data-result={line.key}>
                <dt>{line.label}</dt>
                <dd>{line.count}</dd>
              </div>
            ))}
            <div>
              <dt>Given an owner</dt>
              <dd>{result.assigned}</dd>
            </div>
            <div>
              <dt>Waiting for an owner</dt>
              <dd>{result.waiting}</dd>
            </div>
            {result.staged ? (
              <div>
                <dt>Given their stage</dt>
                <dd>{result.staged}</dd>
              </div>
            ) : null}
            {result.owned ? (
              <div>
                <dt>Given the owner named</dt>
                <dd>{result.owned}</dd>
              </div>
            ) : null}
            {result.given?.map((item) => (
              <div key={item.person_id}>
                <dt>Given to {displayName(item.name)}</dt>
                <dd>{item.leads}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {result?.side ? (
          <p className={styles.hint}>
            The new leads are in{" "}
            {result.side === "cold" ? "Cold Leads" : "Inbound Leads"}.
          </p>
        ) : null}
        {result?.unmatched_stages?.length ? (
          <p className={styles.hint}>
            No stage called {result.unmatched_stages.join(", ")}: those leads
            stay New.
          </p>
        ) : null}
        {/* People the import took past their limit (Lead OS, 25 Oct 2026):
            said as written, as a warning; an import never hides it. */}
        {result?.warnings?.length ? (
          <div
            className={styles.importWarnings}
            role="status"
            data-import-warnings=""
          >
            {result.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
            {canManage ? (
              <Link href={settingsPath("lead-rules")}>Change limits</Link>
            ) : null}
          </div>
        ) : null}
        {result?.unmatched_owners?.length ? (
          <p className={styles.hint}>
            Nobody on your team called {result.unmatched_owners.join(", ")}:
            those leads went by the lead rules.
          </p>
        ) : null}
        {/* The rows it didn't use, with why, to fix and import again. */}
        {result && preview ? (
          <SkippedDownload preview={preview} result={result} />
        ) : null}
        {/* Undo import for 48 hours, owners and admins (competitor teardown 22). */}
        {result?.import_id && result.undo_until ? (
          <UndoImportButton importId={result.import_id} onUndone={onDone} />
        ) : null}
        {result ? null : step === "file" || !preview ? (
          <>
            {/* Cold Leads unless picked otherwise (section 5). */}
            <UploadChoicesFields
              part="side"
              canManage={canManage}
              team={team}
              fresh={fresh}
              pipeline={pipeline}
              value={choices}
              onChange={setChoices}
            />
            {canManage ? (
              <PipelinePick
                open={open}
                value={pipeline}
                onChange={setPipeline}
                plural
              />
            ) : null}
            {googleMissing ? (
              <p className={styles.hint} role="status">
                Connect Google Sheets and Drive first:{" "}
                <Link href={settingsPath("apps")}>
                  Settings → Connected apps
                </Link>
                .
              </p>
            ) : null}
            {googleReady ? (
              <Button onClick={() => void fromGoogle()} disabled={busy}>
                <BrandTile brands={["googlesheets"]} size={20} />
                {busy ? "Opening Google…" : "Pick a Google Sheet"}
              </Button>
            ) : null}
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
            <div className={`${styles.pasteBox} ${styles.pasteRows}`}>
              <textarea
                aria-label="Paste rows"
                rows={3}
                value={text}
                disabled={busy}
                placeholder="Or paste rows from a sheet, a CSV or ChatGPT"
                onChange={(event) => {
                  setText(event.target.value);
                  setError(null);
                }}
                onPaste={(event) => {
                  const value = event.clipboardData.getData("text");
                  if (!value.trim()) return;
                  event.preventDefault();
                  setText(value);
                  readText(value);
                }}
              />
              <Button
                onClick={() => readText(text)}
                disabled={busy || !text.trim()}
              >
                Read rows
              </Button>
            </div>
            <a
              className={styles.linkButton}
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`}
              download="sales-xray-leads-sample.csv"
            >
              Download a sample file
            </a>
            {canManage ? <ImportHistory onChanged={onDone} /> : null}
          </>
        ) : step === "columns" ? (
          <>
            {fileLine}
            {/* Each column with up to three of its values (HubSpot's three
                rows under each column; teardown 5). */}
            <div className={styles.formGrid}>
              {[
                ...MAPPABLE,
                "stage",
                "source",
                ...(canManage ? ["owner"] : []),
              ].map((field) => (
                <div key={field} className={checkStyles.column}>
                  <Field label={COLUMN_LABELS[field]}>
                    <Picker
                      title={COLUMN_LABELS[field] ?? field}
                      mode="inline"
                      value={mapping[field] || null}
                      all={{ label: "Not in this file" }}
                      options={preview.headers.map((header) => ({
                        key: header,
                        label: header,
                      }))}
                      onChange={(key) =>
                        setMapping((current) => {
                          const next = { ...current };
                          if (key) next[field] = key;
                          else delete next[field];
                          return next;
                        })
                      }
                    />
                  </Field>
                  {mapping[field] ? (
                    <small className={checkStyles.samples} data-samples={field}>
                      {samplesOf(preview, mapping[field]) ||
                        "Empty in this file"}
                    </small>
                  ) : null}
                </div>
              ))}
            </div>
            {mapping.stage || (canManage && mapping.owner) ? (
              <p className={styles.hint}>
                Stages are matched by name to the pipeline&apos;s stages, and
                owners to your team. One that doesn&apos;t match stays New, or
                goes by the lead rules.
              </p>
            ) : null}
            <p className={styles.hint}>
              {noColumn
                ? "Choose the column with the name or the phone number."
                : "Every other column is kept on the lead."}
            </p>
          </>
        ) : step === "check" ? (
          <>
            {fileLine}
            <p className={styles.hint}>
              Columns matched:{" "}
              {Object.keys(mapping)
                .filter((field) => mapping[field])
                .map((field) => COLUMN_LABELS[field] ?? field)
                .join(", ")}
              .{" "}
              <button
                type="button"
                className={styles.linkButton}
                onClick={() => setStep("columns")}
              >
                Change columns
              </button>
            </p>
            {/* The first rows as they will be leads, before Import (phone
                personas ph1-48 and competitor teardown 5). */}
            <ul className={styles.hint} aria-label="The first rows, as leads">
              {preview.rows.slice(0, 3).map((row, index) => (
                <li key={index}>
                  {[mapping.name, mapping.phone, mapping.source]
                    .map((column) => (column ? row[column]?.trim() : ""))
                    .filter(Boolean)
                    .join(" · ") || "No name or phone in this row"}
                </li>
              ))}
            </ul>
            <ImportCheck
              preview={preview}
              fresh={fresh}
              canManage={canManage}
              duplicates={duplicates}
              onDuplicates={setDuplicates}
            />
            {/* Who gets them, in a line; Change opens the last step. */}
            <p className={styles.hint} data-import-who="">
              {canManage
                ? `About ${fresh} new ${fresh === 1 ? "lead" : "leads"}: ${sharesLine(choices, team, fresh)}`
                : "They go on your desk."}{" "}
              <button
                type="button"
                className={styles.linkButton}
                onClick={() => setStep("who")}
              >
                Change
              </button>
            </p>
            {limitBox}
          </>
        ) : (
          <>
            <UploadChoicesFields
              part="who"
              canManage={canManage}
              team={team}
              fresh={fresh}
              pipeline={pipeline}
              value={choices}
              onChange={setChoices}
            />
            {canManage ? (
              <p className={styles.hint}>
                About {fresh} new {fresh === 1 ? "lead" : "leads"}:{" "}
                {sharesLine(choices, team, fresh)}
              </p>
            ) : null}
            {limitBox}
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
