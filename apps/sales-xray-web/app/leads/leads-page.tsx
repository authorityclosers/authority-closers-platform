"use client";

/**
 * Sales Xray CRM at /leads (code name Lead Desk; owner order 16 Oct 2026).
 *
 * A seller's desk copied from NeoDove's telecalling app: Start calling serves
 * one lead at a time, and every call ends on "Was the call connected?".
 *
 * Owner, 22 Oct 2026 ("pathetic", "a design flaw"): one page, one strip of
 * stage tabs. To call is the desk; Open, New, Not contacted, Follow up,
 * Interested, Won and Lost come from the organisation's own stages, with
 * real counts, and switch in place (the address follows without a page
 * move). Owners and admins pick whose leads in one small chip. The switches
 * are small chips, an empty list is one line, Start calling sits in a bar
 * above the tab bar on phones, and Team, Lead sources, Lead stages, Import
 * and Test leads live in the ⋯ menu. Adding one lead is the tab bar's +.
 *
 * The desk refreshes itself whenever the app or tab comes back to the front
 * and every minute while it is open. A phone alert opens its lead through
 * /leads#lead=<id> (ids only, after "#"); pull down to refresh.
 */

import {
  ArrowLeft,
  Building2,
  Ellipsis,
  Phone,
  PhoneCall,
  Plus,
  UserRound,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { useCommandSource, type CommandSource } from "../ui/command-registry";
import { DeskChats } from "../chats/desk-chats";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { leavingOverlay } from "../ui/back-close";
import { Badge, Button, Empty, PageHeader } from "../ui/kit";
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
import { RecordedCallsCard } from "./recorded-calls";
import { PhoneAppBanner, PhoneAppDialog } from "./phone-app";
import { ANDROID_DOWNLOAD_READY } from "./phone-app-flag";
import { ActionSheet } from "./action-sheet";
import { DeskView, dueNow, whyLine, type RowActions } from "./desk-view";
import { usePullToRefresh } from "./gestures";
import {
  MAIN_PIPELINE,
  readJourney,
  type JourneyView,
} from "./journey/journey-client";
import { LeadActions } from "./lead-actions";
import {
  LEAD_ADDED_EVENT,
  takeHandedLead,
  type HandedLead,
} from "./lead-handoff";
import { CallingLoop, LeadSheet, type LeadIntent } from "./lead-sheet";
import { publishBadge } from "./leads-badge";
import { LeadsMenu, type LeadsMenuItem } from "./leads-menu";
import {
  LEADS_PATH,
  LeadsError,
  linkedLead,
  pickContacts,
  readDesk,
  readLeads,
  sharedLead,
  type Desk,
  type LeadRow,
  type PickedContact,
} from "./leads-client";
import { MessageSetup } from "./message-sheet";
import { forgetUnknown, onPhoneSignal } from "./native-phone";
import { LeadsSkeleton } from "./leads-skeleton";
import { JourneyTab } from "./journey/journey-view";
import { ListView, TEST, type Scope } from "./list-view";
import { asScope, type ViewSpec } from "./saved-views";
import { KIND_ORDER, StageTabs, stageTabs } from "./stage-tabs";
import { SourcesView } from "./sources-view";
import { TakingSwitch } from "./taking-switch";
import { TeamView } from "./team-view";
import { several, usePipelines } from "./use-pipelines";
import { ViewsChip } from "./views-sheet";
import {
  ActiveFilters,
  FilterChip,
  FilterSheet,
  filtersOn as countFilters,
  type LeadFilters,
} from "./lead-filters";
import styles from "./leads.module.css";

type Manage = "team" | "sources" | "stages";

const MANAGE_TITLE: Record<Manage, string> = {
  team: "Team",
  sources: "Lead sources",
  stages: "Lead stages",
};

const WHO_WORDS: Record<Scope, string> = {
  team: "Everyone",
  mine: "Mine",
  unassigned: "No owner",
};

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

/** The address of a view on this page: the desk, a stage (in one pipeline, when
 * picked; whose leads and a search, when set), or a settings page. A stage's
 * address is the whole view, so a refresh or a shared link keeps it. */
function viewHref(
  view: string,
  pipeline: string | null = null,
  filters: { who?: Scope | null; q?: string } = {},
): string {
  const path = window.location.pathname || LEADS_PATH;
  if (view === "desk") return path;
  if (view === "team" || view === "sources" || view === "stages")
    return `${path}?tab=${view}`;
  const inPipeline = pipeline
    ? `&pipeline=${encodeURIComponent(pipeline)}`
    : "";
  const who = filters.who ? `&who=${filters.who}` : "";
  const words = filters.q?.trim();
  const q = words ? `&q=${encodeURIComponent(words)}` : "";
  return `${path}?tab=all&stage=${encodeURIComponent(view)}${inPipeline}${who}${q}`;
}

export { LeadsSkeleton };

export function LeadsRoute() {
  const access = useWorkspaceAccess();
  const params = useSearchParams();
  const requested = params.get("tab");
  const requestedStage = params.get("stage");
  const requestedPipeline = params.get("pipeline");
  const addressKey = params.toString();
  // A lead handed over by the Chrome extension opens Add lead, filled in. It
  // travels after "#", so the lead's details never reach a server or its logs.
  const hash = useSyncExternalStore(onHashChange, readHash, () => "");
  const shared = sharedLead(new URLSearchParams(hash.replace(/^#/, "")));
  const linked = linkedLead(hash);
  const [linkDone, setLinkDone] = useState<string | null>(null);
  // A lead's own link, /leads?lead=<id> (Liquid Glass, 22 Oct 2026): its sheet
  // opens on arrival and a refresh keeps it; closing it takes the id away.
  // #lead= stays the same for phone alerts and older links.
  const addressLead = linkedLead(`lead=${params.get("lead") ?? ""}`);
  const [addressLeadDone, setAddressLeadDone] = useState<string | null>(null);
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
  // A swipe right asks once before it calls: a sloppy sideways scroll must
  // never ring a lead (Redmi audit #13, 22 Oct 2026).
  const [dialling, setDialling] = useState<LeadRow | null>(null);
  const waiters = useRef<(() => void)[]>([]);
  const lastRead = useRef(0);
  const [calling, setCalling] = useState(false);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [menu, setMenu] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // A settings page opened from the menu is a step of its own: Leads goes back.
  const pushedSettings = useRef(false);
  // The view picked here, until the address catches up (the router follows
  // history.replaceState; without one, as in a static preview, this holds it).
  const [picked, setPicked] = useState<{
    view: string;
    at: string;
    pipeline?: string | null;
  } | null>(null);
  // Whose leads and the search start from the address (a saved view, a link).
  const [scopeChoice, setScopeChoice] = useState<Scope | null>(() =>
    asScope(params.get("who")),
  );
  // Leads → Filter: a fresh sheet each opening.
  const [filtering, setFiltering] = useState<{
    round: number;
    open: boolean;
  } | null>(null);
  const [search, setSearch] = useState(() => params.get("q") ?? "");
  const [query, setQuery] = useState(() => (params.get("q") ?? "").trim());
  // Counts answer a question (who, search, pipeline); a refresh asks it again
  // and the last answer stays on the tabs meanwhile (Redmi, 22 Oct 2026: the
  // counts vanished while the ⋯ sheet was open).
  const [counts, setCounts] = useState<{
    key: string;
    question: string;
    value: Record<string, number>;
  } | null>(null);
  const [journey, setJourney] = useState<{
    key: string;
    view: JourneyView;
  } | null>(null);
  // The account menu's "Phone app" row lands here (only while the download
  // is on); the Leads header no longer carries it (owner, 18 Oct).
  const [apps, setApps] = useState<boolean>(
    () => ANDROID_DOWNLOAD_READY && params.get("app") === "1",
  );
  const [sharedDone, setSharedDone] = useState(false);
  // A work call's number the seller chose to save as a lead (from the phone).
  const [unknownLead, setUnknownLead] = useState<string | null>(null);
  const [contacts, setContacts] = useState(false);
  const [picks, setPicks] = useState<PickedContact[]>([]);
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
  // A lead added from the + sheet, or Home's "Call <name>", opens here
  // (owner, 22 Oct).
  useEffect(() => {
    const show = (handed: HandedLead | null) => {
      if (!handed) return;
      setHolding(null);
      setIntent(handed.call ? "call" : null);
      setOpenLead(handed.leadId);
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

  // Search waits until typing stops.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

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

  const pipes = usePipelines(authenticated);

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

  const current = deskKey === contextKey;
  const can = current && desk ? desk.me.can_manage : false;
  // Only owners and admins pick whose leads; a seller's are always their own.
  const scope: Scope = can ? (scopeChoice ?? "team") : "mine";
  const filters = { who: can ? scopeChoice : null, q: query };

  // From the address: the desk, a stage, or one of the settings pages.
  const stageKeys = new Set<string>([
    "open",
    ...KIND_ORDER,
    ...(can ? [TEST] : []),
  ]);
  const fromAddress: string =
    requested === "stages" ||
    (can && (requested === "team" || requested === "sources"))
      ? requested
      : requested === "all"
        ? requestedStage && stageKeys.has(requestedStage)
          ? requestedStage
          : "open"
        : "desk";
  const view = picked && picked.at === addressKey ? picked.view : fromAddress;
  const manage: Manage | null =
    view === "team" || view === "sources" || view === "stages" ? view : null;
  const stageView = !manage && view !== "desk";
  // Several pipelines: a stage view shows one pipeline's leads, or all of them.
  const fromAddressPipeline =
    several(pipes) &&
    pipes.pipelines.some((item) => item.key === requestedPipeline)
      ? requestedPipeline
      : null;
  const pipeline: string | null =
    stageView && several(pipes) && view !== TEST
      ? picked && picked.at === addressKey && picked.pipeline !== undefined
        ? picked.pipeline
        : fromAddressPipeline
      : null;
  const countsQuestion = JSON.stringify([contextKey, scope, query, pipeline]);
  const countsKey = JSON.stringify([
    contextKey,
    scope,
    query,
    pipeline,
    version,
  ]);

  // The tabs carry the stages of the pipeline shown; across several, the six kinds.
  const journeyFor = several(pipes) ? pipeline : MAIN_PIPELINE;
  const journeyKey = `${contextKey}:${journeyFor}`;
  useEffect(() => {
    if (!authenticated || !journeyFor) return;
    let live = true;
    readJourney(journeyFor)
      .then((next) => {
        if (live) setJourney({ key: journeyKey, view: next });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [authenticated, journeyFor, journeyKey]);

  // The desk needs the stage counts too: one list read gives every stage's.
  const freshCounts = counts?.key === countsKey;
  const haveCounts = counts?.question === countsQuestion;
  useEffect(() => {
    if (!authenticated || !current || stageView || freshCounts || manage)
      return;
    const controller = new AbortController();
    readLeads({ scope, stage: "open", search: query }, controller.signal)
      .then((page) => {
        if (page.stage_counts)
          setCounts({
            key: countsKey,
            question: countsQuestion,
            value: page.stage_counts,
          });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [
    authenticated,
    current,
    stageView,
    freshCounts,
    manage,
    scope,
    query,
    countsKey,
    countsQuestion,
  ]);
  const onCounts = useCallback(
    (value: Record<string, number>) =>
      setCounts({ key: countsKey, question: countsQuestion, value }),
    [countsKey, countsQuestion],
  );

  // The settled search goes into the address in place, like the tabs.
  const addressQuery = (params.get("q") ?? "").trim();
  useEffect(() => {
    if (!stageView || query === addressQuery) return;
    window.history.replaceState(
      null,
      "",
      viewHref(view, pipeline, { who: can ? scopeChoice : null, q: query }),
    );
  }, [stageView, query, addressQuery, view, pipeline, can, scopeChoice]);

  // The command bar (Ctrl K, the header's search) while Leads is open: Start
  // calling, Add lead, and each lead found to open or to call. A call asks
  // first, as a swipe does; nothing dials from the bar.
  const canStart = current && !!desk && desk.counts.open > 0;
  const commands = useMemo<CommandSource | null>(() => {
    if (!authenticated) return null;
    const openLead = (leadId: string, next: LeadIntent | null = null) => {
      setHolding(null);
      setIntent(next);
      setOpenLead(leadId);
    };
    const round = (which: "calling" | "adding") =>
      setRounds((value) => ({ ...value, [which]: value[which] + 1 }));
    return {
      commands: [
        ...(canStart
          ? [
              {
                id: "leads:start-calling",
                group: "Actions",
                label: "Start calling",
                hint: "One due lead at a time",
                icon: <PhoneCall size={16} aria-hidden="true" />,
                run: () => {
                  round("calling");
                  setCalling(true);
                },
              },
            ]
          : []),
        {
          id: "leads:add-lead",
          group: "Actions",
          label: "Add lead",
          icon: <Plus size={16} aria-hidden="true" />,
          run: () => {
            round("adding");
            setAdding(true);
          },
        },
      ],
      search: async (text, signal) => {
        const page = await readLeads(
          { scope: can ? "team" : "mine", search: text },
          signal,
        );
        return page.leads.slice(0, 6).flatMap((row) => [
          {
            id: `leads:open:${row.lead_id}`,
            group: "Leads",
            label: row.name,
            hint: [row.stage_label, row.city].filter(Boolean).join(" · "),
            icon: <UserRound size={16} aria-hidden="true" />,
            run: () => openLead(row.lead_id),
          },
          ...(row.phone_last4
            ? [
                {
                  id: `leads:call:${row.lead_id}`,
                  group: "Leads",
                  label: `Call ${row.name}`,
                  hint: `Ends in ${row.phone_last4}`,
                  icon: <Phone size={16} aria-hidden="true" />,
                  run: () => setDialling(row),
                },
              ]
            : []),
        ]);
      },
    };
  }, [authenticated, can, canStart]);
  useCommandSource("leads", commands);

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
  const addressOpen =
    addressLead && addressLeadDone !== addressLead.leadId ? addressLead : null;
  const shownLead = openLead ?? fromLink?.leadId ?? addressOpen?.leadId ?? null;
  // Done with the address's lead: it neither comes back nor stays in the bar.
  // The sheet may close by stepping Back, which lands after this; the id goes
  // again once it has.
  const leaveAddressLead = () => {
    if (!addressLead) return;
    setAddressLeadDone(addressLead.leadId);
    const strip = () => {
      const next = new URLSearchParams(window.location.search);
      if (!next.has("lead")) return;
      next.delete("lead");
      const query = next.toString();
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    };
    strip();
    window.addEventListener("popstate", () => window.setTimeout(strip, 0), {
      once: true,
    });
  };
  const shownIntent: LeadIntent | null = openLead
    ? intent
    : fromLink?.call
      ? "call"
      : null;
  const open = (leadId: string, next: LeadIntent | null = null) => {
    setLinkDone(hash);
    leaveAddressLead();
    setHolding(null);
    setIntent(next);
    setOpenLead(leadId);
  };
  const rowActions: RowActions = {
    onCall: (row) => setDialling(row),
    onMessage: (row) => open(row.lead_id, "message"),
    onHold: (row) => setHolding(row),
    onLog: (row) => open(row.lead_id, "log"),
  };
  const org =
    access?.workspaces?.find(
      (workspace) => workspace.tenant_id === access.context?.tenantId,
    )?.name ?? "";
  const toCall = dueNow(desk);

  // Tabs and filters change the address in place, so Back never steps
  // through them; a settings page is a step of its own, so Back returns.
  const go = (next: string) => {
    const href = viewHref(next, pipeline, filters);
    setPicked({ view: next, at: addressKey, pipeline });
    if (next === "team" || next === "sources" || next === "stages") {
      pushedSettings.current = true;
      window.history.pushState(null, "", href);
    } else window.history.replaceState(null, "", href);
  };
  const leaveSettings = () => {
    setPicked({ view: "desk", at: addressKey });
    if (pushedSettings.current) {
      pushedSettings.current = false;
      window.history.back();
    } else window.history.replaceState(null, "", viewHref("desk"));
  };
  // An empty list's "Clear filters": everyone's (or your own) leads, no search.
  const filtersOn =
    !!query || (can && scopeChoice !== null && scopeChoice !== "team");
  const clearFilters = () => {
    setScopeChoice(null);
    setSearch("");
    setQuery("");
    window.history.replaceState(null, "", viewHref(view, pipeline));
  };
  const tabs = [
    { key: "desk", label: "To call", count: toCall },
    ...stageTabs(
      journey?.key === journeyKey ? journey.view : null,
      haveCounts ? counts.value : null,
    ),
    ...(view === TEST ? [{ key: TEST, label: "Test leads" }] : []),
  ];
  const stageLabel =
    tabs.find((tab) => tab.key === view)?.label ??
    (view === "open" ? "Open" : "this stage");

  // Leads → Filter (stage lists only): whose leads, the pipeline, a name or number.
  const filterable = stageView && view !== TEST;
  const defaultWho: Scope = can ? "team" : "mine";
  const shownFilters: LeadFilters = { who: scope, pipeline, q: query };

  // Saved views: what the list shows now, in words, and back in one tap.
  const shown: ViewSpec = { stage: view, pipeline, who: scope, q: query };
  const describeView = (spec: ViewSpec) =>
    [
      tabs.find((tab) => tab.key === spec.stage)?.label ??
        (spec.stage === "open" ? "Open" : "A stage"),
      spec.pipeline
        ? (pipes?.pipelines.find((item) => item.key === spec.pipeline)?.name ??
          null)
        : null,
      can ? WHO_WORDS[spec.who] : null,
      spec.q ? `“${spec.q}”` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  const applyFilters = (next: LeadFilters) =>
    applyView({
      stage: view,
      pipeline: next.pipeline,
      who: next.who,
      q: next.q,
    });
  const applyView = (spec: ViewSpec) => {
    const stage = stageKeys.has(spec.stage) ? spec.stage : "open";
    const inPipeline = several(pipes) ? spec.pipeline : null;
    const who = can ? spec.who : null;
    setScopeChoice(who);
    setSearch(spec.q);
    setQuery(spec.q);
    setPicked({ view: stage, at: addressKey, pipeline: inPipeline });
    window.history.replaceState(
      null,
      "",
      viewHref(stage, inPipeline, { who, q: spec.q }),
    );
  };

  const menuItems: LeadsMenuItem[] = [
    ...(can
      ? [
          {
            key: "team",
            label: "Team",
            note: desk.counts.unassigned
              ? `${desk.counts.unassigned} need an owner`
              : "Who gets which leads",
            onPick: () => {
              setSettingsOpen(false);
              leavingOverlay();
              go("team");
            },
          },
          {
            key: "sources",
            label: "Lead sources",
            note: "Facebook, Instagram, forms and sheets",
            onPick: () => {
              setSettingsOpen(false);
              leavingOverlay();
              go("sources");
            },
          },
        ]
      : []),
    {
      key: "stages",
      label: "Lead stages",
      note: can
        ? "Your steps from enquiry to sale, and what your ads learn"
        : "Your team's steps from enquiry to sale",
      onPick: () => {
        setSettingsOpen(false);
        leavingOverlay();
        go("stages");
      },
    },
    {
      key: "import",
      label: "Import leads",
      note: can
        ? "From your phone's contacts, a file or your ads"
        : "From your phone's contacts",
      onPick: () => {
        setSettingsOpen(false);
        begin("menu", setMenu);
      },
    },
    ...(can
      ? [
          {
            key: "test",
            label: "Test leads",
            note: "Sample and test leads, ready to clear",
            onPick: () => {
              setSettingsOpen(false);
              go(TEST);
            },
          },
        ]
      : []),
  ];

  return (
    <AcquisitionShell authenticated active="leads">
      <MessageSetup.Provider
        value={{ templates: desk.templates ?? [], myName: desk.me.name, org }}
      >
        <div
          ref={area}
          className={styles.root}
          data-tab={manage ?? (stageView ? "all" : "desk")}
          data-call-bar={view === "desk" && toCall > 0 ? "" : undefined}
        >
          <div
            ref={spinner}
            className={styles.pullSpinner}
            aria-hidden="true"
          />
          <PhoneSetupBar />
          <div className={styles.wideOnly}>
            <PageHeader
              title={manage ? MANAGE_TITLE[manage] : "Leads"}
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
                  <Button onClick={() => begin("menu", setMenu)}>
                    <Plus size={14} aria-hidden="true" />
                    Add leads
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => begin("calling", setCalling)}
                    disabled={desk.counts.open === 0}
                  >
                    <PhoneCall size={14} aria-hidden="true" />
                    Start calling
                  </Button>
                </>
              }
            />
          </div>
          {manage ? (
            <div className={styles.toolbar}>
              <button
                type="button"
                className={styles.backChip}
                onClick={leaveSettings}
              >
                <ArrowLeft size={16} aria-hidden="true" />
                Leads
              </button>
              <h2 className={styles.toolbarTitle}>{MANAGE_TITLE[manage]}</h2>
            </div>
          ) : (
            <>
              <div className={styles.toolbar}>
                <TakingSwitch
                  key={`taking-${desk.me.taking_leads !== false}`}
                  initial={desk.me.taking_leads !== false}
                  place="chip"
                  pausedUntil={desk.me.paused_until ?? null}
                  onChanged={refresh}
                />
                <PhoneLogCard as="chip" />
                <span className={styles.toolbarEnd}>
                  {filterable ? (
                    <FilterChip
                      count={countFilters(shownFilters, defaultWho)}
                      onOpen={() =>
                        setFiltering((current) => ({
                          round: (current?.round ?? 0) + 1,
                          open: true,
                        }))
                      }
                    />
                  ) : null}
                  <button
                    type="button"
                    className={styles.toolButton}
                    aria-label="Leads settings"
                    aria-haspopup="dialog"
                    onClick={() => setSettingsOpen(true)}
                  >
                    <Ellipsis size={18} aria-hidden="true" />
                  </button>
                </span>
              </div>
              {filterable ? (
                <ActiveFilters
                  filters={shownFilters}
                  defaultWho={defaultWho}
                  pipes={pipes?.pipelines ?? []}
                  onChange={applyFilters}
                />
              ) : null}
              <StageTabs tabs={tabs} current={view} onChange={go} />
            </>
          )}
          {error ? (
            <div className={styles.notice} role="status">
              {error.message}
              <Button variant="ghost" onClick={refresh}>
                Try again
              </Button>
            </div>
          ) : null}
          {manage === "team" ? (
            <TeamView onChanged={refresh} onOpen={(leadId) => open(leadId)} />
          ) : manage === "stages" ? (
            <JourneyTab canManage={can} />
          ) : manage === "sources" ? (
            <SourcesView
              sandbox={desk.sandbox}
              onChanged={refresh}
              onImport={() => begin("importing", setImporting)}
            />
          ) : stageView ? (
            <ListView
              canManage={can}
              stage={view}
              stageLabel={stageLabel}
              scope={view === TEST ? "team" : scope}
              query={query}
              onOpen={(leadId) => open(leadId)}
              version={version}
              actions={rowActions}
              onChanged={refresh}
              onCounts={onCounts}
              pipeline={pipeline}
              filtered={filtersOn}
              onClearFilters={clearFilters}
              onAdd={() => begin("adding", setAdding)}
              onShowOpen={() => go("open")}
              tools={
                view === TEST ? null : (
                  <ViewsChip
                    owner={contextKey}
                    current={shown}
                    describe={describeView}
                    onApply={applyView}
                  />
                )
              }
            />
          ) : (
            <DeskView
              desk={desk}
              onOpen={(leadId) => open(leadId)}
              onAdd={() => begin("adding", setAdding)}
              actions={rowActions}
              afterHero={
                <>
                  <PhoneAppBanner onOpen={() => begin("apps", setApps)} />
                  <AlertsCard />
                  <PhoneLogCard as="offer" />
                  <RecordedCallsCard me={desk.me} />
                  <UnknownCallsCard onSave={setUnknownLead} />
                  {/* Owner, 20 Oct: chats live in Chats; the desk links there. */}
                  <DeskChats />
                </>
              }
            />
          )}
          {/* Phones: the one primary action, in the thumb's reach above the
              tab bar (owner, 22 Oct: no big green card). Nobody due: no bar,
              the desk says "All caught up" (Redmi, 22 Oct). */}
          {view === "desk" && toCall > 0 ? (
            <div className={styles.callBar}>
              <button
                type="button"
                className={styles.callBarButton}
                onClick={() => begin("calling", setCalling)}
              >
                <PhoneCall size={18} aria-hidden="true" />
                Start calling
                {toCall ? (
                  <span className={styles.callBarCount}>{`${toCall} due`}</span>
                ) : null}
              </button>
            </div>
          ) : null}
        </div>
        {filtering ? (
          <FilterSheet
            key={filtering.round}
            open={filtering.open}
            onClose={() =>
              setFiltering((current) => current && { ...current, open: false })
            }
            filters={shownFilters}
            defaultWho={defaultWho}
            canPickWho={can}
            pipes={several(pipes) ? pipes.pipelines : []}
            onApply={applyFilters}
          />
        ) : null}
        <LeadsMenu
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          items={menuItems}
        />
        <LeadSheet
          leadId={shownLead}
          me={desk.me}
          intent={shownIntent}
          onClose={() => {
            setLinkDone(hash);
            leaveAddressLead();
            setOpenLead(null);
            setIntent(null);
          }}
          onChanged={refresh}
          onNext={(leadId) => open(leadId, "call")}
        />
        <ActionSheet
          open={!!dialling}
          title={dialling ? `Call ${dialling.name}?` : "Call"}
          sub={dialling ? whyLine(dialling) : undefined}
          onClose={() => setDialling(null)}
        >
          <div className={styles.confirmCall}>
            <button
              type="button"
              className={styles.callBarButton}
              onClick={() => {
                const row = dialling;
                setDialling(null);
                if (row) open(row.lead_id, "call");
              }}
            >
              <PhoneCall size={18} aria-hidden="true" />
              Call now
            </button>
          </div>
        </ActionSheet>
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
          key={`calling-${rounds.calling}`}
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
          key={`adding-${rounds.adding}`}
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
            else if (way === "sources") {
              leavingOverlay();
              if (view === "sources") return;
              go("sources");
            } else
              pickContacts()
                .then((people) => {
                  if (!people.length) return;
                  setPicks(people);
                  begin("contacts", setContacts);
                })
                .catch(() => undefined);
          }}
        />
        <ContactsDialog
          key={`contacts-${rounds.contacts}`}
          open={contacts}
          picked={picks}
          canManage={can}
          onClose={() => setContacts(false)}
          onDone={refresh}
        />
        <ImportDialog
          key={`importing-${rounds.importing}`}
          open={importing}
          canManage={can}
          onClose={() => setImporting(false)}
          onDone={refresh}
        />
      </MessageSetup.Provider>
    </AcquisitionShell>
  );
}
