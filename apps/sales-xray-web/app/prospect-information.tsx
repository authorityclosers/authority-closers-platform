"use client";

import Link from "next/link";
import { useState } from "react";
import { formatClock } from "./lightbox/time";
import type { ProspectCall, ProspectSummary } from "./prospects-client";
import { confirmDetectedProspect, editProspectField } from "./prospects-client";
import { dismissNotice, notify } from "./notice-center";
import {
  PROSPECT_FIELD_LABELS,
  profileValueText,
  type FactLabel,
  type ProfileField,
  type ProfileKey,
} from "./prospect-profile-contract";
import styles from "./prospect-information.module.css";

export const PROSPECT_SECTIONS = [
  [
    "What You Need to Know Now",
    "The most important information before the next call.",
  ],
  [
    "What They Want — & Why",
    "Problems, impact, goals and what matters to them.",
  ],
  ["Can & Will They Buy?", "Qualification without guessing."],
  ["How They'll Decide", "People, approvals and decision process."],
  ["What's Holding Them Back", "Blockers, concerns and certainty."],
  ["What Happens Next", "Commitments, next action and next event."],
] as const;

function Field({
  label,
  field,
  text,
  state = "Unknown",
}: {
  label: string;
  field?: ProfileField;
  text?: string | null;
  state?: FactLabel;
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
      <dd>{known ? profileValueText(known.value) : text || "Unknown"}</dd>
      {known?.locked && (
        <small className={styles.lock}>Person edit · locked</small>
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

/** Six buyer-focused sections. No opportunity/qualification state is inferred. */
export function ProspectInformation({
  prospect,
  calls = [],
  onSaved,
}: {
  prospect: ProspectSummary;
  calls?: ProspectCall[];
  onSaved?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editKey, setEditKey] = useState<ProfileKey>("name");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const fields = prospect.profile_fields ?? {};
  const field = (
    key: ProfileKey,
    label: string = PROSPECT_FIELD_LABELS[key],
  ) => <Field key={key} label={label} field={fields[key]} />;
  const unknowns = (labels: string[]) =>
    labels.map((label) => <Field key={label} label={label} />);
  const content = [
    <dl key="now" className={styles.facts}>
      <Field
        label="Name"
        field={fields.name}
        text={prospect.profile_fields ? null : prospect.name}
        state="Observed"
      />
      {field("role")}
      {field("business")}
      {field("main_pain")}
      {unknowns(["Main goal", "Current blocker"])}
      {field("decision_maker")}
      <Field label="Deal stage" text={prospect.stage} state="Observed" />
      {field("next_step")}
      {unknowns([
        "Follow-up date and time",
        "Who acts next",
        "Biggest unanswered question",
        "Fit",
        "Urgency",
      ])}
    </dl>,
    <dl key="want" className={styles.facts}>
      {field("industry")}
      {field("city")}
      {field("team_size")}
      {field("turnover")}
      {field("main_pain")}
      {field("timeline")}
      {unknowns([
        "Current process",
        "Secondary problems",
        "Impact",
        "Desired outcome",
        "Why it matters",
      ])}
    </dl>,
    <div key="buy">
      <p className={styles.note}>
        A discussed amount does not confirm ability or willingness to invest.
      </p>
      <dl className={styles.facts}>
        {field("budget")}
        {unknowns([
          "Need",
          "Desire",
          "Ability to invest",
          "Willingness to invest",
          "Authority",
          "Urgency",
          "Timing",
          "Fit",
          "Implementation readiness",
        ])}
      </dl>
    </div>,
    <dl key="decide" className={styles.facts}>
      {field("decision_maker")}
      {unknowns([
        "Other stakeholders",
        "Stakeholder roles",
        "Approval process",
        "Decision process",
        "Decision criteria",
        "Important decision event",
      ])}
    </dl>,
    <div key="blockers">
      <dl className={styles.facts}>
        {unknowns([
          "Current blocker",
          "Objections and resolution",
          "Trust in seller",
          "Solution certainty",
          "Self certainty",
          "Outcome certainty",
          "Decision certainty",
          "Previous attempts",
          "Alternatives",
        ])}
      </dl>
      {calls
        .flatMap((call) =>
          (call.snapshot?.interpretations ?? []).map((interpretation, i) => (
            <div
              key={`${call.submission_id}-${i}`}
              className={styles.inference}
              data-fact-label="Inferred"
            >
              <small>Inferred · needs confirmation</small>
              <p>{interpretation.possible_concern}</p>
              <details className={styles.evidence}>
                <summary>What was said</summary>
                {interpretation.source.evidence.map((source, j) => (
                  <blockquote key={j}>
                    {source.quote}
                    <br />
                    <Link href={call.call_url}>
                      Source call · {formatClock(source.start_ms)}
                    </Link>
                  </blockquote>
                ))}
              </details>
            </div>
          )),
        )
        .slice(0, 3)}
    </div>,
    <dl key="next" className={styles.facts}>
      {field("next_step", "Next action")}
      <Field
        label="Recorded commitment"
        text={prospect.last_promise}
        state="Observed"
      />
      {unknowns([
        "Current blocker",
        "Next event",
        "Date and time",
        "Owner",
        "Prospect commitment",
        "Seller commitment",
        "Status",
        "What still needs clarity",
        "Recommended deal action",
      ])}
    </dl>,
  ];
  return (
    <div className={styles.information} aria-label="Prospect's Information">
      {prospect.origin === "detected" &&
        !prospect.confirmed_at &&
        prospect.can_confirm !== false &&
        onSaved && (
          <div className={styles.edit}>
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
      {prospect.profile_fields && prospect.can_edit !== false && onSaved && (
        <div className={styles.edit}>
          {!editing ? (
            <button type="button" onClick={() => setEditing(true)}>
              Edit a field
            </button>
          ) : (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                if (saving) return;
                setSaving(true);
                try {
                  await editProspectField(
                    prospect.prospect_id,
                    prospect.revision,
                    editKey,
                    draft,
                  );
                  dismissNotice("prospect-field-edit");
                  setEditing(false);
                  setDraft("");
                  onSaved();
                } catch (error) {
                  notify({
                    id: "prospect-field-edit",
                    tone: "error",
                    title: "Edit wasn't saved",
                    message:
                      error instanceof Error ? error.message : "Try again.",
                    action: {
                      label: "Try again",
                      run: () => {
                        onSaved();
                        setEditing(true);
                      },
                    },
                  });
                } finally {
                  setSaving(false);
                }
              }}
            >
              <label>
                Field
                <select
                  value={editKey}
                  disabled={saving}
                  onChange={(event) => {
                    setEditKey(event.target.value as ProfileKey);
                    setDraft("");
                  }}
                >
                  {Object.entries(PROSPECT_FIELD_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Your value
                <input
                  value={draft}
                  disabled={saving}
                  required
                  maxLength={
                    editKey === "name" || editKey === "phone"
                      ? 160
                      : editKey === "email"
                        ? 320
                        : 2048
                  }
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
              <p className={styles.note}>
                Your edit stays locked. Phone and email are entered by people
                only.
              </p>
              <div className={styles.actions}>
                <button type="submit" disabled={saving || !draft.trim()}>
                  {saving ? "Saving…" : "Save and lock"}
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => setEditing(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}
      {PROSPECT_SECTIONS.map(([title, subtitle], i) =>
        i === 0 ? (
          <section
            key={title}
            className={styles.section}
            data-prospect-section={i + 1}
          >
            <h2>{title}</h2>
            <p className={styles.note}>{subtitle}</p>
            {content[i]}
          </section>
        ) : (
          <details
            key={title}
            className={styles.section}
            data-prospect-section={i + 1}
          >
            <summary>
              <span>
                {i + 1}. {title}
              </span>
              <small>{subtitle}</small>
            </summary>
            {content[i]}
          </details>
        ),
      )}
      <details className={styles.section}>
        <summary>Contact details & tags</summary>
        <p className={styles.note}>
          Phone and email are entered by people only.
        </p>
        <dl className={styles.facts}>
          {field("phone")}
          {field("email")}
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
