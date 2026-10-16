"use client";

/**
 * Sales Xray CRM at /leads (code name Lead Desk; owner order 16 Oct 2026).
 *
 * A seller's desk copied from NeoDove's telecalling app: Start calling serves
 * one lead at a time, and every call ends on "Was the call connected?". Owners
 * and admins also get All leads, Team (allocation rules) and Sources.
 */

import { Building2, PhoneCall, Plus, Upload } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  Badge,
  Button,
  Empty,
  PageHeader,
  QueryTabs,
  Skeleton,
} from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { AddLeadDialog, ImportDialog } from "./capture-dialogs";
import { DeskView } from "./desk-view";
import { CallingLoop, LeadSheet } from "./lead-sheet";
import { readDesk, type Desk, LEADS_PATH, LeadsError } from "./leads-client";
import { ListView } from "./list-view";
import { SourcesView } from "./sources-view";
import { TeamView } from "./team-view";
import styles from "./leads.module.css";

type Tab = "desk" | "all" | "team" | "sources";

export function LeadsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="leads">
      <div className={styles.root} aria-busy="true" aria-label="Loading leads">
        <div className={styles.headSkeleton}>
          <Skeleton width={120} height={22} />
          <Skeleton width={260} height={12} />
        </div>
        <div className={styles.tilesSkeleton}>
          {[0, 1, 2, 3].map((key) => (
            <Skeleton key={key} height={86} />
          ))}
        </div>
        <Skeleton height={320} />
      </div>
    </AcquisitionShell>
  );
}

export function LeadsRoute() {
  const access = useWorkspaceAccess();
  const params = useSearchParams();
  const requested = params.get("tab");
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  const contextKey = `${access?.context?.personId}:${access?.context?.tenantId}`;

  const [desk, setDesk] = useState<Desk | null>(null);
  const [deskKey, setDeskKey] = useState<string | null>(null);
  const [error, setError] = useState<LeadsError | null>(null);
  const [version, setVersion] = useState(0);
  const [openLead, setOpenLead] = useState<string | null>(null);
  const [calling, setCalling] = useState(false);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readDesk(controller.signal)
      .then((next) => {
        setDesk(next);
        setDeskKey(contextKey);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason
            : new LeadsError("Your leads didn't load. Try again.", 0),
        );
        setDeskKey(contextKey);
      });
    return () => controller.abort();
  }, [authenticated, contextKey, version]);

  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <LeadsSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="leads"
      >
        <div className={styles.root}>
          <PageHeader title="Leads" />
          <Empty
            icon={PhoneCall}
            title="Sign in to see your leads"
            text="Your leads, follow-ups and calls live here once you're signed in to your organisation."
          />
        </div>
      </AcquisitionShell>
    );
  }

  const current = deskKey === contextKey;
  const can = current && desk ? desk.me.can_manage : false;
  const tab: Tab =
    requested === "all" ||
    (can && (requested === "team" || requested === "sources"))
      ? (requested as Tab)
      : "desk";

  if (current && error && !desk) {
    return (
      <AcquisitionShell authenticated active="leads">
        <div className={styles.root}>
          <PageHeader title="Leads" />
          {error.status === 403 ? (
            <Empty
              icon={Building2}
              title="Leads work inside an organisation"
              text="Switch to your organisation workspace from the account menu, or create one, to get a lead desk for your team."
            />
          ) : (
            <Empty
              icon={PhoneCall}
              title="Your leads didn't load"
              text={error.message}
              action={{ onClick: refresh, label: "Try again" }}
            />
          )}
        </div>
      </AcquisitionShell>
    );
  }

  if (!current || !desk) return <LeadsSkeleton />;

  const tabs = [
    { key: "desk", label: "My desk", count: desk.counts.open },
    { key: "all", label: "All leads" },
    ...(can
      ? [
          {
            key: "team",
            label: "Team",
            count: desk.counts.unassigned || undefined,
          },
          { key: "sources", label: "Lead sources" },
        ]
      : []),
  ];

  return (
    <AcquisitionShell authenticated active="leads">
      <div className={styles.root}>
        <PageHeader
          title="Leads"
          context={[
            desk.me.can_manage
              ? "Your calls and your team's leads"
              : "Who to call today",
            desk.sandbox ? (
              <Badge key="label">Test leads</Badge>
            ) : desk.call_mode === "simulated" ? (
              <Badge key="label">Practice calls</Badge>
            ) : null,
          ]}
          actions={
            <>
              {can ? (
                <Button onClick={() => setImporting(true)}>
                  <Upload size={14} aria-hidden="true" />
                  Import
                </Button>
              ) : null}
              <Button onClick={() => setAdding(true)}>
                <Plus size={14} aria-hidden="true" />
                Add lead
              </Button>
              {tab !== "desk" ? (
                <Button
                  variant="primary"
                  onClick={() => setCalling(true)}
                  disabled={desk.counts.open === 0}
                >
                  <PhoneCall size={14} aria-hidden="true" />
                  Start calling
                </Button>
              ) : null}
            </>
          }
        />
        <QueryTabs base={LEADS_PATH} items={tabs} current={tab} />
        {error ? (
          <div className={styles.notice} role="status">
            {error.message}
            <Button variant="ghost" onClick={refresh}>
              Try again
            </Button>
          </div>
        ) : null}
        {tab === "desk" ? (
          <DeskView
            desk={desk}
            onOpen={setOpenLead}
            onStart={() => setCalling(true)}
            onAdd={() => setAdding(true)}
          />
        ) : tab === "all" ? (
          <ListView canManage={can} onOpen={setOpenLead} version={version} />
        ) : tab === "team" ? (
          <TeamView onChanged={refresh} onOpen={setOpenLead} />
        ) : (
          <SourcesView
            sandbox={desk.sandbox}
            onChanged={refresh}
            onImport={() => setImporting(true)}
          />
        )}
      </div>
      <LeadSheet
        leadId={openLead}
        onClose={() => setOpenLead(null)}
        onChanged={refresh}
      />
      <CallingLoop
        open={calling}
        onClose={() => {
          setCalling(false);
          refresh();
        }}
        onChanged={refresh}
      />
      <AddLeadDialog
        open={adding}
        canManage={can}
        onClose={() => setAdding(false)}
        onAdded={(leadId) => {
          setAdding(false);
          refresh();
          setOpenLead(leadId);
        }}
      />
      <ImportDialog
        open={importing}
        canManage={can}
        onClose={() => setImporting(false)}
        onDone={refresh}
      />
    </AcquisitionShell>
  );
}
