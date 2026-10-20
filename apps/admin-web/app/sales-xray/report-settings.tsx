"use client";

/**
 * Report settings: create a version (previewed on a fictional call), publish
 * it to everyone or choose it for an organisation or an industry, roll back.
 * Every click is one idempotent command; the server keeps every version and
 * every choice (append-only history). Nothing re-analyses a call.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { command, keyFor, type Intent } from "../lib/client-api";
import { Badge, Button } from "../ui/kit";
import { ReportPreview } from "./report-preview";
import {
  SURFACE_LABEL,
  valueAt,
  withValue,
  type HistoryRow,
  type IndustryProfile,
  type Parameter,
  type Version,
} from "./report-settings-data";
import styles from "./report-settings.module.css";

const CHOICES = "/v1/admin/conversation/report-settings/choices";
const VERSIONS = "/v1/admin/conversation/report-settings/versions";

function useCommand(path: string) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [intent, setIntent] = useState<Intent | null>(null);
  async function send(body: unknown): Promise<boolean> {
    const next = keyFor(intent, body);
    setIntent(next);
    setBusy(true);
    setError(null);
    const result = await command(path, body, next.key);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    setIntent(null);
    router.refresh();
    return true;
  }
  return { busy, error, send };
}

/** Pick the version a scope uses; "" means inherit again (or version 1 for everyone). */
export function ChooseVersion({
  scope,
  tenantId = null,
  industryCode = null,
  current,
  inherited = 1,
  versions,
  label,
}: {
  scope: "organisation" | "industry" | "general";
  tenantId?: string | null;
  industryCode?: string | null;
  current: number | null;
  /** What "" resolves to here: the industry or general default, else version 1. */
  inherited?: number;
  versions: Version[];
  label: string;
}) {
  const [value, setValue] = useState(current === null ? "" : String(current));
  const [reason, setReason] = useState("");
  const { busy, error, send } = useCommand(CHOICES);
  const changed = value !== (current === null ? "" : String(current));
  // A one-option menu reads as broken: with nothing else saved, say so instead.
  if (!versions.length && current === null)
    return (
      <span className={styles.sub}>
        Version 1 (built in) · save a new version to choose another
      </span>
    );
  return (
    <div className={styles.choose}>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={busy}
      >
        <option value="">
          {scope === "general"
            ? "Version 1 (built in)"
            : `Default (Version ${inherited})`}
        </option>
        {versions.map((version) => (
          <option key={version.number} value={String(version.number)}>
            {version.number} · {version.label}
          </option>
        ))}
      </select>
      {changed ? (
        <>
          <input
            aria-label={`Why, for ${label}`}
            placeholder="Why (optional)"
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
          />
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void send({
                scope,
                tenant_id: tenantId,
                industry_code: industryCode,
                version_number: value === "" ? null : Number(value),
                expected_version_number: current,
                reason: reason.trim() || null,
              })
            }
          >
            {busy ? "Saving…" : "Use it"}
          </Button>
        </>
      ) : null}
      {error ? (
        <small className={styles.error} role="alert">
          {error}
        </small>
      ) : null}
    </div>
  );
}

