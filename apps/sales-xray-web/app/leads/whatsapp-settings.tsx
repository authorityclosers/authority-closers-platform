"use client";

/**
 * WhatsApp in Settings → Integrations: the organisation connects its own
 * WhatsApp Business number through Meta's Embedded Signup (Meta bills the
 * organisation for its messages), sets its auto replies, and keeps its message
 * templates. Owners and admins only.
 */

import { MessageCircle, RefreshCw } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, Button, Field } from "../ui/kit";
import { useAppConnect } from "./app-connect";
import { LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import {
  START_URL,
  waCall,
  type AutoReplies,
  type WaNumber,
  type WaStatus,
} from "./whatsapp-client";

const RETURNED: Record<string, string> = {
  connected:
    "WhatsApp is connected. Messages to your number now arrive in Leads.",
  nonumbers:
    "No WhatsApp number was shared. Connect again and pick your number.",
  cancelled: "Connecting WhatsApp was cancelled.",
  failed: "That didn't finish. Try connecting WhatsApp again.",
};
const TEMPLATE_STATUS: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  APPROVED: "good",
  PENDING: "warn",
  REJECTED: "bad",
  PAUSED: "bad",
  DISABLED: "bad",
};

function AutoRepliesForm({
  number,
  approved,
  onSaved,
}: {
  number: WaNumber;
  approved: { name: string; language: string }[];
  onSaved: (status: WaStatus) => void;
}) {
  const [rules, setRules] = useState<AutoReplies>(number.autoReplies);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = rules.firstReply;
  const late = rules.outOfHours;
  const save = async () => {
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await waCall<WaStatus>(`/whatsapp/numbers/${number.id}/auto-replies`, {
          method: "PUT",
          body: JSON.stringify(rules),
        }),
      );
      setNote("Auto replies saved.");
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.waRules}>
      <label className={styles.slaField}>
        <input
          type="checkbox"
          checked={first.on}
          onChange={(event) =>
            setRules({
              ...rules,
              firstReply: { ...first, on: event.target.checked },
            })
          }
        />
        Greet new ad leads at once, if their form said yes to WhatsApp
      </label>
      {first.on ? (
        <div className={styles.row}>
          <Field label="Template">
            <select
              value={
                first.template ? `${first.template}|${first.language}` : ""
              }
              onChange={(event) => {
                const [template, language] = event.target.value.split("|");
                setRules({
                  ...rules,
                  firstReply: { ...first, template, language },
                });
              }}
            >
              <option value="">Pick an approved template</option>
              {approved.map((t) => (
                <option
                  key={`${t.name}|${t.language}`}
                  value={`${t.name}|${t.language}`}
                >
                  {t.name} ({t.language})
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Form question for WhatsApp consent"
            hint="Exactly as it is on your lead form. Only people who answered yes are greeted."
          >
            <input
              value={first.consentQuestion ?? ""}
              maxLength={200}
              onChange={(event) =>
                setRules({
                  ...rules,
                  firstReply: { ...first, consentQuestion: event.target.value },
                })
              }
            />
          </Field>
        </div>
      ) : null}
      <label className={styles.slaField}>
        <input
          type="checkbox"
          checked={late.on}
          onChange={(event) =>
            setRules({
              ...rules,
              outOfHours: { ...late, on: event.target.checked },
            })
          }
        />
        Reply to messages that arrive outside your work hours
      </label>
      {late.on ? (
        <Field
          label="After-hours reply"
          hint="Sent at most once in 12 hours to each person."
        >
          <textarea
            value={late.text ?? ""}
            maxLength={1000}
            rows={2}
            onChange={(event) =>
              setRules({
                ...rules,
                outOfHours: { ...late, text: event.target.value },
              })
            }
          />
        </Field>
      ) : null}
      <Button disabled={busy} onClick={save}>
        Save auto replies
      </Button>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </div>
  );
}

function NewTemplate({
  number,
  onSaved,
}: {
  number: WaNumber;
  onSaved: (status: WaStatus) => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<"UTILITY" | "MARKETING">("UTILITY");
  const [example, setExample] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await waCall<WaStatus>(`/whatsapp/numbers/${number.id}/templates`, {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            language: "en",
            category,
            body: body.trim(),
            example: example
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          }),
        }),
      );
      setName("");
      setBody("");
      setExample("");
      setNote(
        "Sent to Meta for review. It shows as pending until Meta decides.",
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className={styles.waNew}>
      <summary>New template</summary>
      <div className={styles.row}>
        <Field
          label="Name"
          hint="Lower case and underscores, e.g. visit_reminder"
        >
          <input
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Kind">
          <select
            value={category}
            onChange={(e) =>
              setCategory(e.target.value as "UTILITY" | "MARKETING")
            }
          >
            <option value="UTILITY">Utility (about their enquiry)</option>
            <option value="MARKETING">Marketing</option>
          </select>
        </Field>
      </div>
      <Field
        label="Message"
        hint="Use {{1}}, {{2}} for parts you fill in, like their name."
      >
        <textarea
          value={body}
          maxLength={1024}
          rows={3}
          onChange={(e) => setBody(e.target.value)}
        />
      </Field>
      <Field
        label="Examples for the parts"
        hint="Comma separated, e.g. Asha, 11 am"
      >
        <input
          value={example}
          maxLength={300}
          onChange={(e) => setExample(e.target.value)}
        />
      </Field>
      <Button disabled={busy || !name.trim() || !body.trim()} onClick={submit}>
        Send for review
      </Button>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </details>
  );
}

