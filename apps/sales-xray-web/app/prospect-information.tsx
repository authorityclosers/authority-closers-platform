"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { InlineEdit } from "./ui/kit";
import { formatClock } from "./lightbox/time";
import type { ProspectCall, ProspectSummary } from "./prospects-client";
import { confirmDetectedProspect, editProspectField } from "./prospects-client";
import { dismissNotice, notify } from "./notice-center";
import type { Transcript } from "./report-contract";
import { useReportPeople } from "./report-kit";
import {
  profileValueText,
  type FactLabel,
  type ProfileField,
  type ProfileKey,
} from "./prospect-profile-contract";
import {
  BRIEF_SECTIONS,
  prospectBrief,
  type BriefFact,
  type BriefSection,
  type BriefSource,
  type LatestCall,
} from "./prospect-brief-model";
import styles from "./prospect-information.module.css";

export const PROSPECT_SECTIONS = BRIEF_SECTIONS.map(
  ({ title, subtitle }) => [title, subtitle] as const,
);

function Field({
  label,
  field,
  text,
  state = "Unknown",
  onSave,
  disabled,
}: {
  label: string;
  field?: ProfileField;
  text?: string | null;
  state?: FactLabel;
  onSave?: (value: string) => Promise<void>;
  disabled?: boolean;
}) {
  const known = field?.state === "known" ? field : null;
  const factLabel = known
    ? known.heard_differently?.length
      ? "Contradiction"
      : known.changed_from
        ? "Changed"
        : "Observed"
    : text
      ? state
      : "Unknown";
  return (
    <div className={styles.fact} data-fact-label={factLabel}>
      <dt>
        {label}
        <small>{factLabel}</small>
      </dt>
      <dd>
        {onSave ? (
          <InlineEdit
            label={label}
            value={known ? profileValueText(known.value) : text || ""}
            placeholder="Unknown · add"
            disabled={disabled}
            onSave={onSave}
          />
        ) : known ? (
          profileValueText(known.value)
        ) : (
          text || "Unknown"
        )}
      </dd>
      {field?.locked && (
        <small className={styles.lock}>
          <LockKeyhole size={12} aria-hidden="true" /> Person edit · locked
        </small>
      )}
      {known?.evidence && (
        <details className={styles.evidence}>
          <summary>Source · {formatClock(known.evidence.start_ms)}</summary>
          <blockquote>{known.evidence.quote}</blockquote>
          <Link
            href={`/analysis/calls/${known.evidence.submission_id}?section=transcript`}
          >
            Open source call · {formatClock(known.evidence.start_ms)}–
            {formatClock(known.evidence.end_ms)}
          </Link>
        </details>
      )}
      {known?.changed_from && (
        <details className={styles.evidence}>
          <summary>Previously recorded</summary>
          <p>{profileValueText(known.changed_from.value)}</p>
          <blockquote>{known.changed_from.evidence.quote}</blockquote>
          <Link
            href={`/analysis/calls/${known.changed_from.evidence.submission_id}?section=transcript`}
          >
            Earlier source · {formatClock(known.changed_from.evidence.start_ms)}
          </Link>
        </details>
      )}
      {known?.heard_differently?.length ? (
        <details className={styles.evidence}>
          <summary>A later call differs · your edit still wins</summary>
          {known.heard_differently.map((heard, i) => (
            <div key={i}>
              <p>{profileValueText(heard.value)}</p>
              <blockquote>{heard.evidence.quote}</blockquote>
              <Link
                href={`/analysis/calls/${heard.evidence.submission_id}?section=transcript`}
              >
                Source · {formatClock(heard.evidence.start_ms)}
              </Link>
            </div>
          ))}
        </details>
      ) : null}
    </div>
  );
}

/** Shared presentation only; callers supply authorised, entity-specific facts. */
export { Field as ProfileFact };

type BriefState = "none" | "loading" | "ready" | "unavailable";

const NO_TRANSCRIPT = {
  revision: "",
  timebase_id: "",
  duration_ms: 0,
  segments: [],
} as unknown as Transcript;

