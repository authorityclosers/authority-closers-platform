"use client";

/**
 * Lead stage options for the owner to choose from (22 Oct 2026), drawn the
 * way Lead stages draws a path. A proposal only: nothing here is saved, and
 * the business meaning is the owner's call.
 */

import { AcquisitionShell } from "../../acquisition-shell";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";
import styles from "./stage-options.module.css";

type Kind =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost";

const OPTIONS: {
  key: string;
  title: string;
  fits: string;
  pick?: string;
  stages: [string, Kind][];
  outcomes: string[];
}[] = [
  {
    key: "A",
    title: "A · Partner outreach",
    fits: "Cold B2B lists, like Partner Leads",
    pick: "Recommended for partner lists",
    stages: [
      ["New", "new"],
      ["Couldn't reach", "not_connected"],
      ["Gatekeeper", "follow_up"],
      ["Spoke to owner", "follow_up"],
      ["Interested", "interested"],
      ["Meeting booked", "interested"],
      ["Meeting done", "interested"],
      ["Partner signed", "won"],
      ["Not a fit", "lost"],
    ],
    outcomes: [
      "Didn't pick → Couldn't reach, retried by itself",
      "Talked to staff → Gatekeeper",
      "Owner, not now → Spoke to owner + call-back date",
      "Wants details → Interested + send the deck",
      "Agreed to meet → Meeting booked (date)",
      "Said no → Not a fit (reason)",
    ],
  },
  {
    key: "B",
    title: "B · Enrolment",
    fits: "Inbound enquiries for a programme",
    pick: "Recommended for enquiries",
    stages: [
      ["New enquiry", "new"],
      ["Couldn't reach", "not_connected"],
      ["Counselled", "follow_up"],
      ["Session booked", "interested"],
      ["Session attended", "interested"],
      ["Payment pending", "interested"],
      ["Enrolled", "won"],
      ["Lost", "lost"],
    ],
    outcomes: [
      "Counselled → next call date",
      "Session booked → session date",
      "Payment pending → payment follow-up date",
    ],
  },
  {
    key: "C",
    title: "C · One simple list",
    fits: "Both kinds of leads in one list",
    stages: [
      ["New", "new"],
      ["Couldn't reach", "not_connected"],
      ["Talked", "follow_up"],
      ["Interested", "interested"],
      ["Meeting or demo booked", "interested"],
      ["Proposal or payment pending", "interested"],
      ["Won", "won"],
      ["Lost", "lost"],
    ],
    outcomes: ["Works today with one list; fewest stages to learn"],
  },
];

export function StageOptionsPreview() {
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: {
          personId: "00000000-0000-4000-8000-000000000001",
          sessionId: "00000000-0000-4000-8000-000000000005",
          tenantId: "00000000-0000-4000-8000-000000000004",
        },
        workspaces: [
          {
            tenant_id: "00000000-0000-4000-8000-000000000004",
            kind: "organisation",
            name: "Fictional Homes",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="leads" pageName="Lead stages">
        <div className={styles.page}>
          <PageHeader
            title="Lead stage options"
            context={["A proposal for the owner to pick from"]}
          />
          <div className={styles.grid}>
            {OPTIONS.map((option) => (
              <section key={option.key} className={styles.option}>
                <header>
                  <h2>{option.title}</h2>
                  <p>{option.fits}</p>
                  {option.pick ? (
                    <span className={styles.pick}>{option.pick}</span>
                  ) : null}
                </header>
                <ol className={styles.path}>
                  {option.stages.map(([label, kind]) => (
                    <li key={label} data-kind={kind}>
                      {label}
                    </li>
                  ))}
                </ol>
                <ul className={styles.outcomes}>
                  {option.outcomes.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}
