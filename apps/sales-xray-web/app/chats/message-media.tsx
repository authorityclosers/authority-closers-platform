"use client";

/**
 * A message's photo, voice note, video or file, shown in the bubble
 * (orchestrator, 20 Oct: attachments shown, not just named). The file comes
 * from Meta through Sales Xray when the chat is open (/v1/lead-desk/chats/
 * media): never stored, never Meta's own link, and nothing reads it on the
 * way. Each kind keeps a fixed size while it loads, so the chat doesn't jump;
 * a file Meta no longer has falls back to its name.
 */

import { Download, FileText, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Sheet } from "../ui/sheet";
import {
  fileSize,
  hasMedia,
  mediaUrl,
  readMediaInfo,
  type ChatChannel,
  type ChatMessage,
  type MediaInfo,
} from "./chats-client";
import styles from "./chats.module.css";

function Gone({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className={styles.attachment}>
      <Icon size={16} aria-hidden="true" />
      {label}
    </span>
  );
}

function Photo({
  channel,
  message,
  sticker,
}: {
  channel: ChatChannel;
  message: ChatMessage;
  sticker: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const [open, setOpen] = useState(false);
  const label = sticker ? "Sticker" : "Photo";
  if (broken)
    return (
      <Gone
        icon={FileText}
        label={`${label}: not available from Meta any more`}
      />
    );
  return (
    <>
      <button
        type="button"
        className={sticker ? styles.mediaSticker : styles.mediaPhoto}
        aria-label={`Open the ${label.toLowerCase()}`}
        onClick={() => setOpen(true)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- a private, signed-in file, not a static asset */}
        <img
          src={mediaUrl(channel, message.id, { preview: !sticker })}
          alt={message.text ? `${label}: ${message.text}` : label}
          loading="lazy"
          decoding="async"
          onError={() => setBroken(true)}
        />
      </button>
      {sticker ? null : (
        <Sheet
          open={open}
          onClose={() => setOpen(false)}
          title={label}
          hideTitle
        >
          <div className={styles.mediaViewer}>
            {/* eslint-disable-next-line @next/next/no-img-element -- as above */}
            <img src={mediaUrl(channel, message.id)} alt={label} />
          </div>
        </Sheet>
      )}
    </>
  );
}

function Player({
  channel,
  message,
  video,
}: {
  channel: ChatChannel;
  message: ChatMessage;
  video: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const label = video ? "Video" : "Voice note";
  if (broken)
    return (
      <Gone
        icon={FileText}
        label={`${label}: not available from Meta any more`}
      />
    );
  // Nothing loads until play is pressed (preload none): a chat full of voice
  // notes costs nothing to open.
  return video ? (
    <video
      className={styles.mediaVideo}
      src={mediaUrl(channel, message.id)}
      controls
      playsInline
      preload="none"
      aria-label={label}
      onError={() => setBroken(true)}
    />
  ) : (
    <audio
      className={styles.mediaAudio}
      src={mediaUrl(channel, message.id)}
      controls
      preload="none"
      aria-label={label}
      onError={() => setBroken(true)}
    />
  );
}

function FileChip({
  channel,
  message,
}: {
  channel: ChatChannel;
  message: ChatMessage;
}) {
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    readMediaInfo(channel, message.id, controller.signal)
      .then(setInfo)
      .catch(() => {
        if (!controller.signal.aborted) setGone(true);
      });
    return () => controller.abort();
  }, [channel, message.id]);
  const name =
    info?.name ?? (message.kind === "document" ? "Document" : "File");
  const size = fileSize(info?.size ?? null);
  if (gone)
    return (
      <Gone icon={FileText} label="File: not available from Meta any more" />
    );
  return (
    <a
      className={styles.fileChip}
      href={mediaUrl(channel, message.id)}
      download={info?.name ?? undefined}
    >
      <FileText size={20} aria-hidden="true" />
      <span>
        <strong>{name}</strong>
        <small>{size ?? " "}</small>
      </span>
      <Download size={16} aria-hidden="true" />
    </a>
  );
}

/** The file part of a bubble; nothing for a message without one. */
export function MessageMedia({
  channel,
  message,
}: {
  channel: ChatChannel;
  message: ChatMessage;
}) {
  if (!hasMedia(message)) return null;
  switch (message.kind) {
    case "image":
    case "sticker":
      return (
        <Photo
          channel={channel}
          message={message}
          sticker={message.kind === "sticker"}
        />
      );
    case "audio":
    case "video":
      return (
        <Player
          channel={channel}
          message={message}
          video={message.kind === "video"}
        />
      );
    default:
      return <FileChip channel={channel} message={message} />;
  }
}
