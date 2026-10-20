"use client";

/**
 * First-response SLA on the Team tab: how fast a new lead must hear from a person,
 * phone alerts to the seller (and managers) when it doesn't, and how each seller
 * did over the last week. Owner, 20 Oct: one clear card, a switch and a target,
 * Save only after a change, and who is late right now at the top.
 */

import { Timer } from "lucide-react";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import {
  AppCard,
  AppCardSkeleton,
  AppLogo,
  cardStyles,
  Group,
  SaveBar,
  StatusPill,
  SubCard,
  SwitchRow,
} from "./app-card";
import { LeadsError } from "./leads-client";
import {
  inTimeShare,
  waCall,
  type Sla,
  type SlaReport,
} from "./whatsapp-client";

const TITLE = "First response";
const LOGO = <AppLogo icon={Timer} />;

const targetWords = (minutes: number) =>
  minutes < 60
    ? `${minutes} minutes`
    : `${minutes / 60} hour${minutes === 60 ? "" : "s"}`;

export function SlaPanel({ onOpen }: { onOpen?: (leadId: string) => void }) {
  const [report, setReport] = useState<SlaReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState<Sla | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    waCall<SlaReport>("/reports/sla")
      .then((data) => {
        if (!live) return;
        setLoaded(true);
        if (!data?.settings || !Array.isArray(data.sellers)) return;
        setReport(data);
        setDraft(data.settings);
      })
      .catch(() => live && setLoaded(true));
    return () => {
      live = false;
    };
  }, []);

  if (!loaded) return <AppCardSkeleton title={TITLE} logo={LOGO} lines={2} />;
  if (!report || !draft) return null;

  const base = report.settings;
  const dirty =
    draft.on !== base.on ||
    draft.minutes !== base.minutes ||
    draft.alertManagers !== base.alertManagers;
  const change = (next: Sla) => {
    setSaved(null);
    setDraft(next);
  };
  const save = async () => {
    setBusy(true);
    try {
      const next = await waCall<Sla>("/sla", {
        method: "PUT",
        body: JSON.stringify({
          on: draft.on,
          minutes: draft.minutes,
          alertManagers: draft.alertManagers,
        }),
      });
      setDraft(next);
      setReport({ ...report, settings: next });
      setSaved(
        next.on
          ? `Target saved: ${next.minutes} minutes.`
          : "Target switched off.",
      );
    } catch (reason) {
      notify({
        id: "sla-settings",
        tone: "error",
        title: "Not saved",
        message:
          reason instanceof LeadsError
            ? reason.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  const late = report.late ?? [];

  return (
    <AppCard
      logo={LOGO}
      title={TITLE}
      status={
        base.on ? (
          <StatusPill tone="good">
            {targetWords(base.minutes)} target
          </StatusPill>
        ) : (
          <StatusPill>Off</StatusPill>
        )
      }
      summary="A new lead should hear from a person within the target: a call, or a WhatsApp a seller sends. Auto replies don't count. When it passes, the seller gets a phone alert."
    >
      {late.length ? (
        <SubCard
          tone="bad"
          title={`Waiting past the target now: ${late.length} lead${late.length === 1 ? "" : "s"}`}
          meta="The longest wait first. Tap one to open it."
        >
          <ul className={cardStyles.rows} role="status">
            {late.map((item) => (
              <li key={item.leadId}>
                <button type="button" onClick={() => onOpen?.(item.leadId)}>
                  <span>
                    <strong>{item.leadName}</strong>
                    <small>{item.seller}</small>
                  </span>
                  <StatusPill tone="bad">
                    {item.minutesLate} min late
                  </StatusPill>
                </button>
              </li>
            ))}
          </ul>
        </SubCard>
      ) : null}
      <Group title="Your target">
        <SwitchRow
          label="Use a first-response target"
          hint="Leads that arrive outside your work hours start their clock when work starts."
          checked={draft.on}
          onChange={(on) => change({ ...draft, on })}
        >
          <label className={cardStyles.field}>
            <span className={cardStyles.fieldLabel}>
              <strong>A person answers within</strong>
            </span>
            <select
              aria-label="Target"
              value={draft.minutes}
              onChange={(event) =>
                change({ ...draft, minutes: Number(event.target.value) })
              }
            >
              {draft.targets.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {targetWords(minutes)}
                </option>
              ))}
            </select>
          </label>
          <SwitchRow
            label="Alert owners and admins too"
            hint="Their phones get the same alert as the seller's."
            checked={draft.alertManagers}
            onChange={(on) => change({ ...draft, alertManagers: on })}
          />
        </SwitchRow>
        <SaveBar
          dirty={dirty}
          busy={busy}
          saved={!!saved}
          savedText={saved ?? undefined}
          onSave={() => void save()}
          onDiscard={() => setDraft(base)}
        />
      </Group>
      <Group title="Last 7 days">
        {report.sellers.length ? (
          <div className={cardStyles.tableWrap}>
            <table className={cardStyles.table}>
              <caption className={cardStyles.srOnly}>
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
          </div>
        ) : (
          <p className={cardStyles.quietText}>
            No new leads in the last 7 days.
          </p>
        )}
      </Group>
    </AppCard>
  );
}
