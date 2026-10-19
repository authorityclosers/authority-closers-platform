"use client";

/**
 * First-response SLA on the Team tab: how fast a new lead must hear from a person,
 * phone alerts to the seller (and managers) when it doesn't, and how each seller
 * did over the last week.
 */

import { Timer } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button } from "../ui/kit";
import { LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import {
  inTimeShare,
  waCall,
  type Sla,
  type SlaReport,
} from "./whatsapp-client";

export function SlaPanel() {
  const [report, setReport] = useState<SlaReport | null>(null);
  const [draft, setDraft] = useState<Sla | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    waCall<SlaReport>("/reports/sla")
      .then((data) => {
        if (!live || !data?.settings || !Array.isArray(data.sellers)) return;
        setReport(data);
        setDraft(data.settings);
      })
      .catch(() => live && setReport(null));
    return () => {
      live = false;
    };
  }, []);

  if (!report || !draft) return null;

  const save = async () => {
    setBusy(true);
    setNote(null);
    try {
      const saved = await waCall<Sla>("/sla", {
        method: "PUT",
        body: JSON.stringify({
          on: draft.on,
          minutes: draft.minutes,
          alertManagers: draft.alertManagers,
        }),
      });
      setDraft(saved);
      setReport({ ...report, settings: saved });
      setNote(
        saved.on
          ? `Target saved: ${saved.minutes} minutes.`
          : "Target switched off.",
      );
    } catch (reason) {
      setNote(
        reason instanceof LeadsError ? reason.message : "That didn't work.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.slaPanel} aria-label="First response">
      <div className={styles.waHead}>
        <Timer size={16} aria-hidden="true" />
        <strong>First response</strong>
        <Badge tone={report.settings.on ? "good" : "neutral"}>
          {report.settings.on ? `${report.settings.minutes} min target` : "Off"}
        </Badge>
      </div>
      <p className={styles.hint}>
        A new lead should hear from a person within the target: a call, or a
        WhatsApp a seller sends. Auto replies don&apos;t count. When it passes,
        the seller gets a phone alert.
      </p>
      <div className={styles.row}>
        <label className={styles.slaField}>
          <input
            type="checkbox"
            checked={draft.on}
            onChange={(event) =>
              setDraft({ ...draft, on: event.target.checked })
            }
          />
          Use a first-response target
        </label>
        <select
          aria-label="Target"
          value={draft.minutes}
          disabled={!draft.on}
          onChange={(event) =>
            setDraft({ ...draft, minutes: Number(event.target.value) })
          }
        >
          {draft.targets.map((minutes) => (
            <option key={minutes} value={minutes}>
              {minutes < 60
                ? `${minutes} minutes`
                : `${minutes / 60} hour${minutes === 60 ? "" : "s"}`}
            </option>
          ))}
        </select>
        <label className={styles.slaField}>
          <input
            type="checkbox"
            checked={draft.alertManagers}
            disabled={!draft.on}
            onChange={(event) =>
              setDraft({ ...draft, alertManagers: event.target.checked })
            }
          />
          Alert owners and admins too
        </label>
        <Button variant="primary" disabled={busy} onClick={save}>
          Save
        </Button>
      </div>
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
      {report.sellers.length ? (
        <table className={styles.slaTable}>
          <caption>
            Last 7 days ({report.start} to {report.end})
          </caption>
          <thead>
            <tr>
              <th scope="col">Seller</th>
              <th scope="col">Leads</th>
              <th scope="col">In time</th>
              <th scope="col">Late</th>
              <th scope="col">Waiting</th>
              <th scope="col">Usual first reply</th>
            </tr>
          </thead>
          <tbody>
            {report.sellers.map((seller) => (
              <tr key={seller.personId ?? "none"}>
                <th scope="row">{seller.name}</th>
                <td>{seller.leads}</td>
                <td>{inTimeShare(seller)}</td>
                <td>{seller.breached}</td>
                <td>{seller.waiting}</td>
                <td>
                  {seller.medianMinutes == null
                    ? "–"
                    : `${seller.medianMinutes} min`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={styles.hint}>No new leads in the last 7 days.</p>
      )}
    </section>
  );
}
