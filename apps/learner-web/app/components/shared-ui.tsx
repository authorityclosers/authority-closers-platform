import {
  Check,
  Circle,
  Clock3,
  Eye,
  LockKeyhole,
  MessageCircleMore,
  PencilLine,
  Play,
  Sparkles,
} from "lucide-react";

import type { ActivityKind, ActivityStatus } from "../lib/view-models";

export function Kicker({ children }: { children: React.ReactNode }) {
  return <p className="kicker">{children}</p>;
}

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "acid" | "muted" | "warning";
}) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}

export function ActivityKindIcon({ kind }: { kind: ActivityKind }) {
  const Icon =
    kind === "VIDEO"
      ? Play
      : kind === "REFLECTION"
        ? PencilLine
        : kind === "IMPLEMENTATION_CHALLENGE"
          ? Sparkles
          : kind === "REVIEW"
            ? MessageCircleMore
            : Check;

  return <Icon size={18} aria-hidden="true" />;
}

export function ActivityStatusPill({ status }: { status: ActivityStatus }) {
  const config: Record<
    ActivityStatus,
    {
      label: string;
      tone: "neutral" | "acid" | "muted" | "warning";
      icon: React.ReactNode;
    }
  > = {
    LOCKED: {
      label: "Locked",
      tone: "muted",
      icon: <LockKeyhole size={13} aria-hidden="true" />,
    },
    PREVIEW: {
      label: "Preview only",
      tone: "neutral",
      icon: <Eye size={13} aria-hidden="true" />,
    },
    AVAILABLE: {
      label: "Ready",
      tone: "acid",
      icon: <Circle size={13} aria-hidden="true" />,
    },
    IN_PROGRESS: {
      label: "In progress",
      tone: "warning",
      icon: <Clock3 size={13} aria-hidden="true" />,
    },
    AWAITING_REVIEW: {
      label: "Awaiting review",
      tone: "warning",
      icon: <MessageCircleMore size={13} aria-hidden="true" />,
    },
    COMPLETED: {
      label: "Complete",
      tone: "acid",
      icon: <Check size={13} aria-hidden="true" />,
    },
  };
  const item = config[status];

  return (
    <StatusPill tone={item.tone}>
      {item.icon}
      <span>{item.label}</span>
    </StatusPill>
  );
}

export function ProgressMeter({
  value,
  label,
  detail,
}: {
  value: number;
  label: string;
  detail: string;
}) {
  const safeValue = Math.min(100, Math.max(0, value));

  return (
    <div className="progress-meter">
      <div className="progress-meter__labels">
        <span>{label}</span>
        <span>{detail}</span>
      </div>
      <div
        className="progress-meter__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={safeValue}
      >
        <span style={{ width: `${safeValue}%` }} />
      </div>
    </div>
  );
}

export function ArrowLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="arrow-label">
      {children} <span aria-hidden="true">↗</span>
    </span>
  );
}
