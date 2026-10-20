"use client";

/**
 * The AI's suggested reply in a chat ("Suggest" mode): one chip above the reply
 * box puts a draft in the box to read, change and send. It shows only while
 * the organisation's AI replies are on for this channel (Admin switch and the
 * organisation's own setting), and says plainly when a person should answer.
 */

import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import {
  draftReply,
  draftStatus,
  HANDOFF_WORDS,
  leadAi,
  type AiDraft,
  type AiLeadState,
} from "../leads/ai-replies-client";
import { LeadsError } from "../leads/leads-client";
import type { ChatChannel } from "./chats-client";
import styles from "./chats.module.css";

const POLL_MS = 1500;
const POLL_TRIES = 30;

/** This lead's AI state, or null when there is none (off, or not answering). */
export function useLeadAiState(leadId: string): AiLeadState | null {
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

/** The chip shows for this channel only while drafts can come. */
export function aiOffers(
  ai: AiLeadState | null,
  channel: ChatChannel,
): boolean {
  return (
    !!ai &&
    ai.available &&
    ai.mode !== "off" &&
    ai.channels.includes(channel) &&
    ai.ready &&
    !ai.paused
  );
}

async function written(leadId: string, first: AiDraft): Promise<AiDraft> {
  let answer = first;
  for (
    let tries = 0;
    answer.status === "queued" && answer.replyId && tries < POLL_TRIES;
    tries += 1
  ) {
    await new Promise((done) => setTimeout(done, POLL_MS));
    answer = await draftStatus(leadId, answer.replyId);
  }
  return answer;
}

export function AiChip({
  ai,
  leadId,
  channel,
  accountId,
  onDraft,
}: {
  ai: AiLeadState | null;
  leadId: string;
  channel: ChatChannel;
  accountId?: string | null;
  onDraft: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ words: string; tone: string } | null>(
    null,
  );
  // Only while the organisation's AI replies are on for this channel.
  if (!ai?.available || ai.mode === "off" || !ai.channels.includes(channel))
    return null;
  const handoff = ai.handoffs.find((item) => item.channel === channel);
  if (!aiOffers(ai, channel) && !handoff) return null;
  const ask = async () => {
    setBusy(true);
    setNote(null);
    try {
      const answer = await written(
        leadId,
        await draftReply(leadId, { channel, accountId }),
      );
      if (answer.draft && !answer.handoff && answer.status !== "queued") {
        onDraft(answer.draft);
        setNote({
          words: "AI draft in the box: read it, change anything, then send.",
          tone: "accent",
        });
      } else
        setNote({
          words:
            answer.status === "queued" || answer.status === "failed"
              ? HANDOFF_WORDS.failed
              : `A person should answer. ${answer.words || HANDOFF_WORDS[answer.reason ?? ""] || ""}`.trim(),
          tone: "warn",
        });
    } catch (reason) {
      setNote({
        words:
          reason instanceof LeadsError ? reason.message : HANDOFF_WORDS.failed,
        tone: "warn",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.aiRow}>
      {aiOffers(ai, channel) ? (
        <button
          type="button"
          className={styles.aiChip}
          aria-busy={busy || undefined}
          disabled={busy}
          onClick={() => void ask()}
        >
          <Sparkles size={14} aria-hidden="true" />
          {busy ? "Writing a draft…" : "Suggest a reply"}
        </button>
      ) : null}
      {note ? (
        <span className={styles.aiNote} data-tone={note.tone} role="status">
          {note.words}
        </span>
      ) : handoff ? (
        <span className={styles.aiNote} data-tone="warn" role="status">
          A person should answer:{" "}
          {HANDOFF_WORDS[handoff.reason] ?? handoff.reason}
        </span>
      ) : null}
    </div>
  );
}
