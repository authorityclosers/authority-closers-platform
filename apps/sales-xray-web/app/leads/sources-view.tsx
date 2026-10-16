"use client";

/**
 * Sources: where leads come from. One capture path for all of them; each lead
 * keeps exactly what its source sent. Meta lead forms need AC's Meta app first.
 */

import {
  Copy,
  FileSpreadsheet,
  FlaskConical,
  Globe,
  RefreshCw,
  Sheet as SheetIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Field, Panel, Skeleton } from "../ui/kit";
import {
  addSource,
  LeadsError,
  readSources,
  rotateSource,
  seedTestLeads,
  setSourceActive,
  syncSource,
  when,
  type Sources,
  type SourceView,
} from "./leads-client";
import styles from "./leads.module.css";

function CopyText({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className={styles.copy}>
      <code>{value}</code>
      <Button
        variant="icon"
        aria-label={`Copy ${label}`}
        onClick={() => {
          navigator.clipboard
            .writeText(value)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => undefined);
        }}
      >
        <Copy size={14} aria-hidden="true" />
      </Button>
      {copied ? <small role="status">Copied</small> : null}
    </span>
  );
}

function SourceRow({
  source,
  onChanged,
}: {
  source: SourceView;
  onChanged: (next: SourceView | null, note?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } catch (reason) {
      onChanged(
        null,
        reason instanceof LeadsError
          ? reason.message
          : "That didn't work. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className={styles.source}>
      <span className={styles.sourceIcon} aria-hidden="true">
        {source.kind === "sheet" ? (
          <SheetIcon size={16} />
        ) : (
          <Globe size={16} />
        )}
      </span>
      <span className={styles.sourceMain}>
        <strong>
          {source.label} {source.active ? null : <Badge>Paused</Badge>}
        </strong>
        <small>
          {source.kind === "sheet" ? "Google Sheet" : "Website form"} ·{" "}
          {source.received} received
          {source.last_received_at
            ? ` · last ${when(source.last_received_at)}`
            : ""}
        </small>
        {source.endpoint ? (
          <CopyText value={source.endpoint} label="address" />
        ) : null}
        {source.token ? (
          <span className={styles.secretOnce}>
            Key (shown once, keep it safe):{" "}
            <CopyText value={source.token} label="key" />
          </span>
        ) : null}
        {source.sheet_url ? (
          <small className={styles.ellipsis}>{source.sheet_url}</small>
        ) : null}
      </span>
      <span className={styles.sourceActions}>
        {source.kind === "sheet" && source.active ? (
          <Button
            disabled={busy}
            onClick={() =>
              act(async () => {
                const result = await syncSource(source.source_id);
                onChanged(
                  null,
                  `Synced: ${result.created} new, ${result.repeats} already leads.`,
                );
              })
            }
          >
            <RefreshCw size={14} aria-hidden="true" />
            Sync now
          </Button>
        ) : null}
        {source.kind === "webhook" ? (
          <Button
            disabled={busy}
            onClick={() =>
              act(async () => onChanged(await rotateSource(source.source_id)))
            }
          >
            New key
          </Button>
        ) : null}
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() =>
            act(async () =>
              onChanged(
                await setSourceActive(source.source_id, !source.active),
              ),
            )
          }
        >
          {source.active ? "Pause" : "Resume"}
        </Button>
      </span>
    </li>
  );
}

export function SourcesView({
  sandbox,
  onChanged,
  onImport,
}: {
  sandbox: boolean;
  onChanged: () => void;
  onImport: () => void;
}) {
  const [data, setData] = useState<Sources | null>(null);
  const [fresh, setFresh] = useState<Record<string, SourceView>>({});
  const [note, setNote] = useState<string | null>(null);
  const [kind, setKind] = useState<"webhook" | "sheet" | null>(null);
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    readSources()
      .then(setData)
      .catch((reason: unknown) =>
        setNote(
          reason instanceof LeadsError
            ? reason.message
            : "Sources didn't load.",
        ),
      );
  useEffect(() => {
    void load();
  }, []);

  const create = async () => {
    if (!kind || !label.trim()) {
      setNote("Give the source a name.");
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const made = await addSource({
        kind,
        label: label.trim(),
        sheet_url: kind === "sheet" ? url.trim() : undefined,
      });
      setFresh((current) => ({ ...current, [made.source_id]: made }));
      setKind(null);
      setLabel("");
      setUrl("");
      await load();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "Not added. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const seed = async () => {
    setBusy(true);
    setNote(null);
    try {
      const result = await seedTestLeads(25);
      setNote(
        `Added ${result.created} test leads: ${result.assigned} given an owner by the rules, ${result.waiting} waiting.`,
      );
      onChanged();
    } catch (reason) {
      setNote(
        reason instanceof LeadsError
          ? reason.message
          : "Test leads weren't added.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.sourcesGrid}>
      <Panel
        title="Connected sources"
        sub={data ? `${data.sources.length}` : undefined}
      >
        {data === null ? (
          <Skeleton height={120} />
        ) : data.sources.length ? (
          <ul className={styles.sourceList}>
            {data.sources.map((source) => (
              <SourceRow
                key={source.source_id}
                source={fresh[source.source_id] ?? source}
                onChanged={(next, message) => {
                  if (next)
                    setFresh((current) => ({
                      ...current,
                      [next.source_id]: next,
                    }));
                  if (message) setNote(message);
                  void load();
                  onChanged();
                }}
              />
            ))}
          </ul>
        ) : (
          <p className={`${styles.hint} ${styles.padded}`}>
            No sources yet. Add a website form or a Google Sheet below.
          </p>
        )}
        {note ? (
          <p className={`${styles.hint} ${styles.padded}`} role="status">
            {note}
          </p>
        ) : null}
      </Panel>

      <Panel title="Add a source">
        <div className={styles.sourceChoices}>
          <button
            type="button"
            className={styles.sourceChoice}
            aria-pressed={kind === "webhook"}
            onClick={() => setKind("webhook")}
          >
            <Globe size={18} aria-hidden="true" />
            <strong>Website form</strong>
            <small>
              Your site or another tool posts each enquiry. You get an address
              and a key.
            </small>
          </button>
          <button
            type="button"
            className={styles.sourceChoice}
            aria-pressed={kind === "sheet"}
            onClick={() => setKind("sheet")}
          >
            <SheetIcon size={18} aria-hidden="true" />
            <strong>Google Sheet</strong>
            <small>
              Share the sheet as "Anyone with the link can view", paste the
              link, then sync.
            </small>
          </button>
          <button
            type="button"
            className={styles.sourceChoice}
            onClick={onImport}
          >
            <FileSpreadsheet size={18} aria-hidden="true" />
            <strong>CSV or Excel file</strong>
            <small>Upload once, match the columns, done.</small>
          </button>
          <div className={styles.sourceChoice} data-disabled="">
            <Globe size={18} aria-hidden="true" />
            <strong>
              Meta lead forms <Badge tone="warn">Soon</Badge>
            </strong>
            <small>
              Continue with Meta, pick your Page and Instant Forms. Needs AC's
              Meta app first.
            </small>
          </div>
        </div>
        {kind ? (
          <div className={styles.form}>
            <Field label="Name">
              <input
                value={label}
                maxLength={120}
                placeholder={
                  kind === "sheet" ? "Expo leads sheet" : "Website contact form"
                }
                onChange={(event) => setLabel(event.target.value)}
              />
            </Field>
            {kind === "sheet" ? (
              <Field label="Google Sheet link">
                <input
                  value={url}
                  maxLength={500}
                  placeholder="https://docs.google.com/spreadsheets/d/…"
                  onChange={(event) => setUrl(event.target.value)}
                />
              </Field>
            ) : null}
            <div className={styles.row}>
              <Button onClick={() => setKind(null)}>Cancel</Button>
              <Button variant="primary" onClick={create} disabled={busy}>
                {busy ? "Adding…" : "Add source"}
              </Button>
            </div>
          </div>
        ) : null}
      </Panel>

      {sandbox ? (
        <Panel title="Test leads">
          <div className={styles.form}>
            <p className={styles.hint}>
              This is the AC Sandbox organisation. Pull 25 fictional leads from
              the synthetic data: the rules give each one to a fictional seller
              by language, area and product, with the reason on the lead.
            </p>
            <div className={styles.row}>
              <Button onClick={seed} disabled={busy}>
                <FlaskConical size={14} aria-hidden="true" />
                Add 25 test leads
              </Button>
            </div>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
