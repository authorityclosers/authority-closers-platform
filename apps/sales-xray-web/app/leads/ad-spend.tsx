"use client";

/**
 * What the organisation's Meta campaigns spent and what each lead from them cost
 * (Marketing API, read with its Continue with Meta connection). Its own ad data,
 * for owners and admins: a line on the Facebook & Instagram source, and a panel on
 * the Team tab with each campaign.
 */

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { AppCard, AppLogo, cardStyles, StatusPill } from "./app-card";
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
  const [busy, setBusy] = useState(false);
  if (
    !report?.configured ||
    (!report.campaigns.length && (!report.connected || report.needsAdsRead))
  )
    return null;

  const refresh = async () => {
    setBusy(true);
    try {
      setReport(
        await waCall<SpendReport>("/meta/spend/refresh?days=30", {
          method: "POST",
        }),
      );
    } catch (reason) {
      notify({
        id: "ad-spend",
        tone: "error",
        title: "Not updated",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  const line = spendLine(report);
  return (
    <AppCard
      logo={<AppLogo brands={["meta"]} />}
      title="Ads: what each lead cost"
      label="Ad spend"
      status={
        report.syncedAt ? (
          <StatusPill tone="accent">Updated {ago(report.syncedAt)}</StatusPill>
        ) : null
      }
      summary={`Your Meta campaigns over the last 30 days, and the leads that reached Sales X-Ray from each. Only owners and admins see this.${line ? ` ${line}.` : ""}`}
      action={
        <button
          type="button"
          className={cardStyles.secondary}
          disabled={busy}
          onClick={() => void refresh()}
        >
          <RefreshCw size={14} aria-hidden="true" />
          {busy ? "Checking…" : "Check now"}
        </button>
      }
    >
      {report.error ? (
        <p className={cardStyles.problem} role="status">
          {report.error}
        </p>
      ) : null}
      {report.campaigns.length ? (
        <div className={cardStyles.tableWrap}>
          <table className={cardStyles.table}>
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
                  <th scope="row">{item.campaignName}</th>
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
        <p className={cardStyles.quietText}>
          No campaign spent anything in these days.
        </p>
      )}
    </AppCard>
  );
}
