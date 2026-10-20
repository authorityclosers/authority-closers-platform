"use client";

/**
 * WhatsApp after 24 hours: only an approved template may go, and only to
 * someone who agreed to hear from the business. This box picks a template,
 * fills its parts, shows exactly what they will read, and sends it; before a
 * yes, it notes how they agreed instead.
 */

import { CheckCircle2, SendHorizontal } from "lucide-react";
import { useState } from "react";

import { LeadsError } from "../leads/leads-client";
import { filled, type WaTemplate } from "../leads/whatsapp-client";
import { notify } from "../notice-center";
import { recordOptIn, sendTemplate, type ChatDetail } from "./chats-client";
import styles from "./chats.module.css";

const keyOf = (template: WaTemplate) => `${template.name}|${template.language}`;

/** "first_visit_reminder" → "First visit reminder". */
export function templateName(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

function failed(reason: unknown, title: string) {
  notify({
    id: "chats-whatsapp",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "That didn't work. Try again.",
  });
}

export function TemplateComposer({
  detail,
  leadId,
  onSent,
}: {
  detail: ChatDetail;
  leadId: string;
  onSent: (next: ChatDetail) => void;
}) {
  const [pickedKey, setPickedKey] = useState(
    detail.templates[0] ? keyOf(detail.templates[0]) : "",
  );
  const [values, setValues] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const picked =
    detail.templates.find((template) => keyOf(template) === pickedKey) ?? null;

  if (!detail.templates.length)
    return (
      <p className={styles.composeNote}>
        No approved WhatsApp templates yet. A manager adds them in WhatsApp
        settings; Meta approves each one, usually within a day.
      </p>
    );

  const missing = picked
    ? Array.from({ length: picked.parts }, (_, index) => index).filter(
        (index) => !values[index]?.trim(),
      ).length
    : 1;
  const send = async () => {
    if (!picked) return;
    setBusy(true);
    try {
      const next = await sendTemplate(leadId, picked, values);
      setValues([]);
      onSent(next);
    } catch (reason) {
      failed(reason, "Template not sent");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.templateBox}>
      <label className={styles.templatePick}>
        <span>Template</span>
        <select
          value={pickedKey}
          onChange={(event) => {
            setPickedKey(event.target.value);
            setValues([]);
          }}
        >
          {detail.templates.map((template) => (
            <option key={keyOf(template)} value={keyOf(template)}>
              {templateName(template.name)} ({template.language})
            </option>
          ))}
        </select>
      </label>
      {picked && picked.parts ? (
        <div className={styles.templateParts}>
          {Array.from({ length: picked.parts }, (_, index) => (
            <input
              key={index}
              aria-label={`Fill in part ${index + 1}`}
              placeholder={`Part ${index + 1}`}
              maxLength={200}
              value={values[index] ?? ""}
              onChange={(event) =>
                setValues((current) => {
                  const next = [...current];
                  next[index] = event.target.value;
                  return next;
                })
              }
            />
          ))}
        </div>
      ) : null}
      {picked ? (
        <div className={styles.templatePreview}>
          <span>They will read</span>
          <p>{filled(picked.text, values)}</p>
        </div>
      ) : null}
      <button
        type="button"
        className={styles.templateSend}
        disabled={busy || !picked || missing > 0}
        onClick={() => void send()}
      >
        <SendHorizontal size={16} aria-hidden="true" />
        {busy
          ? "Sending…"
          : missing > 0 && picked
            ? `Fill in ${missing} part${missing === 1 ? "" : "s"}`
            : "Send template"}
      </button>
    </div>
  );
}

export function OptInBox({
  leadId,
  onSaved,
}: {
  leadId: string;
  onSaved: (next: ChatDetail) => void;
}) {
  const [how, setHow] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      onSaved(await recordOptIn(leadId, how));
    } catch (reason) {
      failed(reason, "Not saved");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.optIn}>
      <input
        aria-label="How they agreed"
        placeholder="How they agreed, e.g. said yes on the call"
        maxLength={200}
        value={how}
        onChange={(event) => setHow(event.target.value)}
      />
      <button
        type="button"
        className={styles.templateSend}
        disabled={busy}
        onClick={() => void save()}
      >
        <CheckCircle2 size={16} aria-hidden="true" />
        {busy ? "Saving…" : "They agreed"}
      </button>
    </div>
  );
}
