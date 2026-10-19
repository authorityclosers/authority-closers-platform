import type { CSSProperties } from "react";

import { BRANDS, type Brand } from "../brands/brand-registry";
import { BrandMark } from "../report-entities";
import { Avatar } from "../ui/kit";
import { CHANNEL_LABEL, type ChatChannel } from "./chats-client";
import styles from "./chats.module.css";

// The apps' own marks, from the brand library the Lead sources use too.
const MARKS: Record<ChatChannel, Brand | undefined> = {
  whatsapp: BRANDS.find((brand) => brand.key === "whatsapp"),
  messenger: BRANDS.find((brand) => brand.key === "messenger"),
  instagram: BRANDS.find((brand) => brand.key === "instagram"),
};

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
  const brand = MARKS[channel];
  return (
    <span
      className={styles.channelMark}
      data-channel={channel}
      style={{ "--mark": `${size}px` } as CSSProperties}
      role={labelled ? "img" : undefined}
      aria-label={labelled ? CHANNEL_LABEL[channel] : undefined}
      aria-hidden={labelled ? undefined : "true"}
    >
      {brand ? (
        <BrandMark brand={brand} size={Math.round(size * 0.78)} />
      ) : null}
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
