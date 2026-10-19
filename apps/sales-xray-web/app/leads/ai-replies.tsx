"use client";

/**
 * AI replies in the CRM.
 *
 * - Settings → Integrations → AI replies (owners and admins): off, suggest (a seller
 *   reviews each draft and taps send; the default) or auto (sent within the
 *   guardrails), the channels, whether prices may be quoted, and the business profile
 *   the AI may answer from (what you do, your services, FAQs, notes).
 * - In a lead's conversation: "Suggest a reply" fills the reply box with a draft, or
 *   says why a person should answer instead. The draft is written in the background
 *   (by the AI replies runner); the button asks every couple of seconds until it is
 *   ready. Nothing shows while AI replies are paused.
 */

import { Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Field } from "../ui/kit";
import {
  draftReply,
  draftStatus,
  HANDOFF_WORDS,
  leadAi,
  tryReply,
  tryStatus,
  type AiChannel,
  type AiDraft,
  type AiLeadState,
  type AiSettings,
} from "./ai-replies-client";
import { LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import { waCall } from "./whatsapp-client";

const MODES: { value: AiSettings["mode"]; label: string; hint: string }[] = [
  { value: "off", label: "Off", hint: "No AI drafts or replies." },
  {
    value: "suggest",
    label: "Suggest",
    hint: "The AI drafts a reply; a seller reads it and taps send.",
  },
  {
    value: "auto",
    label: "Auto",
    hint: "The AI answers by itself within the rules, and hands to a person when it should.",
  },
];
const CHANNEL_LABELS: Record<AiChannel, string> = {
  whatsapp: "WhatsApp",
  messenger: "Messenger",
  instagram: "Instagram",
};

export function AiRepliesSettings() {
  const [form, setForm] = useState<AiSettings | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    waCall<AiSettings>("/ai-replies/settings")
      .then(
        (data) =>
          live && setForm(data && Array.isArray(data.faqs) ? data : null),
      )
      .catch(() => live && setForm(null));
    return () => {
      live = false;
    };
  }, []);

  if (!form) return null;

  const save = async () => {
    setBusy(true);
    setNote(null);
    try {
      const saved = await waCall<AiSettings>("/ai-replies/settings", {
        method: "PUT",
        body: JSON.stringify({ ...form, ready: undefined }),
      });
      setForm(saved);
      setNote("Saved.");
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  const set = (patch: Partial<AiSettings>) => setForm({ ...form, ...patch });

  return (
    <section className={styles.waSettings} aria-label="AI replies">
      <div className={styles.waHead}>
        <Sparkles size={18} aria-hidden="true" />
        <h3>AI replies</h3>
        {!form.available ? (
          <Badge>Coming soon</Badge>
        ) : form.paused && form.mode !== "off" ? (
          <Badge tone="warn">Paused for now</Badge>
        ) : form.mode === "off" ? (
          <Badge>Off</Badge>
        ) : form.ready ? (
          <Badge tone="good">{form.mode === "auto" ? "Auto" : "Suggest"}</Badge>
        ) : (
          <Badge tone="warn">Add your business profile</Badge>
        )}
      </div>
      <p className={styles.hint}>
        Replies to leads on WhatsApp, Messenger and Instagram, only about your
        business and only from what you write here, in the lead&apos;s own
        language. It hands the chat to a person on complaints, price talk,
        anything it can&apos;t answer from your profile, or when they ask for a
        person, and stops when they say STOP.
      </p>
      <div className={styles.chips} role="radiogroup" aria-label="AI replies">
        {MODES.map((mode) => (
          <label key={mode.value} className={styles.slaField}>
            <input
              type="radio"
              name="ai-mode"
              checked={form.mode === mode.value}
              onChange={() => set({ mode: mode.value })}
            />
            <span>
              <strong>{mode.label}</strong> <small>{mode.hint}</small>
            </span>
          </label>
        ))}
      </div>
      <div className={styles.chips} role="group" aria-label="Channels">
        {(Object.keys(CHANNEL_LABELS) as AiChannel[]).map((channel) => (
          <label key={channel} className={styles.slaField}>
            <input
              type="checkbox"
              checked={form.channels.includes(channel)}
              onChange={(event) =>
                set({
                  channels: event.target.checked
                    ? [...form.channels, channel]
                    : form.channels.filter((c) => c !== channel),
                })
              }
            />
            {CHANNEL_LABELS[channel]}
          </label>
        ))}
      </div>
      <label className={styles.slaField}>
        <input
          type="checkbox"
          checked={form.quotePrices}
          onChange={(event) => set({ quotePrices: event.target.checked })}
        />
        Let the AI give prices exactly as written below (never discounts)
      </label>
      <Field label="Business name">
        <input
          value={form.businessName}
          maxLength={200}
          onChange={(event) => set({ businessName: event.target.value })}
        />
      </Field>
      <Field
        label="What you do"
        hint="Where you are, your hours, what a lead can do next (visit, call, book)."
      >
        <textarea
          value={form.about}
          maxLength={4000}
          rows={3}
          onChange={(event) => set({ about: event.target.value })}
        />
      </Field>
      <Field label="Products and services">
        <textarea
          value={form.offerings}
          maxLength={4000}
          rows={3}
          onChange={(event) => set({ offerings: event.target.value })}
        />
      </Field>
      <strong>Questions leads ask</strong>
      {form.faqs.map((faq, index) => (
        <fieldset key={index} className={styles.waRules}>
          <div className={styles.row}>
            <Field label="Question">
              <input
                value={faq.question}
                maxLength={300}
                onChange={(event) =>
                  set({
                    faqs: form.faqs.map((f, i) =>
                      i === index ? { ...f, question: event.target.value } : f,
                    ),
                  })
                }
              />
            </Field>
            <Button
              variant="ghost"
              aria-label="Remove question"
              onClick={() =>
                set({ faqs: form.faqs.filter((_, i) => i !== index) })
              }
            >
              <Trash2 size={14} aria-hidden="true" />
            </Button>
          </div>
          <Field label="Answer">
            <textarea
              value={faq.answer}
              maxLength={1000}
              rows={2}
              onChange={(event) =>
                set({
                  faqs: form.faqs.map((f, i) =>
                    i === index ? { ...f, answer: event.target.value } : f,
                  ),
                })
              }
            />
          </Field>
        </fieldset>
      ))}
      <Button
        variant="ghost"
        disabled={form.faqs.length >= 40}
        onClick={() =>
          set({ faqs: [...form.faqs, { question: "", answer: "" }] })
        }
      >
        <Plus size={14} aria-hidden="true" />
        Add a question
      </Button>
      <Field label="Anything else the AI should know (optional)">
        <textarea
          value={form.notes}
          maxLength={4000}
          rows={2}
          onChange={(event) => set({ notes: event.target.value })}
        />
      </Field>
      <Button disabled={busy} onClick={save}>
        Save
      </Button>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
      {form.available && form.ready && !form.paused ? <TryIt /> : null}
    </section>
  );
}

const POLL_MS = 1500;
const POLL_TRIES = 30;

/** Ask again every POLL_MS until a queued draft is written (or we stop waiting). */
async function untilWritten(
  first: AiDraft,
  again: (replyId: string) => Promise<AiDraft>,
): Promise<AiDraft> {
  let answer = first;
  for (
    let tries = 0;
    answer.status === "queued" && answer.replyId && tries < POLL_TRIES;
    tries += 1
  ) {
    await new Promise((done) => setTimeout(done, POLL_MS));
    answer = await again(answer.replyId);
  }
  return answer;
}

/** The AI's answer in the seller's words: the draft, or why a person should answer. */
function answerWords(answer: AiDraft): string {
  if (answer.status === "queued") return HANDOFF_WORDS.failed;
  if (answer.status === "paused" || answer.status === "failed")
    return answer.words || HANDOFF_WORDS.failed;
  return `A person should answer. ${answer.words || HANDOFF_WORDS[answer.reason ?? ""] || ""}`.trim();
}

/**
 * "Try it" in Settings: type a message a lead might send and see the reply the AI
 * would draft from this profile. Nothing is sent to anyone.
 */
function TryIt() {
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setAnswer(null);
    try {
      const done = await untilWritten(
        await tryReply({ message: message.trim() }),
        tryStatus,
      );
      setAnswer(
        done.status === "drafted" && done.draft
          ? `AI draft: ${done.draft}`
          : answerWords(done),
      );
    } catch (reason) {
      setAnswer(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.aiSuggest}>
      <Field label="Try it: a message a lead might send">
        <textarea
          value={message}
          maxLength={500}
          rows={2}
          onChange={(event) => setMessage(event.target.value)}
        />
      </Field>
      <Button variant="ghost" disabled={busy || !message.trim()} onClick={run}>
        <Sparkles size={14} aria-hidden="true" />
        {busy ? "Thinking…" : "Try it"}
      </Button>
      <p className={styles.hint}>Nothing is sent to anyone.</p>
      {answer ? (
        <p className={styles.hint} role="status">
          {answer}
        </p>
      ) : null}
    </div>
  );
}

/**
 * "Suggest a reply" beside a reply box: puts the AI's draft in the box, or says why
 * a person should answer instead. Shows nothing when AI replies are off.
 */
export function SuggestReply({
  leadId,
  channel,
  accountId,
  onDraft,
}: {
  leadId: string;
  channel: AiChannel;
  accountId?: string | null;
  onDraft: (text: string) => void;
}) {
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ask = async () => {
    setBusy(true);
    setNote(null);
    try {
      // Queued: the draft is written in the background; ask until it is ready.
      const answer = await untilWritten(
        await draftReply(leadId, { channel, accountId }),
        (replyId) => draftStatus(leadId, replyId),
      );
      if (answer.draft && !answer.handoff && answer.status !== "queued") {
        onDraft(answer.draft);
        setNote("AI draft: read it, change anything, then send.");
      } else {
        setNote(answerWords(answer));
      }
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.aiSuggest}>
      <Button variant="ghost" disabled={busy} onClick={ask}>
        <Sparkles size={14} aria-hidden="true" />
        {busy ? "Thinking…" : "Suggest a reply"}
      </Button>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </div>
  );
}

/** This lead's AI state: the mode, its channels, and recent hand-offs to a person. */
export function useLeadAi(leadId: string): AiLeadState | null {
  const [state, setState] = useState<AiLeadState | null>(null);
  useEffect(() => {
    let live = true;
    leadAi(leadId)
      .then(
        (data) =>
          live && setState(data && Array.isArray(data.handoffs) ? data : null),
      )
      .catch(() => live && setState(null));
    return () => {
      live = false;
    };
  }, [leadId]);
  return state;
}

/** The AI's help for one reply box: a hand-off note, and Suggest a reply. */
export function AiHelp({
  ai,
  leadId,
  channel,
  accountId,
  onDraft,
}: {
  ai: AiLeadState | null;
  leadId: string;
  channel: AiChannel;
  accountId?: string | null;
  onDraft: (text: string) => void;
}) {
  if (!ai?.available || ai.mode === "off" || !ai.channels.includes(channel))
    return null;
  const suggest = ai.ready && !ai.paused;
  const handoff = ai.handoffs.find((item) => item.channel === channel);
  return (
    <>
      {handoff ? (
        <p className={styles.aiHandoff} role="status">
          A person should answer:{" "}
          {HANDOFF_WORDS[handoff.reason] ?? handoff.reason}
        </p>
      ) : null}
      {suggest ? (
        <SuggestReply
          leadId={leadId}
          channel={channel}
          accountId={accountId}
          onDraft={onDraft}
        />
      ) : null}
    </>
  );
}
