"use client";

/**
 * Leads setup → Sources → Campaigns (owner, 2-3 Nov 2026: "live, paused and old
 * campaigns managed so the app isn't cluttered"; design cleared by ux-audit). One
 * folded row like the other sources; inside, each campaign with one Live, Paused or
 * Ended chip, the ended ones folded under "Ended (n)". The status sorts campaigns in
 * Analytics; a form, sheet or website is switched off where it is listed, and a real
 * enquiry is never dropped. A file of old leads starts Ended.
 */

import { useEffect, useState } from "react";

import { SOURCE_WORDS } from "../../leads/lead-filters";
import { LeadsError } from "../../leads/leads-client";
import {
  readPipelineReport,
  setCampaignStatus,
  type CampaignRow,
  type CampaignStatus,
} from "../../leads/pipeline/pipeline-client";
import { notify } from "../../notice-center";
import { Picker } from "../../ui/picker";
import own from "./campaigns.module.css";
import styles from "./setup.module.css";

const STATUSES: { key: CampaignStatus; label: string }[] = [
  { key: "live", label: "Live" },
  { key: "paused", label: "Paused" },
  { key: "ended", label: "Ended" },
];

function lastLead(at: string | null): string | null {
  if (!at) return null;
  return new Date(at).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

function CampaignLine({
  row,
  onChange,
}: {
  row: CampaignRow;
  onChange: (status: CampaignStatus) => void;
}) {
  const last = lastLead(row.last_lead_at);
  return (
    <li>
      <span className={own.name}>
        {row.label}
        <small>
          {[
            SOURCE_WORDS[row.source] ?? row.source,
            `${row.leads} lead${row.leads === 1 ? "" : "s"}`,
            last ? `last ${last}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </small>
      </span>
      <Picker
        title={`${row.label}: status`}
        ariaLabel={`Status of ${row.label}`}
        mode="inline"
        value={row.status}
        options={STATUSES}
        onChange={(key) => {
          if (key) onChange(key as CampaignStatus);
        }}
      />
    </li>
  );
}

export function CampaignStatuses() {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<CampaignRow[] | null>(null);
  const [revision, setRevision] = useState(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    readPipelineReport({ days: 0 }, controller.signal).then(
      (report) => {
        setRows(report.campaigns ?? []);
        setRevision(report.revision ?? 0);
      },
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setRows([]);
        notify({
          id: "campaigns",
          tone: "error",
          title: "Campaigns didn't load",
          message: reason instanceof LeadsError ? reason.message : "Try again.",
        });
      },
    );
    return () => controller.abort();
  }, [open, attempt]);

  const change = async (row: CampaignRow, status: CampaignStatus) => {
    if (status === row.status) return;
    try {
      const saved = await setCampaignStatus(row.key, status, revision);
      setRevision(saved.revision);
      setRows(
        (current) =>
          current?.map((item) =>
            item.key === row.key ? { ...item, status } : item,
          ) ?? current,
      );
    } catch (reason) {
      notify({
        id: "campaign-status",
        tone: "error",
        title: "The status didn't save",
        message: reason instanceof LeadsError ? reason.message : "Try again.",
      });
      setAttempt((value) => value + 1);
    }
  };
  const working = rows?.filter((row) => row.status !== "ended") ?? [];
  const ended = rows?.filter((row) => row.status === "ended") ?? [];

  return (
    <details
      className={styles.details}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Campaigns</summary>
      {open ? (
        <div className={own.campaigns}>
          {rows === null ? (
            <p className={own.note}>Reading your campaigns…</p>
          ) : !rows.length ? (
            <p className={own.note}>
              No campaigns yet: an ad&apos;s campaign and each imported file
              show here.
            </p>
          ) : (
            <>
              {working.length ? (
                <ul className={own.rows} aria-label="Live and paused campaigns">
                  {working.map((row) => (
                    <CampaignLine
                      key={row.key}
                      row={row}
                      onChange={(status) => void change(row, status)}
                    />
                  ))}
                </ul>
              ) : null}
              {ended.length ? (
                <details className={own.ended}>
                  <summary>Ended ({ended.length})</summary>
                  <ul className={own.rows} aria-label="Ended campaigns">
                    {ended.map((row) => (
                      <CampaignLine
                        key={row.key}
                        row={row}
                        onChange={(status) => void change(row, status)}
                      />
                    ))}
                  </ul>
                </details>
              ) : null}
              <p className={own.note}>
                A real enquiry is never dropped, whatever a campaign&apos;s
                status.
              </p>
            </>
          )}
        </div>
      ) : null}
    </details>
  );
}
