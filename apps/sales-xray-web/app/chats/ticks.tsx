import { Check, CheckCheck, CircleAlert, Clock } from "lucide-react";

import styles from "./chats.module.css";

const WORDS: Record<string, string> = {
  queued: "Sending",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Not sent",
};

/** Sent, delivered and read, the way people know them from WhatsApp. */
export function Ticks({
  status,
  size = 15,
}: {
  status: string;
  size?: number;
}) {
  const Icon =
    status === "queued"
      ? Clock
      : status === "failed"
        ? CircleAlert
        : status === "delivered" || status === "read"
          ? CheckCheck
          : Check;
  return (
    <span
      className={styles.ticks}
      data-status={status}
      role="img"
      aria-label={WORDS[status] ?? status}
      title={WORDS[status] ?? status}
    >
      <Icon size={size} strokeWidth={2.25} aria-hidden="true" />
    </span>
  );
}
