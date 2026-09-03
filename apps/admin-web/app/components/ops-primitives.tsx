import type { ReactNode } from "react";
import { Database, FileCheck2, History, LockKeyhole } from "lucide-react";

export function PreviewNotice({
  body = "No learner, catalog, job, or audit record is seeded here. A trusted server adapter must provide tenant-scoped state before this surface can read or write.",
  title = "This preview asserts no operational data.",
}: {
  body?: string;
  title?: string;
}) {
  return (
    <div className="preview-notice" role="note">
      <div className="notice-icon" aria-hidden="true">
        <LockKeyhole size={22} strokeWidth={1.7} />
      </div>
      <div>
        <span className="notice-kicker">Preview / structurally inert</span>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
      <span className="notice-code">NO SIDE EFFECTS</span>
    </div>
  );
}

export function SectionHeading({
  action,
  body,
  eyebrow,
  id,
  title,
}: {
  action?: ReactNode;
  body: string;
  eyebrow: string;
  id?: string;
  title: string;
}) {
  return (
    <div className="section-heading">
      <div>
        <span className="section-eyebrow">{eyebrow}</span>
        <h2 id={id}>{title}</h2>
        <p>{body}</p>
      </div>
      {action}
    </div>
  );
}

export function SourceBoundary({
  body,
  id,
  source = "tenant-scoped authorized API",
  title,
}: {
  body: string;
  id: string;
  source?: string;
  title: string;
}) {
  return (
    <section className="source-boundary" aria-labelledby={`${id}-title`}>
      <div className="empty-ornament" aria-hidden="true">
        <Database size={24} strokeWidth={1.5} />
      </div>
      <div>
        <span className="state-label">SOURCE / NOT CONNECTED</span>
        <h2 id={`${id}-title`}>{title}</h2>
        <p>{body}</p>
        <dl className="mini-definition">
          <div>
            <dt>Expected source</dt>
            <dd>{source}</dd>
          </div>
          <div>
            <dt>Record state</dt>
            <dd>Unknown — no response or record is asserted</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

export function CapabilityBoundary({
  actionLabel,
  audit,
  detail,
  permission,
  reason,
  title,
}: {
  actionLabel: string;
  audit: string;
  detail: string;
  permission: string;
  reason: string;
  title: string;
}) {
  const headingId = `capability-${permission.replaceAll("_", "-")}`;

  return (
    <section className="capability-boundary" aria-labelledby={headingId}>
      <div className="boundary-topline">
        <span className="section-eyebrow">Permission boundary</span>
        <span className="locked-pill">
          <LockKeyhole size={13} aria-hidden="true" /> LOCKED
        </span>
      </div>
      <h2 id={headingId}>{title}</h2>
      <p className="boundary-detail">{detail}</p>
      <dl className="capability-facts">
        <div>
          <dt>Required permission</dt>
          <dd>
            <code>{permission}</code>
          </dd>
        </div>
        <div>
          <dt>Why locked</dt>
          <dd>{reason}</dd>
        </div>
        <div>
          <dt>Audit behavior</dt>
          <dd>{audit}</dd>
        </div>
      </dl>
      <button className="button button-locked" type="button" disabled>
        <LockKeyhole size={15} aria-hidden="true" />
        {actionLabel}
      </button>
    </section>
  );
}

export function AuditPanel({
  body,
  id,
  title,
  fields = [
    "Named actor and tenant context",
    "Purpose, reason, and provenance",
    "Append-only event or supersession link",
    "Idempotency and request trace",
  ],
}: {
  body: string;
  fields?: string[];
  id: string;
  title: string;
}) {
  return (
    <section className="audit-panel" aria-labelledby={`${id}-title`}>
      <div className="audit-topline">
        <span className="section-eyebrow">
          <History size={14} aria-hidden="true" /> Audit / append-only
        </span>
        <span className="audit-status">NOT WRITTEN</span>
      </div>
      <h2 id={`${id}-title`}>{title}</h2>
      <p>{body}</p>
      <div className="audit-fields">
        <span className="field-label">Required evidence fields</span>
        <ul>
          {fields.map((field) => (
            <li key={field}>
              <FileCheck2 size={14} aria-hidden="true" />
              {field}
            </li>
          ))}
        </ul>
      </div>
      <code className="audit-code">
        audit event: none · trace: none · chain: untouched
      </code>
    </section>
  );
}

export const LEARNING_PRIMITIVES = [
  { index: "01", label: "WATCH", detail: "Evidence-backed viewing" },
  { index: "02", label: "REFLECT", detail: "Human-readable response" },
  { index: "03", label: "IMPLEMENT", detail: "Action in the real world" },
  { index: "04", label: "REVIEW", detail: "Assigned review boundary" },
  { index: "05", label: "IMPROVE", detail: "Deterministic next attempt" },
] as const;

export function PrimitiveSequence() {
  return (
    <ol
      className="primitive-sequence"
      aria-label="Permanent learning activity sequence"
    >
      {LEARNING_PRIMITIVES.map((primitive) => (
        <li key={primitive.label}>
          <span>{primitive.index}</span>
          <strong>{primitive.label}</strong>
          <small>{primitive.detail}</small>
        </li>
      ))}
    </ol>
  );
}
