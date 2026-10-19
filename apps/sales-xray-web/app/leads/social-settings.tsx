"use client";

/**
 * Messenger and Instagram in Settings → Integrations: the organisation connects
 * its Facebook Pages (and the Instagram accounts linked to them), and for each
 * Page picks its channels, auto replies and comment rules (a keyword in a comment
 * sends the commenter one private message and makes them a lead). Owners and
 * admins only.
 */

import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, Button, Field } from "../ui/kit";
import { useAppConnect } from "./app-connect";
import { LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import {
  CONNECT_URL,
  keywordList,
  type CommentRule,
  type MessagingStatus,
  type PageSettings,
  type SocialPage,
} from "./social-client";
import { waCall } from "./whatsapp-client";

// Instagram is named only when a connected Page has an Instagram account.
const CONNECTED_WITH_INSTAGRAM =
  "Connected. Messages to your Page and its Instagram account now arrive in Leads.";
const RETURNED: Record<string, string> = {
  connected: "Connected. Messages to your Page now arrive in Leads.",
  nopages: "No Pages were shared. Connect again and tick your Page.",
  taken: "That Page is connected to another organisation.",
  cancelled: "Connecting was cancelled.",
  failed: "That didn't finish. Try connecting again.",
};

function RuleEditor({
  rule,
  onChange,
  onRemove,
}: {
  rule: CommentRule;
  onChange: (next: CommentRule) => void;
  onRemove: () => void;
}) {
  const [words, setWords] = useState(rule.keywords.join(", "));
  return (
    <fieldset className={styles.waRules}>
      <div className={styles.row}>
        <Field
          label="Keywords"
          hint="Separated by commas, e.g. price, site visit. Any case."
        >
          <input
            value={words}
            maxLength={600}
            onChange={(event) => {
              setWords(event.target.value);
              onChange({ ...rule, keywords: keywordList(event.target.value) });
            }}
          />
        </Field>
        <Button variant="ghost" onClick={onRemove} aria-label="Remove rule">
          <Trash2 size={14} aria-hidden="true" />
        </Button>
      </div>
      <Field
        label="Private message"
        hint="Sent once to the person who commented. {first_name} becomes their first name."
      >
        <textarea
          value={rule.reply}
          maxLength={1000}
          rows={2}
          onChange={(event) => onChange({ ...rule, reply: event.target.value })}
        />
      </Field>
      <Field
        label="Public answer under the comment (optional)"
        hint="On Instagram for now; on Facebook only the private message goes."
      >
        <input
          value={rule.publicReply ?? ""}
          maxLength={300}
          placeholder="e.g. We've sent you a message."
          onChange={(event) =>
            onChange({ ...rule, publicReply: event.target.value || null })
          }
        />
      </Field>
    </fieldset>
  );
}

function PageForm({
  page,
  onSaved,
}: {
  page: SocialPage;
  onSaved: (status: MessagingStatus) => void;
}) {
  const [form, setForm] = useState<PageSettings>(page.settings);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setNote(null);
    try {
      onSaved(
        await waCall<MessagingStatus>(`/messaging/accounts/${page.id}`, {
          method: "PUT",
          body: JSON.stringify(form),
        }),
      );
      setNote("Saved.");
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  const check = (label: string, value: boolean, set: (on: boolean) => void) => (
    <label className={styles.slaField}>
      <input
        type="checkbox"
        checked={value}
        onChange={(event) => set(event.target.checked)}
      />
      {label}
    </label>
  );
  return (
    <div className={styles.waRules}>
      {check("Messenger conversations", form.messenger, (on) =>
        setForm({ ...form, messenger: on }),
      )}
      {page.hasInstagram
        ? check(
            `Instagram conversations (@${page.igUsername ?? "linked account"})`,
            form.instagram,
            (on) => setForm({ ...form, instagram: on }),
          )
        : null}
      {page.hasInstagram && form.instagram ? (
        <p className={styles.hint}>
          In Instagram, turn on Settings → Messages and story replies → Message
          controls → Connected tools → Allow access to messages.
        </p>
      ) : null}
      {check(
        "Let sellers answer personally up to 7 days later (Meta's Human Agent rule)",
        form.humanAgent,
        (on) => setForm({ ...form, humanAgent: on }),
      )}
      {check(
        "Greet people who write for the first time",
        form.firstReply.on,
        (on) => setForm({ ...form, firstReply: { ...form.firstReply, on } }),
      )}
      {form.firstReply.on ? (
        <Field
          label="First reply"
          hint="{first_name} becomes their first name."
        >
          <textarea
            value={form.firstReply.text ?? ""}
            maxLength={1000}
            rows={2}
            onChange={(event) =>
              setForm({
                ...form,
                firstReply: { ...form.firstReply, text: event.target.value },
              })
            }
          />
        </Field>
      ) : null}
      {check(
        "Reply to messages that arrive outside your work hours",
        form.outOfHours.on,
        (on) => setForm({ ...form, outOfHours: { ...form.outOfHours, on } }),
      )}
      {form.outOfHours.on ? (
        <Field
          label="After-hours reply"
          hint="Sent at most once in 12 hours to each person."
        >
          <textarea
            value={form.outOfHours.text ?? ""}
            maxLength={1000}
            rows={2}
            onChange={(event) =>
              setForm({
                ...form,
                outOfHours: { ...form.outOfHours, text: event.target.value },
              })
            }
          />
        </Field>
      ) : null}
      <strong>Comments that send a message</strong>
      {form.comments.map((rule, index) => (
        <RuleEditor
          key={index}
          rule={rule}
          onChange={(next) =>
            setForm({
              ...form,
              comments: form.comments.map((r, i) => (i === index ? next : r)),
            })
          }
          onRemove={() =>
            setForm({
              ...form,
              comments: form.comments.filter((_, i) => i !== index),
            })
          }
        />
      ))}
      <Button
        variant="ghost"
        disabled={form.comments.length >= 20}
        onClick={() =>
          setForm({
            ...form,
            comments: [
              ...form.comments,
              { on: true, keywords: [], reply: "", publicReply: null },
            ],
          })
        }
      >
        <Plus size={14} aria-hidden="true" />
        Add a comment rule
      </Button>
      <Button disabled={busy} onClick={save}>
        Save
      </Button>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </div>
  );
}

export function SocialSettings() {
  const params = useSearchParams();
  const [status, setStatus] = useState<MessagingStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    RETURNED[params?.get("messaging") ?? ""] ?? null,
  );
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(0);
  // In the Sales Xray app, Connect opens Facebook in the phone's browser and
  // finishes back here (Facebook refuses sign-in inside the app).
  const connect = useAppConnect("messaging", ({ result, message }) => {
    setNote(message ?? RETURNED[result] ?? RETURNED.failed);
    if (result === "connected") setLoaded((times) => times + 1);
  });

  useEffect(() => {
    let live = true;
    waCall<MessagingStatus>("/messaging/status")
      .then(
        (data) =>
          live &&
          setStatus(
            Array.isArray(data?.accounts)
              ? data
              : { configured: false, accounts: [] },
          ),
      )
      .catch(() => live && setStatus({ configured: false, accounts: [] }));
    return () => {
      live = false;
    };
  }, [loaded]);

  // Hidden until AC's Messaging app is set up for Sales Xray (nothing to connect yet).
  if (!status || (!status.configured && !status.accounts.length)) return null;
  const shown =
    note === RETURNED.connected &&
    status.accounts.some((account) => account.hasInstagram)
      ? CONNECTED_WITH_INSTAGRAM
      : note;

  const disconnect = async (page: SocialPage) => {
    setBusy(true);
    setNote(null);
    try {
      setStatus(
        await waCall<MessagingStatus>(
          `/messaging/accounts/${page.id}/disconnect`,
          { method: "POST" },
        ),
      );
      setNote(`${page.pageName} is disconnected.`);
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.waSettings} aria-label="Messenger and Instagram">
      <div className={styles.waHead}>
        <MessageSquare size={18} aria-hidden="true" />
        <h3>Messenger &amp; Instagram</h3>
        {!status.configured ? (
          <Badge>Coming soon</Badge>
        ) : status.accounts.length ? (
          <Badge tone="good">Connected</Badge>
        ) : null}
      </div>
      <p className={styles.hint}>
        Messages to your Facebook Page and its Instagram account arrive in Leads
        and go to your sellers by your rules. A keyword in a comment can send
        the person a message and make them a lead.
      </p>
      {status.configured ? (
        <a
          className={styles.waConnect}
          href={CONNECT_URL}
          onClick={connect}
          data-variant={status.accounts.length ? undefined : "primary"}
        >
          {status.accounts.length
            ? "Add a Page"
            : "Connect Messenger & Instagram"}
        </a>
      ) : null}
      {status.accounts.map((page) => (
        <article key={page.id} className={styles.waNumber}>
          <div className={styles.capiStatus}>
            <span>
              <strong>{page.pageName}</strong>{" "}
              {page.igUsername ? <small>@{page.igUsername}</small> : null}
            </span>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => disconnect(page)}
            >
              Disconnect
            </Button>
          </div>
          <PageForm key={page.id} page={page} onSaved={setStatus} />
        </article>
      ))}
      {shown ? (
        <p className={styles.hint} role="status">
          {shown}
        </p>
      ) : null}
    </section>
  );
}