/** Add or change an industry's default version (industries are the lead-stage profiles). */
export function IndustryDefault({
  versions,
  profiles,
}: {
  versions: Version[];
  profiles: IndustryProfile[];
}) {
  const [code, setCode] = useState("");
  const [version, setVersion] = useState(String(versions.at(-1)?.number ?? 1));
  const { busy, error, send } = useCommand(CHOICES);
  return (
    <div className={styles.choose}>
      <select
        aria-label="Industry"
        value={code}
        onChange={(event) => setCode(event.target.value)}
      >
        <option value="">Choose an industry</option>
        {profiles.map((profile) => (
          <option key={profile.id} value={profile.id}>
            {profile.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Version for this industry"
        value={version}
        onChange={(event) => setVersion(event.target.value)}
      >
        {versions.map((item) => (
          <option key={item.number} value={String(item.number)}>
            {item.number} · {item.label}
          </option>
        ))}
      </select>
      <Button
        disabled={busy || !code}
        onClick={() =>
          void send({
            scope: "industry",
            industry_code: code.trim(),
            version_number: Number(version),
            expected_version_number: null,
          })
        }
      >
        Set industry default
      </Button>
      {error ? (
        <small className={styles.error} role="alert">
          {error}
        </small>
      ) : null}
    </div>
  );
}

/** Undo the newest choice for one scope: choose what it had before. */
export function RollBack({ row }: { row: HistoryRow }) {
  const { busy, error, send } = useCommand(CHOICES);
  return (
    <span className={styles.rollback}>
      <Button
        variant="ghost"
        disabled={busy}
        onClick={() =>
          void send({
            scope: row.scope,
            tenant_id: row.tenantId,
            industry_code: row.industryCode,
            version_number: row.previousVersionNumber,
            expected_version_number: row.versionNumber,
            reason: `Rolled back the choice of ${new Date(row.createdAt).toLocaleString("en-IN")}`,
          })
        }
      >
        Roll back
      </Button>
      {error ? (
        <small className={styles.error} role="alert">
          {error}
        </small>
      ) : null}
    </span>
  );
}

function Field({
  parameter,
  value,
  onChange,
}: {
  parameter: Parameter;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const note = parameter.inApp
    ? "In the app now"
    : parameter.applies === "generation"
      ? "AI wording, later"
      : "Saved; each tab adopts it";
  const head = (
    <span className={styles.fieldHead}>
      <strong>{parameter.label}</strong>
      <Badge tone={parameter.inApp ? "good" : "neutral"}>{note}</Badge>
    </span>
  );
  if (parameter.kind === "toggle")
    return (
      <label className={styles.field} title={parameter.help}>
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => onChange(event.target.checked)}
        />
        {head}
      </label>
    );
  if (parameter.kind === "choice")
    return (
      <div className={styles.field} title={parameter.help}>
        {head}
        <span
          className={styles.segments}
          role="radiogroup"
          aria-label={parameter.label}
        >
          {parameter.choices.map((choice) => (
            <button
              key={choice.value}
              type="button"
              role="radio"
              aria-checked={value === choice.value}
              className={styles.segment}
              onClick={() => onChange(choice.value)}
            >
              {choice.label}
            </button>
          ))}
        </span>
      </div>
    );
  if (parameter.kind === "number")
    return (
      <label className={styles.field} title={parameter.help}>
        {head}
        <input
          type="number"
          min={parameter.minimum ?? undefined}
          max={parameter.maximum ?? undefined}
          value={typeof value === "number" ? value : ""}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </label>
    );
  return null;
}

function Pointers({
  all,
  value,
  onChange,
}: {
  all: string[];
  value: unknown;
  onChange: (value: string[]) => void;
}) {
  const shown = new Set(Array.isArray(value) ? (value as string[]) : all);
  return (
    <fieldset className={styles.pointers}>
      <legend>
        Pointers shown{" "}
        <small>
          {shown.size} of {all.length}
        </small>
      </legend>
      {all.map((id) => (
        <label key={id}>
          <input
            type="checkbox"
            checked={shown.has(id)}
            onChange={(event) => {
              const next = all.filter((item) =>
                item === id ? event.target.checked : shown.has(item),
              );
              if (next.length) onChange(next);
            }}
          />
          {id.replace(/_/g, " ")}
        </label>
      ))}
    </fieldset>
  );
}

/**
 * A new version, started from an existing one; only what you change differs.
 * The preview shows it on a fictional call as you change it. Save keeps it for
 * later; Save and publish also makes it everyone's default in one go (an
 * organisation's or industry's own choice still wins). Rolling back is in the
 * history.
 */
export function VersionEditor({
  parameters,
  versions,
  profiles = [],
  generalVersionNumber = null,
}: {
  parameters: Parameter[];
  versions: Version[];
  profiles?: IndustryProfile[];
  /** Everyone's default now, as this screen saw it (null: version 1). */
  generalVersionNumber?: number | null;
}) {
  const router = useRouter();
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishIntent, setPublishIntent] = useState<Intent | null>(null);
  const newest = versions.at(-1);
  const [base, setBase] = useState(newest?.number ?? 1);
  const start = versions.find((item) => item.number === base)?.settings ?? {};
  const [settings, setSettings] = useState<Record<string, unknown>>(start);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [industry, setIndustry] = useState("");
  const [open, setOpen] = useState(false);
  const { busy, error, send } = useCommand(VERSIONS);
  const body = () => ({
    label: label.trim(),
    note: note.trim() || null,
    base_number: base,
    industry_code: industry || null,
    settings,
  });
  async function publish() {
    const request = body();
    const intent = keyFor(publishIntent, request);
    setPublishIntent(intent);
    setPublishing(true);
    setPublishError(null);
    const made = await command<Record<string, unknown>>(
      VERSIONS,
      request,
      intent.key,
    );
    if (!made.ok) {
      setPublishing(false);
      setPublishError(made.message);
      return;
    }
    const number =
      typeof made.data.number === "number" ? made.data.number : null;
    const choice = {
      scope: "general",
      version_number: number,
      expected_version_number: generalVersionNumber,
      reason: `Published version ${number ?? "?"}`,
    };
    const chosen =
      number === null
        ? null
        : await command(CHOICES, choice, keyFor(null, choice).key);
    setPublishing(false);
    router.refresh();
    if (!chosen || !chosen.ok) {
      setPublishError(
        `Version ${number ?? "?"} is saved but not published: ${
          chosen && !chosen.ok ? chosen.message : "its number was not returned"
        }. Choose it under Defaults.`,
      );
      return;
    }
    setPublishIntent(null);
    setOpen(false);
  }
  const allPointers = Array.isArray(
    valueAt(versions[0]?.settings ?? {}, "report.pointers"),
  )
    ? (valueAt(versions[0]?.settings ?? {}, "report.pointers") as string[])
    : [];
  if (!open)
    return (
      <Button variant="primary" onClick={() => setOpen(true)}>
        New version
      </Button>
    );
  return (
    <form
      className={styles.editor}
      onSubmit={(event) => {
        event.preventDefault();
        void send(body()).then((saved) => {
          if (saved) setOpen(false);
        });
      }}
    >
      <div className={styles.editorHead}>
        <label>
          Start from{" "}
          <select
            value={base}
            onChange={(event) => {
              const number = Number(event.target.value);
              setBase(number);
              setSettings(
                versions.find((item) => item.number === number)?.settings ?? {},
              );
            }}
          >
            {versions.map((version) => (
              <option key={version.number} value={version.number}>
                {version.number} · {version.label}
              </option>
            ))}
          </select>
        </label>
        <input
          aria-label="Version name"
          placeholder="Name, e.g. Compact for real estate"
          required
          minLength={2}
          maxLength={80}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <select
          aria-label="Built for industry (optional)"
          value={industry}
          onChange={(event) => setIndustry(event.target.value)}
        >
          <option value="">Any industry</option>
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>
          ))}
        </select>
        <input
          aria-label="Why this version"
          placeholder="Why (optional)"
          maxLength={500}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      <div className={styles.editorBody}>
        <div className={styles.editorFields}>
          {["report", "prospect", "coaching"].map((surface) => (
            <fieldset key={surface} className={styles.surface}>
              <legend>{SURFACE_LABEL[surface]}</legend>
              {parameters
                .filter((parameter) => parameter.surface === surface)
                .map((parameter) =>
                  parameter.kind === "pointers" ? (
                    <Pointers
                      key={parameter.key}
                      all={allPointers}
                      value={valueAt(settings, parameter.key)}
                      onChange={(value) =>
                        setSettings(withValue(settings, parameter.key, value))
                      }
                    />
                  ) : (
                    <Field
                      key={parameter.key}
                      parameter={parameter}
                      value={valueAt(settings, parameter.key)}
                      onChange={(value) =>
                        setSettings(withValue(settings, parameter.key, value))
                      }
                    />
                  ),
                )}
            </fieldset>
          ))}
        </div>
        <ReportPreview
          settings={settings}
          baseline={versions[0]?.settings ?? {}}
          parameters={parameters}
        />
      </div>
      <div className={styles.editorFoot}>
        {error || publishError ? (
          <small className={styles.error} role="alert">
            {error ?? publishError}
          </small>
        ) : (
          <small>
            Version 1 stays as it is. Saving makes a new numbered version;
            people see it only once it is published or chosen for them.
          </small>
        )}
        <Button
          variant="ghost"
          onClick={() => setOpen(false)}
          disabled={busy || publishing}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={busy || publishing}>
          {busy ? "Saving…" : "Save version"}
        </Button>
        <Button
          variant="primary"
          disabled={busy || publishing || label.trim().length < 2}
          onClick={() => void publish()}
        >
          {publishing ? "Publishing…" : "Save and publish to everyone"}
        </Button>
      </div>
    </form>
  );
}
