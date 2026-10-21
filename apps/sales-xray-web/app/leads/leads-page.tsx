"use client";

/**
 * Sales Xray CRM at /leads (code name Lead Desk; owner order 16 Oct 2026).
 *
 * A seller's desk copied from NeoDove's telecalling app: Start calling serves
 * one lead at a time, and every call ends on "Was the call connected?". Owners
 * and admins also get All leads, Team (allocation rules) and Sources.
 *
 * Phones (UX study, 17 Oct): Start calling comes first (no subtitle, buttons
 * or tab row on the desk), pull down to refresh, swipe a row to call or
 * message, hold it for more. The desk refreshes itself whenever the app or tab
 * comes back to the front and every minute while it is open. A phone alert
 * opens its lead through /leads#lead=<id> (ids only, after "#").
 */

import {
  Building2,
  Inbox,
  ListChecks,
  PhoneCall,
  Plug,
  Plus,
  Route,
  UsersRound,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { DeskChats } from "../chats/desk-chats";
import { LeadsChatsSwitch } from "../chats/leads-chats-switch";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { Badge, Button, Empty, PageHeader, QueryTabs } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { requestWorkspace } from "../call-ownership";
import {
  AddLeadDialog,
  AddLeadsMenu,
  ContactsDialog,
  ImportDialog,
  type AddWay,
} from "./capture-dialogs";
import { AlertsCard } from "./alerts-card";
import { PhoneLogCard } from "./phone-log-card";
import { PhoneSetupBar } from "./phone-setup";
import { UnknownCallsCard } from "./unknown-calls-card";
import { PhoneAppBanner, PhoneAppDialog } from "./phone-app";
import { ANDROID_DOWNLOAD_READY } from "./phone-app-flag";
import { DeskView, dueNow, type DeskLink, type RowActions } from "./desk-view";
import { usePullToRefresh } from "./gestures";
import { LeadActions } from "./lead-actions";
import { LEAD_ADDED_EVENT, takeHandedLead } from "./lead-handoff";
import { CallingLoop, LeadSheet, type LeadIntent } from "./lead-sheet";
import { publishBadge } from "./leads-badge";
import {
  LEADS_PATH,
  LeadsError,
  linkedLead,
  pickContacts,
  readDesk,
  sharedLead,
  type Desk,
  type LeadRow,
  type PickedContact,
} from "./leads-client";
import { MessageSetup } from "./message-sheet";
import { forgetUnknown, onPhoneSignal } from "./native-phone";
import { LeadsSkeleton } from "./leads-skeleton";
import { JourneyTab } from "./journey/journey-view";
import { ListView } from "./list-view";
import { SourcesView } from "./sources-view";
import { TakingSwitch } from "./taking-switch";
import { TeamView } from "./team-view";
import styles from "./leads.module.css";

type Tab = "desk" | "all" | "team" | "sources" | "stages";

// The desk reads itself again when the app comes back, and every minute.
const REFRESH_EVERY_MS = 60 * 1000;
const REFRESH_GAP_MS = 15 * 1000;

// The handed-over lead is read once, then wiped from the address at once, so it
// never sits in the address bar or the browser's history.
let handedOver: string | null = null;
const readHash = () => (handedOver ??= window.location.hash);
const onHashChange = (change: () => void) => {
  const listener = () => {
    handedOver = null;
    change();
  };
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
};

export { LeadsSkeleton };

export function LeadsRoute() {
  const access = useWorkspaceAccess();
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  // A lead handed over by the Chrome extension opens Add lead, filled in. It
  // travels after "#", so the lead's details never reach a server or its logs.
  const hash = useSyncExternalStore(onHashChange, readHash, () => "");
  const shared = sharedLead(new URLSearchParams(hash.replace(/^#/, "")));
  const linked = linkedLead(hash);
  const [linkDone, setLinkDone] = useState<string | null>(null);
  useEffect(() => {
    if (/(^|[#&])(add=lead|lead=)/.test(window.location.hash))
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname + window.location.search,
      );
  }, [hash]);
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
  const [intent, setIntent] = useState<LeadIntent | null>(null);
  const [holding, setHolding] = useState<LeadRow | null>(null);
  const waiters = useRef<(() => void)[]>([]);
  const lastRead = useRef(0);
  const [calling, setCalling] = useState(false);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [menu, setMenu] = useState(false);
  // The account menu's "Phone app" row lands here (only while the download
  // is on); the Leads header no longer carries it (owner, 18 Oct).
  const [apps, setApps] = useState<boolean>(
    () => ANDROID_DOWNLOAD_READY && params.get("app") === "1",
  );
  const [sharedDone, setSharedDone] = useState(false);
  // A work call's number the seller chose to save as a lead (from the phone).
  const [unknownLead, setUnknownLead] = useState<string | null>(null);
  const [contacts, setContacts] = useState(false);
  const [picked, setPicked] = useState<PickedContact[]>([]);
  // Each opening mounts a fresh dialog, so nothing is reset in an effect.
  const [rounds, setRounds] = useState({
    calling: 0,
    adding: 0,
    importing: 0,
    menu: 0,
    contacts: 0,
    apps: 0,
  });
  const begin = (
    which: keyof typeof rounds,
    show: (value: boolean) => void,
  ) => {
    setRounds((current) => ({ ...current, [which]: current[which] + 1 }));
    show(true);
  };

  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  // A lead added from the + sheet opens here, ready to call (owner, 22 Oct).
  useEffect(() => {
    const show = (leadId: string | null) => {
      if (!leadId) return;
      setHolding(null);
      setIntent(null);
      setOpenLead(leadId);
      refresh();
    };
    show(takeHandedLead());
    const onAdded = () => show(takeHandedLead());
    window.addEventListener(LEAD_ADDED_EVENT, onAdded);
    return () => window.removeEventListener(LEAD_ADDED_EVENT, onAdded);
  }, [refresh]);
  const closeShared = () => setSharedDone(true);
  // Pull to refresh waits for the desk to come back before the spinner goes.
  const reload = useCallback(
    () =>
      new Promise<void>((resolve) => {
        waiters.current.push(resolve);
        refresh();
      }),
    [refresh],
  );
  const { area, spinner } = usePullToRefresh(reload);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    const settle = () => {
      lastRead.current = Date.now();
      waiters.current.splice(0).forEach((resolve) => resolve());
    };
    readDesk(controller.signal)
      .then((next) => {
        setDesk(next);
        setDeskKey(contextKey);
        setError(null);
        publishBadge({
          overdue: next.counts.overdue ?? 0,
          to_call: dueNow(next),
        });
        settle();
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof LeadsError
            ? reason
            : new LeadsError("Your leads didn't load. Try again.", 0),
        );
        setDeskKey(contextKey);
        settle();
      });
    return () => controller.abort();
  }, [authenticated, contextKey, version]);

  // Back in the app or the tab, an alert while open, or a minute gone: read again.
  useEffect(() => {
    if (!authenticated) return;
    const again = (force = false) => {
      if (document.visibilityState !== "visible") return;
      if (!force && Date.now() - lastRead.current < REFRESH_GAP_MS) return;
      refresh();
    };
    const onVisible = () => again();
    const timer = window.setInterval(() => again(true), REFRESH_EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    const stop = onPhoneSignal((event) => {
      if (event === "resume" || event === "alert" || event === "calls")
        again(event !== "resume");
    });
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
      stop();
    };
  }, [authenticated, refresh]);

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
          <PageHeader title="Leads" titleInBar />
          <SignedOutWelcome
            title="Sign in to see your leads"
            text="Your leads, follow-ups and calls, ready the moment you sign in to your organisation."
          />
        </div>
      </AcquisitionShell>
    );
  }

  const current = deskKey === contextKey;
  const can = current && desk ? desk.me.can_manage : false;
  const tab: Tab =
    requested === "all" ||
    requested === "stages" ||
    (can && (requested === "team" || requested === "sources"))
      ? (requested as Tab)
      : "desk";

  const organisation = access?.workspaces?.find(
    (workspace) =>
      workspace.kind === "organisation" && workspace.sales_xray_enabled,
  );

  if (current && error && !desk) {
    return (
      <AcquisitionShell authenticated active="leads">
        <div className={styles.root}>
          <PageHeader title="Leads" titleInBar />
          {error.status === 403 ? (
            // A personal workspace: one tap into the organisation, or to
            // the page that creates one (phones have no sidebar switcher).
            <Empty
              icon={Building2}
              title="Leads work inside an organisation"
              text={
                organisation
                  ? `Your team's lead desk is in ${organisation.name}.`
                  : "Set up an organisation to get a lead desk for your team."
              }
              action={
                organisation
                  ? {
                      onClick: () =>
                        requestWorkspace(organisation.tenant_id, LEADS_PATH),
                      label: `Switch to ${organisation.name}`,
                    }
                  : { href: "/organisation", label: "Set up an organisation" }
              }
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

  // A phone alert's lead opens once; closing it leaves the desk.
  const fromLink = linked && linkDone !== hash ? linked : null;
  const shownLead = openLead ?? fromLink?.leadId ?? null;
  const shownIntent: LeadIntent | null = openLead
    ? intent
    : fromLink?.call
      ? "call"
      : null;
  const open = (leadId: string, next: LeadIntent | null = null) => {
    setLinkDone(hash);
    setHolding(null);
    setIntent(next);
    setOpenLead(leadId);
  };
  const rowActions: RowActions = {
    onCall: (row) => open(row.lead_id, "call"),
    onMessage: (row) => open(row.lead_id, "message"),
    onHold: (row) => setHolding(row),
  };
  const org =
    access?.workspaces?.find(
      (workspace) => workspace.tenant_id === access.context?.tenantId,
    )?.name ?? "";
  const links: DeskLink[] = [
    {
      key: "all",
      label: "All leads",
      note: "Search and filters",
      href: `${LEADS_PATH}?tab=all`,
    },
    ...(can
      ? [
          {
            key: "team",
            label: "Team",
            note: desk.counts.unassigned
              ? `${desk.counts.unassigned} need an owner`
              : "Who gets which leads",
            href: `${LEADS_PATH}?tab=team`,
          },
          {
            key: "sources",
            label: "Lead sources",
            note: "Meta, forms, sheets",
            href: `${LEADS_PATH}?tab=sources`,
          },
          {
            key: "stages",
            label: "Lead stages",
            note: "Your steps from enquiry to sale",
            href: `${LEADS_PATH}?tab=stages`,
          },
        ]
      : []),
    {
      key: "add",
      label: "Add leads",
      note: "Type, paste, contacts or a file",
      onClick: () => begin("menu", setMenu),
    },
  ];

  // Five tabs at most, each with an icon (the AC design system's rule, as in Pulse).
  const tabs = [
    {
      key: "desk",
      label: (
        <>
          <Inbox size={15} aria-hidden="true" />
          My desk
        </>
      ),
      count: desk.counts.open,
    },
    {
      key: "all",
      label: (
        <>
          <ListChecks size={15} aria-hidden="true" />
          All leads
        </>
      ),
    },
    ...(can
      ? [
          {
            key: "team",
            label: (
              <>
                <UsersRound size={15} aria-hidden="true" />
                Team
              </>
            ),
            count: desk.counts.unassigned || undefined,
          },
          {
            key: "sources",
            label: (
              <>
                <Plug size={15} aria-hidden="true" />
                Lead sources
              </>
            ),
          },
          {
            key: "stages",
            label: (
              <>
                <Route size={15} aria-hidden="true" />
                Lead stages
              </>
            ),
          },
        ]
      : []),
  ];

  return (
    <AcquisitionShell authenticated active="leads">
      <MessageSetup.Provider
        value={{ templates: desk.templates ?? [], myName: desk.me.name, org }}
      >
        <div ref={area} className={styles.root} data-tab={tab}>
          <div
            ref={spinner}
            className={styles.pullSpinner}
            aria-hidden="true"
          />
          {/* Phones: Leads | Chats (owner, 20 Oct: Chats inside Leads). */}
          <LeadsChatsSwitch current="leads" />
          <PhoneSetupBar />
          <div className={styles.wideOnly}>
            <PageHeader
              title="Leads"
              titleInBar
              context={[
                desk.me.can_manage
                  ? "Your calls and your team's leads"
                  : "Who to call today",
                desk.sandbox ? (
                  <Badge key="label">Test leads</Badge>
                ) : desk.call_mode === "simulated" ? (
                  <Badge key="label">Sample calls</Badge>
                ) : null,
              ]}
              actions={
                <>
                  <TakingSwitch
                    key={`taking-${desk.me.taking_leads !== false}`}
                    initial={desk.me.taking_leads !== false}
                    place="header"
                    onChanged={refresh}
                  />
                  <Button onClick={() => begin("menu", setMenu)}>
                    <Plus size={14} aria-hidden="true" />
                    Add leads
                  </Button>
                  {tab !== "desk" ? (
                    <Button
                      variant="primary"
                      onClick={() => begin("calling", setCalling)}
                      disabled={desk.counts.open === 0}
                    >
                      <PhoneCall size={14} aria-hidden="true" />
                      Start calling
                    </Button>
                  ) : null}
                </>
              }
            />
          </div>
          {tab === "desk" ? null : (
            <PhoneAppBanner onOpen={() => begin("apps", setApps)} />
          )}
          <div className={tab === "desk" ? styles.wideOnly : undefined}>
            <QueryTabs base={LEADS_PATH} items={tabs} current={tab} />
          </div>
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
              onOpen={(leadId) => open(leadId)}
              onStart={() => begin("calling", setCalling)}
              onAdd={() => begin("menu", setMenu)}
              actions={rowActions}
              links={links}
              afterHero={
                <>
                  <TakingSwitch
                    key={`taking-${desk.me.taking_leads !== false}`}
                    initial={desk.me.taking_leads !== false}
                    place="row"
                    pausedUntil={desk.me.paused_until ?? null}
                    onChanged={refresh}
                  />
                  <PhoneAppBanner onOpen={() => begin("apps", setApps)} />
                  <AlertsCard />
                  <PhoneLogCard />
                  <UnknownCallsCard onSave={setUnknownLead} />
                  {/* Owner, 20 Oct: chats live in Chats; the desk links there. */}
                  <DeskChats />
                </>
              }
            />
          ) : tab === "all" ? (
            <ListView
              canManage={can}
              onOpen={(leadId) => open(leadId)}
              version={version}
              actions={rowActions}
              onChanged={refresh}
            />
          ) : tab === "team" ? (
            <TeamView onChanged={refresh} onOpen={(leadId) => open(leadId)} />
          ) : tab === "stages" ? (
            <JourneyTab canManage={can} />
          ) : (
            <SourcesView
              sandbox={desk.sandbox}
              onChanged={refresh}
              onImport={() => begin("importing", setImporting)}
            />
          )}
        </div>
        <LeadSheet
          leadId={shownLead}
          me={desk.me}
          intent={shownIntent}
          onClose={() => {
            setLinkDone(hash);
            setOpenLead(null);
            setIntent(null);
          }}
          onChanged={refresh}
        />
        {holding ? (
          <LeadActions
            key={holding.lead_id}
            row={holding}
            canManage={can}
            onClose={() => setHolding(null)}
            onCall={(row) => open(row.lead_id, "call")}
            onMessage={(row) => open(row.lead_id, "message")}
            onOpen={(leadId) => open(leadId)}
            onChanged={refresh}
          />
        ) : null}
        <CallingLoop
          key={rounds.calling}
          open={calling}
          me={desk.me}
          onClose={() => {
            setCalling(false);
            refresh();
          }}
          onChanged={refresh}
        />
        {shared ? (
          <AddLeadDialog
            key={`shared-${hash}`}
            open={!sharedDone}
            canManage={can}
            initial={shared}
            onClose={closeShared}
            onAdded={(leadId) => {
              closeShared();
              refresh();
              setOpenLead(leadId);
            }}
          />
        ) : null}
        {unknownLead ? (
          <AddLeadDialog
            key={`unknown-${unknownLead}`}
            open
            canManage={can}
            initial={{ name: "", phone: unknownLead, email: "", note: "" }}
            initialNote="A work call on your phone. Add their name, then add the lead."
            onClose={() => setUnknownLead(null)}
            onAdded={(leadId) => {
              void forgetUnknown(unknownLead);
              setUnknownLead(null);
              refresh();
              setOpenLead(leadId);
            }}
          />
        ) : null}
        <AddLeadDialog
          key={rounds.adding}
          open={adding}
          canManage={can}
          onClose={() => setAdding(false)}
          onAdded={(leadId) => {
            setAdding(false);
            refresh();
            setOpenLead(leadId);
          }}
        />
        <PhoneAppDialog
          key={`apps-${rounds.apps}`}
          open={apps}
          onClose={() => setApps(false)}
        />
        <AddLeadsMenu
          key={`menu-${rounds.menu}`}
          open={menu}
          canManage={can}
          onClose={() => setMenu(false)}
          onPick={(way: AddWay) => {
            setMenu(false);
            if (way === "type") begin("adding", setAdding);
            else if (way === "file") begin("importing", setImporting);
            else if (way === "sources")
              router.push(`${LEADS_PATH}?tab=sources`);
            else
              pickContacts()
                .then((people) => {
                  if (!people.length) return;
                  setPicked(people);
                  begin("contacts", setContacts);
                })
                .catch(() => undefined);
          }}
        />
        <ContactsDialog
          key={`contacts-${rounds.contacts}`}
          open={contacts}
          picked={picked}
          canManage={can}
          onClose={() => setContacts(false)}
          onDone={refresh}
        />
        <ImportDialog
          key={rounds.importing}
          open={importing}
          canManage={can}
          onClose={() => setImporting(false)}
          onDone={refresh}
        />
      </MessageSetup.Provider>
    </AcquisitionShell>
  );
}
