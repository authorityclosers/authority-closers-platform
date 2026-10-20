"use client";

/**
 * One conversation, the way people know chats: bubbles, a day line between
 * days, sent / delivered / read ticks, and a reply box that knows Meta's
 * 24-hour window and says plainly why it can't send when it can't. Photos,
 * voice notes, videos and files show in the bubble (message-media.tsx). A
 * message goes out as "Sending…" and turns into ticks, or into the reason it
 * didn't go with a "Send again".
 */

import {
  ArrowLeft,
  Camera,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  MapPin,
  Mic,
  Paperclip,
  RotateCcw,
  SendHorizontal,
  Smile,
  Sticker,
  UserRound,
  Video,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { LeadsError } from "../leads/leads-client";
import { notify } from "../notice-center";
import { Skeleton } from "../ui/kit";
import { AiChip, useLeadAiState } from "./ai-chip";
import { ChatAvatar } from "./channel-mark";
import {
  attachmentLabel,
  clockTime,
  composerState,
  dayGroups,
  hasMedia,
  readThread,
  sendText,
  type ChatChannel,
  type ChatDetail,
  type ChatMessage,
  type ChatThread,
} from "./chats-client";
import styles from "./chats.module.css";
import { MessageMedia } from "./message-media";
import { OptInBox, TemplateComposer } from "./template-composer";
import { Ticks } from "./ticks";

// The open chat reads again every 10 s while in view (a shared server).
const POLL_MS = 10 * 1000;
const MIN_GAP_MS = 5 * 1000;
const SENDING_EVERY_MS = 2 * 1000;
const SENDING_FOR_MS = 60 * 1000;
const STICK_PX = 96;

const AUTO: Record<string, string> = {
  first_reply: "Automatic first reply",
  out_of_hours: "Automatic after-hours reply",
  comment_reply: "Private reply to their comment",
  ai: "AI reply",
};

const ATTACHMENT_ICONS: Record<string, typeof Paperclip> = {
  image: ImageIcon,
  video: Video,
  audio: Mic,
  document: FileText,
  file: FileText,
  sticker: Sticker,
  location: MapPin,
  share: ExternalLink,
  story_reply: Camera,
  story_mention: Camera,
  reaction: Smile,
};

function Bubble({
  channel,
  message,
  first,
  last,
  onRetry,
}: {
  channel: ChatChannel;
  message: ChatMessage;
  first: boolean;
  last: boolean;
  /** A written message that didn't go: send the same words again. */
  onRetry?: () => void;
}) {
  const media = hasMedia(message);
  const attachment = media ? null : attachmentLabel(message.kind);
  const Icon = ATTACHMENT_ICONS[message.kind] ?? Paperclip;
  const out = message.direction === "out";
  const who = message.auto
    ? (AUTO[message.auto] ?? "Automatic reply")
    : out
      ? (message.by ?? null)
      : null;
  return (
    <li
      className={styles.bubbleRow}
      data-dir={message.direction}
      data-first={first || undefined}
      data-last={last || undefined}
    >
      <div
        className={styles.bubble}
        data-failed={message.status === "failed" || undefined}
      >
        {message.kind === "comment" ? (
          <span className={styles.bubbleTag}>Comment on your post</span>
        ) : null}
        {message.template ? (
          <span className={styles.bubbleTag}>Template</span>
        ) : null}
        {media ? <MessageMedia channel={channel} message={message} /> : null}
        {attachment ? (
          <span className={styles.attachment}>
            <Icon size={16} aria-hidden="true" />
            {attachment}
          </span>
        ) : null}
        {message.text ? (
          <p className={styles.bubbleText}>{message.text}</p>
        ) : null}
        {!message.text && !attachment && !media ? (
          <p className={styles.bubbleText} data-quiet>
            {message.kind === "comment"
              ? "(comment removed)"
              : "A message this app can't show"}
          </p>
        ) : null}
        <span className={styles.bubbleMeta}>
          {who ? <span className={styles.bubbleWho}>{who}</span> : null}
          {message.humanAgent ? <span>Answered personally</span> : null}
          {message.status === "queued" ? (
            <span className={styles.sending}>Sending…</span>
          ) : (
            <time dateTime={message.at}>{clockTime(message.at)}</time>
          )}
          {out ? <Ticks status={message.status} size={14} /> : null}
        </span>
      </div>
      {message.status === "failed" ? (
        <p className={styles.failedLine}>
          Not sent{message.error ? `: ${message.error}` : "."}
          {onRetry ? (
            <button
              type="button"
              className={styles.retryButton}
              onClick={onRetry}
            >
              <RotateCcw size={13} aria-hidden="true" />
              Send again
            </button>
          ) : null}
        </p>
      ) : null}
    </li>
  );
}

function MessagesSkeleton() {
  return (
    <div className={styles.messagesSkeleton} aria-hidden="true">
      {[62, 44, 70, 38, 56].map((width, index) => (
        <span key={index} data-dir={index % 2 ? "out" : "in"}>
          <Skeleton width={`${width}%`} height={index === 2 ? 52 : 36} />
        </span>
      ))}
    </div>
  );
}

type Delivery = {
  onSent: (next: ChatDetail | null) => void;
  onPending: (message: ChatMessage | null) => void;
};

/**
 * Send written words: a "Sending…" bubble at once, then the server's answer
 * (queued, sent or refused, with Meta's reason). Throws when the request
 * itself failed, after taking the bubble back.
 */
async function deliver(
  leadId: string,
  detail: ChatDetail,
  words: string,
  { onSent, onPending }: Delivery,
): Promise<ChatDetail | null> {
  onPending({
    id: `pending-${Date.now()}`,
    direction: "out",
    kind: "text",
    text: words,
    status: "queued",
    at: new Date().toISOString(),
  });
  try {
    const next = await sendText(leadId, detail, words);
    onSent(next);
    return next;
  } catch (reason) {
    onPending(null);
    throw reason;
  }
}

function notSent(reason: unknown) {
  notify({
    id: "chats-send",
    tone: "error",
    title: "Not sent",
    message:
      reason instanceof LeadsError
        ? reason.message
        : "That didn't go. Try again.",
  });
}

function Composer({
  detail,
  leadId,
  onSent,
  onPending,
}: {
  detail: ChatDetail;
  leadId: string;
  onSent: (next: ChatDetail | null) => void;
  onPending: (message: ChatMessage | null) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const ai = useLeadAiState(leadId);
  const state = composerState(detail);
  const send = async () => {
    const words = text.trim();
    if (!words || busy) return;
    setBusy(true);
    setText("");
    try {
      const next = await deliver(leadId, detail, words, { onSent, onPending });
      const last = next?.messages[next.messages.length - 1];
      if (last?.direction === "out" && last.status === "failed") setText(words);
    } catch (reason) {
      setText(words);
      notSent(reason);
    } finally {
      setBusy(false);
    }
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends on a keyboard; on a touch screen Enter is a new line.
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing &&
      window.matchMedia("(pointer: fine)").matches
    ) {
      event.preventDefault();
      void send();
    }
  };
  return (
    <div className={styles.composer}>
      {state.line ? (
        <p className={styles.windowLine} data-tone={state.tone}>
          {state.line}
        </p>
      ) : null}
      {detail.channel === "whatsapp" && !detail.windowOpen ? (
        detail.optedIn ? (
          <TemplateComposer detail={detail} leadId={leadId} onSent={onSent} />
        ) : (
          <OptInBox leadId={leadId} onSaved={onSent} />
        )
      ) : null}
      {state.canWrite ? (
        <AiChip
          ai={ai}
          leadId={leadId}
          channel={detail.channel}
          accountId={detail.accountId}
          onDraft={setText}
        />
      ) : null}
      {state.canWrite ? (
        <div className={styles.composeBox}>
          <textarea
            aria-label="Write a reply"
            placeholder="Write a reply"
            rows={1}
            value={text}
            maxLength={
              detail.channel === "instagram"
                ? 1000
                : detail.channel === "messenger"
                  ? 2000
                  : 4096
            }
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKey}
          />
          <button
            type="button"
            className={styles.sendButton}
            aria-label="Send"
            title="Send"
            disabled={busy || !text.trim()}
            onClick={() => void send()}
          >
            <SendHorizontal size={18} aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function ThreadView({
  thread,
  leadShown = false,
  onLead,
  onBack,
  onChanged,
  onSeen,
}: {
  thread: Pick<ChatThread, "key" | "channel" | "leadId" | "accountId"> &
    Partial<Pick<ChatThread, "leadName" | "place">>;
  /** The lead's panel is open beside the chat. */
  leadShown?: boolean;
  /** Show or hide the lead (a sheet on phones). */
  onLead?: () => void;
  onBack: () => void;
  /** Something was sent: the list reads again. */
  onChanged: () => void;
  /** Read up to this message (its time) while on screen: the read mark. */
  onSeen?: (at: string, accountId: string | null) => void;
}) {
  const [detail, setDetail] = useState<ChatDetail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [pending, setPending] = useState<ChatMessage | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const { channel, leadId, accountId } = thread;

  const [round, setRound] = useState(0);
  const again = () => setRound((value) => value + 1);
  // A read that started before a send must not undo the sent message: each
  // send moves the epoch on, and older answers are dropped (orchestrator's
  // dev pass, 20 Oct: the new bubble vanished until a later poll).
  const epoch = useRef(0);
  const readAt = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const started = epoch.current;
    readAt.current = Date.now();
    readThread({ channel, leadId, accountId }, controller.signal)
      .then((next) => {
        if (started !== epoch.current) return;
        setDetail(next);
        setFailed(next ? null : "This chat isn't here any more.");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setFailed(
          reason instanceof LeadsError
            ? reason.message
            : "This chat didn't load. Try again.",
        );
      });
    return () => controller.abort();
  }, [channel, leadId, accountId, round]);

  // New messages while it is open: every 10 s in view, none while hidden, and
  // once on coming back (at most every 5 s).
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible")
        setRound((value) => value + 1);
    }, POLL_MS);
    const back = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - readAt.current > MIN_GAP_MS
      )
        setRound((value) => value + 1);
    };
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
    };
  }, []);

  // A message still sending (queued on the server): read again every 2 s
  // until it is sent or refused, for up to a minute.
  const sending =
    detail?.messages.some(
      (message) => message.direction === "out" && message.status === "queued",
    ) ?? false;
  useEffect(() => {
    if (!sending) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (Date.now() - started > SENDING_FOR_MS) {
        window.clearInterval(timer);
        return;
      }
      if (document.visibilityState === "visible")
        setRound((value) => value + 1);
    }, SENDING_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [sending]);

  // The newest message on screen is read (while the page is in view).
  const seenRef = useRef(onSeen);
  useEffect(() => {
    seenRef.current = onSeen;
  });
  const newest = detail?.messages[detail.messages.length - 1]?.at ?? null;
  const shownAccount = detail?.accountId ?? null;
  useEffect(() => {
    if (newest && document.visibilityState === "visible")
      seenRef.current?.(newest, shownAccount);
  }, [newest, shownAccount]);

  const count = (detail?.messages.length ?? 0) + (pending ? 1 : 0);
  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && stick.current) box.scrollTop = box.scrollHeight;
  }, [count]);

  const onScroll = () => {
    const box = scroller.current;
    if (box)
      stick.current =
        box.scrollHeight - box.scrollTop - box.clientHeight < STICK_PX;
  };

  const messages = [...(detail?.messages ?? []), ...(pending ? [pending] : [])];
  const delivery: Delivery = {
    onPending: (message) => {
      epoch.current += 1;
      stick.current = true;
      setPending(message);
    },
    onSent: (next) => {
      epoch.current += 1;
      setPending(null);
      if (next) setDetail(next);
      onChanged();
    },
  };
  const retry = (words: string) => {
    if (!detail || !leadId || pending) return;
    deliver(leadId, detail, words, delivery).catch(notSent);
  };
  // Undefined while the list loads; empty when the chat is older than it.
  const name = thread.leadName;
  return (
    <section
      className={styles.thread}
      aria-label={name ? `Chat with ${name}` : "Chat"}
    >
      <header className={styles.threadHead}>
        <button
          type="button"
          className={styles.backButton}
          aria-label="Back to chats"
          title="Back to chats"
          onClick={onBack}
        >
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <ChatAvatar name={name || "?"} channel={channel} size={36} />
        <span className={styles.threadTitle}>
          {name === undefined ? (
            <Skeleton width={140} height={14} />
          ) : (
            <strong>{name || "This chat"}</strong>
          )}
          <small>{detail?.place ?? thread.place ?? " "}</small>
        </span>
        {leadId ? (
          <button
            type="button"
            className={styles.headAction}
            aria-pressed={leadShown}
            onClick={onLead}
          >
            <UserRound size={15} aria-hidden="true" />
            Lead
          </button>
        ) : null}
      </header>
      <div
        ref={scroller}
        className={styles.messages}
        onScroll={onScroll}
        aria-live="polite"
        aria-busy={!detail && !failed}
      >
        {detail ? (
          <ol className={styles.days}>
            {dayGroups(messages).map((group) => (
              <li key={group.day}>
                <p className={styles.dayLine}>
                  <span>{group.day}</span>
                </p>
                <ol className={styles.bubbles}>
                  {group.items.map((item) => (
                    <Bubble
                      key={item.message.id}
                      channel={channel}
                      message={item.message}
                      first={item.first}
                      last={item.last}
                      onRetry={
                        item.message.direction === "out" &&
                        item.message.status === "failed" &&
                        item.message.kind === "text" &&
                        item.message.text &&
                        !item.message.auto
                          ? () => retry(item.message.text ?? "")
                          : undefined
                      }
                    />
                  ))}
                </ol>
              </li>
            ))}
          </ol>
        ) : failed ? (
          <div className={styles.listEmpty}>
            <p className={styles.emptyTitle}>{failed}</p>
            <button type="button" className={styles.linkButton} onClick={again}>
              Try again
            </button>
          </div>
        ) : (
          <MessagesSkeleton />
        )}
      </div>
      {detail && leadId ? (
        <Composer
          detail={detail}
          leadId={leadId}
          onPending={delivery.onPending}
          onSent={delivery.onSent}
        />
      ) : (
        <div className={styles.composer} aria-hidden="true">
          <div className={styles.composeBox} data-placeholder />
        </div>
      )}
    </section>
  );
}
