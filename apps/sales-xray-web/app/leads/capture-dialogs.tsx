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
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { useFlow } from "../telemetry-flows";
import { Button, Dialog, Field, kitStyles, Segmented } from "../ui/kit";
import { Picker } from "../ui/picker";
import { Sheet } from "../ui/sheet";
import { several, usePipelines } from "./use-pipelines";
import {
  addLead,
  matchLead,
  commandId,
  contactsSupported,
  LeadsError,
  parseContactText,
  pickContacts,
  type LeadMatch,
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

// Importing a file: a full-page workspace of its own (owner's picks I1-I4, 17 Nov 2026).
export { ImportFlow as ImportDialog } from "./import-flow";