export function WhatsAppSettings() {
  const params = useSearchParams();
  const [status, setStatus] = useState<WaStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    RETURNED[params?.get("whatsapp") ?? ""] ?? null,
  );
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(0);
  // In the Sales Xray app, Connect opens Meta in the phone's browser and
  // finishes back here (Facebook refuses sign-in inside the app).
  const connect = useAppConnect("whatsapp", ({ result, message }) => {
    setNote(message ?? RETURNED[result] ?? RETURNED.failed);
    if (result === "connected") setLoaded((times) => times + 1);
  });

  useEffect(() => {
    let live = true;
    waCall<WaStatus>("/whatsapp/status")
      .then(
        (data) =>
          live &&
          setStatus(
            Array.isArray(data?.numbers) && Array.isArray(data?.templates)
              ? data
              : { configured: false, numbers: [], templates: [] },
          ),
      )
      .catch(
        () =>
          live && setStatus({ configured: false, numbers: [], templates: [] }),
      );
    return () => {
      live = false;
    };
  }, [loaded]);

  // Hidden until AC's WhatsApp app is set up for Sales Xray (nothing to connect yet).
  if (!status || (!status.configured && !status.numbers.length)) return null;
  const act = async (work: () => Promise<WaStatus>, done?: string) => {
    setBusy(true);
    setNote(null);
    try {
      setStatus(await work());
      if (done) setNote(done);
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  const approved = status.templates.filter((t) => t.status === "APPROVED");

  return (
    <section className={styles.waSettings} aria-label="WhatsApp">
      <div className={styles.waHead}>
        <MessageCircle size={18} aria-hidden="true" />
        <h3>WhatsApp</h3>
        {!status.configured ? (
          <Badge>Coming soon</Badge>
        ) : status.numbers.length ? (
          <Badge tone="good">Connected</Badge>
        ) : null}
      </div>
      <p className={styles.hint}>
        Talk to leads on your own WhatsApp Business number, inside Leads. Meta
        bills your business for its messages; Sales Xray adds nothing.
      </p>
      {status.configured ? (
        <a
          className={styles.waConnect}
          href={START_URL}
          onClick={connect}
          data-variant={status.numbers.length ? undefined : "primary"}
        >
          {status.numbers.length ? "Add a number" : "Connect WhatsApp"}
        </a>
      ) : null}
      {status.numbers.map((number) => (
        <article key={number.id} className={styles.waNumber}>
          <div className={styles.capiStatus}>
            <span>
              <strong>{number.verifiedName ?? number.displayNumber}</strong>{" "}
              <small>{number.displayNumber}</small>
              {number.quality ? (
                <Badge>{number.quality.toLowerCase()} quality</Badge>
              ) : null}
            </span>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                act(
                  () =>
                    waCall<WaStatus>(
                      `/whatsapp/numbers/${number.id}/disconnect`,
                      {
                        method: "POST",
                      },
                    ),
                  `${number.displayNumber} is disconnected.`,
                )
              }
            >
              Disconnect
            </Button>
          </div>
          <AutoRepliesForm
            key={JSON.stringify(number.autoReplies)}
            number={number}
            approved={approved}
            onSaved={setStatus}
          />
          <div className={styles.waTemplates}>
            <div className={styles.capiStatus}>
              <strong>Templates</strong>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  act(
                    () =>
                      waCall<WaStatus>(
                        `/whatsapp/numbers/${number.id}/templates/sync`,
                        {
                          method: "POST",
                        },
                      ),
                    "Templates brought in from Meta.",
                  )
                }
              >
                <RefreshCw size={14} aria-hidden="true" />
                Check with Meta
              </Button>
            </div>
            <ul>
              {status.templates.map((template) => (
                <li key={`${template.name}|${template.language}`}>
                  <span>
                    <strong>{template.name}</strong>{" "}
                    <small>{template.language}</small>
                    <small className={styles.waTemplateText}>
                      {template.text}
                    </small>
                  </span>
                  <Badge tone={TEMPLATE_STATUS[template.status] ?? "neutral"}>
                    {template.status.toLowerCase()}
                  </Badge>
                </li>
              ))}
            </ul>
            <NewTemplate number={number} onSaved={setStatus} />
          </div>
        </article>
      ))}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </section>
  );
}
