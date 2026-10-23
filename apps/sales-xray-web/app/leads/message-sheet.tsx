"use client";

/**
 * Message a lead on WhatsApp or SMS with a ready, name-filled message
 * (Privyr's quick responses, NeoDove's after-call templates; UX study item 2).
 * The seller reads it, changes it if they like, and it opens in their own
 * WhatsApp or Messages app with the text ready. The lead's history gets
 * "Sent a WhatsApp · Tried calling"; the text itself is never stored.
 */

import { MessageCircle, MessageSquareText, Send } from "lucide-react";
import { createContext, useState } from "react";

import { ActionSheet } from "./action-sheet";
import {
  displayPhone,
  fillTemplate,
  firstName,
  logMessage,
  smsHref,
  whatsappHref,
  type Channel,
  type LeadDetail,
  type MessageTemplate,
} from "./leads-client";
import { buzz } from "./native-phone";
import styles from "./leads.module.css";

/** The ready messages and the names that fill them, for every lead on the page. */
export const MessageSetup = createContext<{
  templates: MessageTemplate[];
  myName: string;
  org: string;
}>({ templates: [], myName: "", org: "" });

/** Opens the composer for the open lead, starting with a ready message. */
export const OpenMessage = createContext<
  ((preset?: string | null) => void) | null
>(null);

export type MessageTarget = {
  leadId: string;
  name: string;
  phone: string;
  interest: string | null;
};

export function MessageSheet({
  open,
  target,
  templates,
  myName,
  org,
  preset,
  channel: initialChannel = "whatsapp",
  onClose,
  onLogged,
}: {
  open: boolean;
  target: MessageTarget | null;
  templates: MessageTemplate[];
  myName: string;
  org: string;
  /** The ready message to start with, such as "missed_call" after a missed call. */
  preset?: string | null;
  /** The channel the person tapped (WhatsApp or SMS). */
  channel?: Channel;
  onClose: () => void;
  onLogged?: (next: LeadDetail) => void;
}) {
  const fill = (template: MessageTemplate | undefined) =>
    template && target
      ? fillTemplate(template.text, {
          leadName: target.name,
          myName,
          org,
          interest: target.interest,
        })
      : "";
  const first =
    templates.find((template) => template.key === preset) ?? templates[0];
  const [channel, setChannel] = useState<Channel>(initialChannel);
  const [picked, setPicked] = useState<string | null>(first?.key ?? null);
  const [text, setText] = useState(() => fill(first));
  const chosen = templates.find((template) => template.key === picked);
  const edited = !!chosen && text.trim() !== fill(chosen).trim();

  if (!target) return null;
  const href =
    channel === "whatsapp"
      ? whatsappHref(target.phone, text.trim())
      : smsHref(target.phone, text.trim());

  const sent = () => {
    buzz("done");
    void logMessage(target.leadId, {
      channel,
      template: picked,
      edited: edited || !picked,
    })
      .then((next) => onLogged?.(next))
      .catch(() => undefined);
    // Leave the sheet up for a moment, so coming back shows where you were.
    window.setTimeout(onClose, 400);
  };

  return (
    <ActionSheet
      open={open}
      title={`Message ${firstName(target.name) === "there" ? target.name : firstName(target.name)}`}
      sub={displayPhone(target.phone)}
      onClose={onClose}
    >
      <div className={styles.messageBody}>
        <div
          className={styles.channelSwitch}
          role="group"
          aria-label="Send with"
        >
          <button
            type="button"
            aria-pressed={channel === "whatsapp"}
            data-channel="whatsapp"
            onClick={() => setChannel("whatsapp")}
          >
            <MessageCircle size={16} aria-hidden="true" />
            WhatsApp
          </button>
          <button
            type="button"
            aria-pressed={channel === "sms"}
            data-channel="sms"
            onClick={() => setChannel("sms")}
          >
            <MessageSquareText size={16} aria-hidden="true" />
            SMS
          </button>
        </div>
        <div
          className={styles.templateChips}
          role="group"
          aria-label="Ready messages"
        >
          {templates.map((template) => (
            <button
              key={template.key}
              type="button"
              className={styles.chip}
              aria-pressed={picked === template.key}
              onClick={() => {
                setPicked(template.key);
                setText(fill(template));
              }}
            >
              {template.label}
            </button>
          ))}
        </div>
        <label className={styles.messageField}>
          <span className={styles.stepLabel}>Your message</span>
          <textarea
            rows={4}
            value={text}
            maxLength={1000}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <a
          className={styles.sendButton}
          data-channel={channel}
          href={href}
          target={channel === "whatsapp" ? "_blank" : undefined}
          rel="noreferrer"
          aria-disabled={!text.trim() || undefined}
          onClick={(event) => {
            if (!text.trim()) {
              event.preventDefault();
              return;
            }
            sent();
          }}
        >
          <Send size={18} aria-hidden="true" />
          {channel === "whatsapp" ? "Open WhatsApp" : "Open Messages"}
        </a>
        <p className={styles.hint}>
          It opens in your own{" "}
          {channel === "whatsapp" ? "WhatsApp" : "Messages"} app with the text
          ready. Sales X-Ray notes that you sent it, not what it said.
        </p>
      </div>
    </ActionSheet>
  );
}
