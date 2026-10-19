"use client";

/**
 * What the organisation's Meta campaigns spent and what each lead from them cost
 * (Marketing API, read with its Continue with Meta connection). Its own ad data,
 * for owners and admins: a line on the Facebook & Instagram source, and a panel on
 * the Team tab with each campaign.
 */

import { RefreshCw, Megaphone } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../ui/kit";
import { ago, LeadsError } from "./leads-client";
import styles from "./leads.module.css";
import { waCall } from "./whatsapp-client";

export type SpendCampaign = {
  campaignId: string;
  campaignName: string;
  adAccountId: string;
  currency: string;
  spend: string;
  impressions: number;
  clicks: number;
  metaLeads: number;
  leads: number;
  won: number;
  perLead?: string | null;
  perCustomer?: string | null;
};
export type SpendTotal = {
  currency: string;
  spend: string;
  leads: number;
  won: number;
  perLead?: string | null;
};
export type SpendReport = {
  configured: boolean;
  connected: boolean;
  syncedAt?: string | null;
  error?: string | null;
  accounts?: number | null;
  /** The connection has no ads_read yet: show nothing, quietly. */
  needsAdsRead?: boolean;
  start: string;
  end: string;
  totals: SpendTotal[];
  campaigns: SpendCampaign[];
};

/** "₹12,340" in the account's own currency, whole units. */
export function money(
  amount: string | null | undefined,
  currency: string,
): string {
  if (amount == null) return "–";
  const value = Number(amount);
  if (!Number.isFinite(value)) return "–";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${currency} ${Math.round(value)}`;
  }
}

/** One line per currency: "₹12,340 spent in 30 days · ₹410 a lead". */
export function spendLine(report: SpendReport): string | null {
  if (!report.totals.length) return null;
  return report.totals
    .map((total) => {
      const each = total.perLead
        ? ` · ${money(total.perLead, total.currency)} a lead`
        : " · no leads here yet";
      return `${money(total.spend, total.currency)} spent in 30 days${each}`;
    })
    .join("; ");
}

function useSpend(): [SpendReport | null, (next: SpendReport) => void] {
  const [report, setReport] = useState<SpendReport | null>(null);
  useEffect(() => {
    let live = true;
    waCall<SpendReport>("/meta/spend?days=30")
      .then(
        (data) =>
          live && setReport(Array.isArray(data?.campaigns) ? data : null),
      )
      .catch(() => live && setReport(null));
    return () => {
      live = false;
    };
  }, []);
  return [report, setReport];
}

/** The line under the Facebook & Instagram source. */
export function SpendSummary() {
  const [report] = useSpend();
  const line = report ? spendLine(report) : null;
  if (!line) return null;
  return <p className={styles.hint}>{line}</p>;
}

export function AdSpendPanel() {
  const [report, setReport] = useSpend();
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (
    !report?.configured ||
    (!report.campaigns.length && (!report.connected || report.needsAdsRead))
  )
    return null;

  const refresh = async () => {
    setBusy(true);
    setNote(null);
    try {
      setReport(
        await waCall<SpendReport>("/meta/spend/refresh?days=30", {
          method: "POST",
        }),
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
    <section className={styles.waSettings} aria-label="Ad spend">
      <div className={styles.waHead}>
        <Megaphone size={18} aria-hidden="true" />
        <h3>Ads: what each lead cost</h3>
        <Button variant="ghost" disabled={busy} onClick={refresh}>
          <RefreshCw size={14} aria-hidden="true" />
          Check now
        </Button>
      </div>
      <p className={styles.hint}>
        Your Meta campaigns over the last 30 days, and the leads that reached
        Sales Xray from each.
        {report.syncedAt ? ` Updated ${ago(report.syncedAt)}.` : ""}
      </p>
      {report.error ? (
        <p className={styles.error} role="alert">
          {report.error}
        </p>
      ) : null}
      {report.campaigns.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Campaign</th>
                <th scope="col">Spent</th>
                <th scope="col">Leads here</th>
                <th scope="col">Per lead</th>
                <th scope="col">Customers</th>
                <th scope="col">Per customer</th>
              </tr>
            </thead>
            <tbody>
              {report.campaigns.map((item) => (
                <tr
                  key={`${item.adAccountId}|${item.campaignId}|${item.currency}`}
                >
                  <td>{item.campaignName}</td>
                  <td>{money(item.spend, item.currency)}</td>
                  <td>
                    {item.leads}
                    {item.metaLeads !== item.leads ? (
                      <small> (Meta counts {item.metaLeads})</small>
                    ) : null}
                  </td>
                  <td>{money(item.perLead, item.currency)}</td>
                  <td>{item.won}</td>
                  <td>{money(item.perCustomer, item.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className={styles.hint}>No campaign spent anything in these days.</p>
      )}
      {note ? (
        <p className={styles.hint} role="status">
          {note}
        </p>
      ) : null}
    </section>
  );
}
