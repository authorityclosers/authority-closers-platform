import { Camera, MessageCircle, MessageSquare } from "lucide-react";
import type { CSSProperties } from "react";

import { Avatar } from "../ui/kit";
import { CHANNEL_LABEL, type ChatChannel } from "./chats-client";
import styles from "./chats.module.css";

const ICONS = {
  whatsapp: MessageCircle,
  messenger: MessageSquare,
  instagram: Camera,
} as const;

/** The channel's own colour and mark, small: WhatsApp, Messenger, Instagram. */
export function ChannelMark({
  channel,
  size = 16,
  labelled = false,
}: {
  channel: ChatChannel;
  size?: number;
  labelled?: boolean;
}) {
  const Icon = ICONS[channel];
  return (
    <span
      className={styles.channelMark}
      data-channel={channel}
      style={{ "--mark": `${size}px` } as CSSProperties}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? CHANNEL_LABEL[channel] : undefined}
      aria-hidden={labelled ? undefined : "true"}
    >
      <Icon
        size={Math.round(size * 0.62)}
        strokeWidth={2.25}
        aria-hidden="true"
      />
    </span>
  );
}

/** The person's initials with their channel's mark on the corner. */
export function ChatAvatar({
  name,
  channel,
  size = 40,
}: {
  name: string;
  channel: ChatChannel;
  size?: number;
}) {
  return (
    <span className={styles.chatAvatar} aria-hidden="true">
      <Avatar name={name} size={size} />
      <ChannelMark
        channel={channel}
        size={Math.max(14, Math.round(size * 0.42))}
      />
    </span>
  );
}