function SourceLink({ source }: { source?: BriefSource }) {
  if (!source) return null;
  const at = formatClock(source.start_ms);
  return source.callId ? (
    <Link
      className={styles.briefSource}
      href={`/analysis/calls/${source.callId}?section=transcript`}
      title={`“${source.quote}”`}
    >
      Heard · {at}
    </Link>
  ) : (
    <span className={styles.briefSource} title={`“${source.quote}”`}>
      Heard · {at}
    </span>
  );
}

function BriefFactRow({
  fact,
  canEdit,
  saving,
  save,
}: {
  fact: BriefFact;
  canEdit: boolean;
  saving: boolean;
  save: (key: ProfileKey, value: string) => Promise<void>;
}) {
  const editable = canEdit && fact.editKey;
  return (
    <div className={styles.briefFact} data-fact-label={fact.fact}>
      <dt>
        <span>{fact.label}</span>
        <small className={styles.factChip} data-fact={fact.fact}>
          {fact.fact}
        </small>
        {fact.basis === "person" ? (
          <small className={styles.lock} title="Set by a person; it wins">
            <LockKeyhole size={12} aria-hidden="true" />
            <span className={styles.srOnly}>Set by a person</span>
          </small>
        ) : null}
      </dt>
      <dd>
        {fact.list ? (
          <ul className={styles.briefList}>
            {fact.list.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : editable ? (
          <InlineEdit
            label={fact.label}
            value={fact.value}
            disabled={saving}
            onSave={(value) => save(fact.editKey!, value)}
          />
        ) : (
          fact.value
        )}
        <SourceLink source={fact.source} />
        {fact.earlier ? (
          <span className={styles.briefNote}>
            Earlier: {fact.earlier.value}
          </span>
        ) : null}
        {fact.differs?.map((item, index) => (
          <span key={index} className={styles.briefNote}>
            A later call heard: {item.value} · your edit still wins
          </span>
        ))}
      </dd>
    </div>
  );
}

function BriefUnknown({
  items,
  canEdit,
  saving,
  save,
}: {
  items: BriefSection["unknown"];
  canEdit: boolean;
  saving: boolean;
  save: (key: ProfileKey, value: string) => Promise<void>;
}) {
  if (!items.length) return null;
  const plain = items.filter((item) => !(canEdit && item.editKey));
  const addable = items.filter((item) => canEdit && item.editKey);
  return (
    <div className={styles.briefUnknown}>
      <span className={styles.factChip} data-fact="Unknown">
        Unknown
      </span>
      {plain.map((item, index) => (
        <span key={item.label} data-unknown-locked={item.locked || undefined}>
          {index > 0 ? "· " : ""}
          {item.locked ? (
            <LockKeyhole
              size={12}
              aria-label="Set to Unknown by a person"
              role="img"
            />
          ) : null}
          {item.label}
        </span>
      ))}
      {addable.map((item) => (
        <span
          key={item.label}
          className={styles.briefAdd}
          data-unknown-locked={item.locked || undefined}
        >
          {item.locked ? (
            <LockKeyhole
              size={12}
              aria-label="Set to Unknown by a person"
              role="img"
            />
          ) : null}
          <InlineEdit
            label={item.label}
            value=""
            placeholder={`+ ${item.label}`}
            disabled={saving}
            onSave={(value) => save(item.editKey!, value)}
          />
        </span>
      ))}
    </div>
  );
}

/** Six buyer-focused sections. No opportunity/qualification state is inferred. */
export function ProspectInformation({
  prospect,
  calls = [],
  onSaved,
  latest,
  latestState = latest ? "ready" : "none",
}: {
  prospect: ProspectSummary;
  calls?: ProspectCall[];
  onSaved?: () => void;
  /** The latest analysed call's Report, when it could be read. */
  latest?: LatestCall;
  latestState?: BriefState;
}) {
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const canEdit =
    !!prospect.profile_fields && prospect.can_edit !== false && !!onSaved;
  // Own words need confirmed speaker roles; never guessed from text.
  const people = useReportPeople(
    latest?.callId ?? null,
    latest?.transcript ?? NO_TRANSCRIPT,
  );
  const seller = people.roles?.seller ?? null;
  const prospectVoice = people.roles?.prospect ?? null;
  const brief = useMemo(() => {
    try {
      return prospectBrief(
        prospect,
        calls,
        latest
          ? { ...latest, roles: { seller, prospect: prospectVoice } }
          : undefined,
      );
    } catch {
      // An unreadable call report never hides the saved facts.
      return prospectBrief(prospect, calls);
    }
  }, [prospect, calls, latest, seller, prospectVoice]);
  async function save(key: ProfileKey, value: string) {
    if (pending.current)
      throw new Error("Another field is being saved. Try again.");
    pending.current = true;
    setSaving(true);
    try {
      await editProspectField(
        prospect.prospect_id,
        prospect.revision,
        key,
        value,
      );
      dismissNotice("prospect-field-edit");
      onSaved?.();
    } catch (error) {
      notify({
        id: "prospect-field-edit",
        tone: "error",
        title: "Edit wasn't saved",
        message: error instanceof Error ? error.message : "Try again.",
        action: { label: "Try again", run: () => onSaved?.() },
      });
      throw error;
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  const fields = prospect.profile_fields ?? {};
  return (
    <div className={styles.information} aria-label="Prospect's Information">
      {prospect.origin === "detected" &&
        !prospect.confirmed_at &&
        prospect.can_confirm !== false &&
        onSaved && (
          <div className={styles.detected}>
            <span>Detected from a call · not yet confirmed</span>
            <button
              type="button"
              disabled={saving}
              onClick={async () => {
                if (saving) return;
                setSaving(true);
                try {
                  await confirmDetectedProspect(
                    prospect.prospect_id,
                    prospect.revision,
                  );
                  dismissNotice("prospect-confirmation");
                  onSaved();
                } catch (error) {
                  notify({
                    id: "prospect-confirmation",
                    tone: "error",
                    title: "Prospect wasn't confirmed",
                    message:
                      error instanceof Error ? error.message : "Try again.",
                    action: { label: "Try again", run: onSaved },
                  });
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? "Confirming…" : "Confirm prospect"}
            </button>
          </div>
        )}
      <p className={styles.briefBasis} data-brief-state={latestState}>
        {latestState === "ready" && brief.basedOn
          ? `Call facts from your latest analysed call: ${brief.basedOn.label}.`
          : latestState === "loading"
            ? "Reading the latest analysed call…"
            : latestState === "unavailable"
              ? "The latest call's report couldn't be read; only saved facts are shown."
              : "No analysed call yet; only saved facts are shown."}
      </p>
      {BRIEF_SECTIONS.map(({ title, subtitle }, index) => {
        const part = brief.sections[index];
        return (
          <section
            key={title}
            className={styles.briefSection}
            data-prospect-section={index + 1}
            data-brief-lead={index === 0 || undefined}
            aria-labelledby={`brief-${index + 1}`}
          >
            <header className={styles.briefHead}>
              <span className={styles.briefNumber} aria-hidden="true">
                {index + 1}
              </span>
              <div>
                <h2 id={`brief-${index + 1}`}>{title}</h2>
                <p>{subtitle}</p>
              </div>
            </header>
            {index === 2 && fields.budget?.state === "known" ? (
              <p className={styles.note}>
                A discussed amount does not confirm ability or willingness to
                invest.
              </p>
            ) : null}
            {part.facts.length ? (
              <dl className={styles.briefFacts}>
                {part.facts.map((fact, i) => (
                  <BriefFactRow
                    key={`${fact.label}-${i}`}
                    fact={fact}
                    canEdit={canEdit}
                    saving={saving}
                    save={save}
                  />
                ))}
              </dl>
            ) : null}
            {latestState === "loading" ? (
              <span className={styles.briefSkeleton} aria-hidden="true" />
            ) : null}
            <BriefUnknown
              items={part.unknown}
              canEdit={canEdit}
              saving={saving}
              save={save}
            />
          </section>
        );
      })}
      <details className={styles.briefMore}>
        <summary>Contact details &amp; tags</summary>
        <p className={styles.note}>
          Phone and email are entered by people only.
        </p>
        <dl className={styles.facts}>
          <Field
            label="Phone"
            field={fields.phone}
            disabled={saving}
            onSave={canEdit ? (value) => save("phone", value) : undefined}
          />
          <Field
            label="Email"
            field={fields.email}
            disabled={saving}
            onSave={canEdit ? (value) => save("email", value) : undefined}
          />
          <Field
            label="Tags"
            text={prospect.tags.length ? prospect.tags.join(", ") : null}
            state="Observed"
          />
        </dl>
      </details>
    </div>
  );
}
