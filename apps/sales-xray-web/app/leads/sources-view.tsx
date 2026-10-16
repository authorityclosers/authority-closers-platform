"use client";

/**
 * Sources: where leads come from. Every source ends in the same capture path,
 * and each lead keeps exactly what its source sent. Meta lead forms first,
 * Google Ads lead forms second (owner, 16 Oct), then websites, sheets and files.
 */

import {
  Copy,
  FileSpreadsheet,
  FlaskConical,
  Globe,
  Megaphone,
  RefreshCw,
  Sheet as SheetIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
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
import { MetaCard } from "./meta-card";
import styles from "./leads.module.css";

const GOOGLE_ADS = "Google Ads lead form";
type Kind = "webhook" | "google_ads" | "sheet";

const isGoogleAds = (source: SourceView) =>
  source.kind === "webhook" && source.label.startsWith("Google Ads");

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

function Steps({ source }: { source: SourceView }) {
  if (isGoogleAds(source))
    return (
      <ol className={styles.howTo}>
        <li>
          In Google Ads, open the campaign&apos;s lead form, then Export leads,
          then Webhook integration.
        </li>
        <li>
          Paste the address above as the Webhook URL and the key as the Key.
        </li>
        <li>Press Send test data. The test lead appears on the desk here.</li>
      </ol>
    );
  return (
    <ol className={styles.howTo}>
      <li>
        Your website or tool sends each enquiry to the address above as JSON or
        a normal form post.
      </li>
      <li>
        Send the key in an <code>X-Lead-Desk-Key</code> header, or add{" "}
        <code>?key=</code> to the address for a plain HTML form.
      </li>
      <li>
        Any field names work: name, phone, email, city and what they want are
        picked out, and everything else is kept on the lead.
      </li>
    </ol>
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
  const google = isGoogleAds(source);
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
  const endpoint = source.endpoint
    ? google
      ? `${source.endpoint}/google-ads`
      : source.endpoint
    : null;
  return (
    <li className={styles.source}>
      <span className={styles.sourceIcon} aria-hidden="true">
        {source.kind === "sheet" ? (
          <SheetIcon size={16} />
        ) : google ? (
          <Megaphone size={16} />
        ) : (
          <Globe size={16} />
        )}
      </span>
      <span className={styles.sourceMain}>
        <strong>
          {source.label} {source.active ? null : <Badge>Paused</Badge>}
        </strong>
        <small>
          {source.kind === "sheet"
            ? "Google Sheet"
            : google
              ? "Google Ads lead form"
              : "Website form"}{" "}
          · {source.received} received
          {source.last_received_at
            ? ` · last ${when(source.last_received_at)}`
            : ""}
        </small>
        {endpoint ? <CopyText value={endpoint} label="address" /> : null}
        {source.token ? (
          <span className={styles.secretOnce}>
            Key (shown once, keep it safe):{" "}
            <CopyText value={source.token} label="key" />
          </span>
        ) : null}
        {source.sheet_url ? (
          <small className={styles.ellipsis}>{source.sheet_url}</small>
        ) : null}
        {source.kind === "webhook" ? (
          <details className={styles.terms} open={!!source.token}>
            <summary>How to connect it</summary>
            <Steps source={source} />
          </details>
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

const CHOICES: {
  kind: Kind;
  title: string;
  text: string;
  icon: typeof Globe;
}[] = [
  {
    kind: "google_ads",
    title: "Google Ads lead form",
    text: "Leads from your Google Ads lead forms land here within seconds. Two values to paste.",
    icon: Megaphone,
  },
  {
    kind: "webhook",
    title: "Website form",
    text: "Your site or another tool posts each enquiry. You get an address and a key.",
    icon: Globe,
  },
  {
    kind: "sheet",
    title: "Google Sheet",
    text: 'Share the sheet as "Anyone with the link can view", paste the link, then sync.',
    icon: SheetIcon,
  },
];

export function SourcesView({
  sandbox,
  onChanged,
  onImport,
}: {
  sandbox: boolean;
  onChanged: () => void;
  onImport: () => void;
}) {
  const params = useSearchParams();
  const [data, setData] = useState<Sources | null>(null);
  const [fresh, setFresh] = useState<Record<string, SourceView>>({});
  const [note, setNote] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
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

  const choose = (next: Kind) => {
    setKind(next);
    setNote(null);
    setLabel(next === "google_ads" ? GOOGLE_ADS : "");
  };

  const create = async () => {
    if (!kind || !label.trim()) {
      setNote("Give the source a name.");
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const made = await addSource({
        kind: kind === "sheet" ? "sheet" : "webhook",
        label:
          kind === "google_ads" && !label.trim().startsWith("Google Ads")
            ? `${GOOGLE_ADS}: ${label.trim()}`.slice(0, 120)
            : label.trim(),
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

  const listed = (data?.sources ?? []).filter(
    (source) => source.kind !== "meta",
  );

  return (
    <div className={styles.sourcesGrid}>
      <Panel title="Ad platforms">
        <div className={styles.adGrid}>
          <MetaCard returned={params.get("meta")} />
          <div className={styles.metaCard}>
            <div className={styles.metaHead}>
              <strong>Google Ads lead forms</strong>
              <Badge tone="good">Ready</Badge>
            </div>
            <p className={styles.hint}>
              Add a Google Ads source below: you get a webhook address and a key
              to paste into the lead form, then press Send test data in Google
              Ads.
            </p>
            <div className={styles.row}>
              <Button variant="primary" onClick={() => choose("google_ads")}>
                <Megaphone size={14} aria-hidden="true" />
                Connect Google Ads
              </Button>
            </div>
          </div>
        </div>
      </Panel>

      <Panel
        title="Connected sources"
        sub={data ? `${listed.length}` : undefined}
      >
        {data === null ? (
          <Skeleton height={120} />
        ) : listed.length ? (
          <ul className={styles.sourceList}>
            {listed.map((source) => (
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
            No sources yet. Connect Google Ads, a website form or a Google Sheet
            below.
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
          {CHOICES.map((choice) => (
            <button
              key={choice.kind}
              type="button"
              className={styles.sourceChoice}
              aria-pressed={kind === choice.kind}
              onClick={() => choose(choice.kind)}
            >
              <choice.icon size={18} aria-hidden="true" />
              <strong>{choice.title}</strong>
              <small>{choice.text}</small>
            </button>
          ))}
          <button
            type="button"
            className={styles.sourceChoice}
            onClick={onImport}
          >
            <FileSpreadsheet size={18} aria-hidden="true" />
            <strong>CSV or Excel file</strong>
            <small>Upload once, match the columns, done.</small>
          </button>
        </div>
        {kind ? (
          <div className={styles.form}>
            <Field label="Name">
              <input
                value={label}
                maxLength={120}
                placeholder={
                  kind === "sheet"
                    ? "Expo leads sheet"
                    : kind === "google_ads"
                      ? GOOGLE_ADS
                      : "Website contact form"
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
