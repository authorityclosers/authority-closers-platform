"use client";

/**
 * One lead's WhatsApp conversation in the lead sheet: the thread, and a reply box
 * that follows WhatsApp's rules. Inside 24 hours of the person's last message the
 * seller writes freely; after that, an approved template, and only to someone who
 * agreed to WhatsApp (they wrote in, said yes on the form, or told the seller).
 */

import { MessageCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { chatHref } from "../chats/chats-client";
import { Badge, Button } from "../ui/kit";
import { AiHelp, useLeadAi } from "./ai-replies";
import { ago, LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import {
  filled,
  sendWhatsApp,
  waCall,
  windowLine,
  type WaConversation,
  type WaMessage,
  type WaTemplate,
} from "./whatsapp-client";

// The drawer keeps the latest few; the whole chat lives in Chats (owner, 20 Oct).
const RECENT = 3;

const STATUS: Record<string, string> = {
  queued: "Sending",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Not sent",
};

function Bubble({ message }: { message: WaMessage }) {
  return (
    <li className={styles.waBubble} data-direction={message.direction}>
      <p>
        {message.text ??
          (message.template
            ? `Template: ${message.template}`
            : "A file or something WhatsApp can't show here")}
      </p>
      <small>
        {ago(message.at)}
        {message.direction === "out"
          ? ` · ${message.auto ? "Automatic" : (message.by ?? "Sales Xray")} · ${STATUS[message.status] ?? message.status}`
          : null}
        {message.error ? ` · ${message.error}` : null}
      </small>
    </li>
  );
}

function TemplatePicker({
  templates,
  onSend,
  busy,
}: {
  templates: WaTemplate[];
  onSend: (template: WaTemplate, values: string[]) => void;
  busy: boolean;
}) {
  const [picked, setPicked] = useState<WaTemplate | null>(templates[0] ?? null);
  const [values, setValues] = useState<string[]>([]);
  if (!templates.length)
    return (
      <p className={styles.hint}>
        No approved templates yet. A manager adds them in Settings →
        Integrations → WhatsApp.
      </p>
    );
  return (
    <div className={styles.waTemplate}>
      <select
        aria-label="Template"
        value={picked ? `${picked.name}|${picked.language}` : ""}
        onChange={(event) => {
          const [name, language] = event.target.value.split("|");
          setPicked(
            templates.find((t) => t.name === name && t.language === language) ??
              null,
          );
          setValues([]);
        }}
      >
        {templates.map((template) => (
          <option
            key={`${template.name}|${template.language}`}
            value={`${template.name}|${template.language}`}
          >
            {template.name} ({template.language})
          </option>
        ))}
      </select>
      {picked
        ? Array.from({ length: picked.parts }, (_, index) => (
            <input
              key={index}
              aria-label={`Part ${index + 1}`}
              placeholder={`Part ${index + 1}`}
              value={values[index] ?? ""}
              maxLength={200}
              onChange={(event) =>
                setValues((current) => {
                  const next = [...current];
                  next[index] = event.target.value;
                  return next;
                })
              }
            />
          ))
        : null}
      {picked ? (
        <p className={styles.waPreview}>{filled(picked.text, values)}</p>
      ) : null}
      <Button
        variant="primary"
        disabled={
          busy ||
          !picked ||
          values.filter((value) => value.trim()).length < (picked?.parts ?? 0)
        }
        onClick={() => picked && onSend(picked, values)}
      >
        Send template
      </Button>
    </div>
  );
}

export function WhatsAppThread({
  leadId,
  canSend,
  onChanged,
}: {
  leadId: string;
  canSend: boolean;
  onChanged?: () => void;
}) {
  const [chat, setChat] = useState<WaConversation | null>(null);
  const [text, setText] = useState("");
  const [how, setHow] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ai = useLeadAi(leadId);

  useEffect(() => {
    let live = true;
    waCall<WaConversation>(`/leads/${leadId}/whatsapp`)
      .then((data) => live && setChat(data))
      .catch(() => live && setChat(null));
    return () => {
      live = false;
    };
  }, [leadId]);

  if (!chat?.configured || !chat.connected) return null;

  const run = async (work: () => Promise<WaConversation>) => {
    setBusy(true);
    setNote(null);
    try {
      const next = await work();
      setChat(next);
      const last = next.messages[next.messages.length - 1];
      if (last?.status === "failed")
        setNote(last.error ?? "WhatsApp didn't take it.");
      onChanged?.();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.waThread} aria-label="WhatsApp">
      <div className={styles.waHead}>
        <MessageCircle size={16} aria-hidden="true" />
        <h3 className={styles.stepLabel}>WhatsApp</h3>
        {chat.optedIn ? (
          <Badge tone="good">
            Agreed{chat.optInHow ? ` · ${chat.optInHow}` : ""}
          </Badge>
        ) : (
          <Badge>Not agreed yet</Badge>
        )}
        {chat.messages.length ? (
          <Link
            className={styles.openChats}
            href={chatHref("whatsapp", leadId)}
            prefetch={false}
          >
            Open in Chats
          </Link>
        ) : null}
      </div>
      {chat.messages.length > RECENT ? (
        <p className={styles.hint}>
          {chat.messages.length - RECENT} earlier message
          {chat.messages.length - RECENT === 1 ? "" : "s"} in Chats
        </p>
      ) : null}
      {chat.messages.length ? (
        <ol className={styles.waMessages}>
          {chat.messages.slice(-RECENT).map((message) => (
            <Bubble key={message.id} message={message} />
          ))}
        </ol>
      ) : (
        <p className={styles.hint}>No WhatsApp with this lead yet.</p>
      )}
      {canSend ? (
        <>
          <p className={styles.hint}>{windowLine(chat)}</p>
          <AiHelp
            ai={ai}
            leadId={leadId}
            channel="whatsapp"
            onDraft={setText}
          />
          {chat.windowOpen ? (
            <div className={styles.waCompose}>
              <textarea
                aria-label="WhatsApp message"
                value={text}
                maxLength={4096}
                rows={2}
                placeholder="Write a reply"
                onChange={(event) => setText(event.target.value)}
              />
              <Button
                variant="primary"
                disabled={busy || !text.trim()}
                onClick={() =>
                  run(async () => {
                    const next = await sendWhatsApp(leadId, {
                      text: text.trim(),
                    });
                    setText("");
                    return next;
                  })
                }
              >
                Send
              </Button>
            </div>
          ) : chat.optedIn ? (
            <TemplatePicker
              templates={chat.templates}
              busy={busy}
              onSend={(template, values) =>
                run(() =>
                  sendWhatsApp(leadId, {
                    template: template.name,
                    language: template.language,
                    values,
                  }),
                )
              }
            />
          ) : (
            <div className={styles.waOptIn}>
              <p className={styles.hint}>
                WhatsApp needs their yes before you message first. When they say
                yes, note how and save it.
              </p>
              <input
                aria-label="How they agreed"
                placeholder="e.g. Said yes on the call"
                value={how}
                maxLength={200}
                onChange={(event) => setHow(event.target.value)}
              />
              <Button
                disabled={busy}
                onClick={() =>
                  run(() =>
                    waCall<WaConversation>(`/leads/${leadId}/whatsapp/opt-in`, {
                      method: "POST",
                      body: JSON.stringify({
                        commandId: crypto.randomUUID(),
                        agreed: true,
                        how: how.trim() || "Told the seller",
                      }),
                    }),
                  )
                }
              >
                They agreed to WhatsApp
              </Button>
            </div>
          )}
        </>
      ) : null}
      {note ? (
        <p className={styles.error} role="alert">
          {note}
        </p>
      ) : null}
    </section>
  );
}
