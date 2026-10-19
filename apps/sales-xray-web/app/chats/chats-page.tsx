"use client";

/**
 * Chats at /chats (owner, 20 Oct 2026: "salesxray should have a better chat
 * experience and not everything confused on one panel"). WhatsApp, Messenger
 * and Instagram conversations in one inbox: the list on the left, the open
 * chat beside it. Phones show one at a time; Back returns to the list.
 *
 * The open chat lives after "#" (#chat=<channel>:<lead id>), so a link or a
 * reload opens it again and its id never reaches a server log.
 */

import { Building2, MessagesSquare } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { requestWorkspace } from "../call-ownership";
import { LeadsError, readMe, type Desk } from "../leads/leads-client";
import { notify, dismissNotice } from "../notice-center";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { Empty, Skeleton } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { publishChats, rememberSeen, useSeenMarks } from "./chats-badge";
import {
  CHANNELS,
  CHATS_PATH,
  isUnread,
  NO_FILTER,
  sameThread,
  readChats,
  readSla,
  type ChatChannel,
  type ChatFilter,
  type ChatList,
  type ChatThread,
  type Sla,
} from "./chats-client";
import styles from "./chats.module.css";
import { ThreadFilters, ThreadList, ThreadListSkeleton } from "./thread-list";
import { LeadPanel, LeadSheetDialog } from "./lead-panel";
import { readPanelChoice, savePanelChoice, useMedia } from "./media";
import { ThreadView } from "./thread-view";

const LIST_EVERY_MS = 20 * 1000;
const CLOCK_EVERY_MS = 30 * 1000;

/* ---------- The open chat, after "#" ---------- */

const readHash = () => window.location.hash;
const onHash = (change: () => void) => {
  window.addEventListener("hashchange", change);
  return () => window.removeEventListener("hashchange", change);
};

type Opened = Pick<ChatThread, "key" | "channel" | "leadId" | "accountId">;

/** "#chat=messenger:<lead id>[:<account id>]" → the chat to open. */
export function openedFromHash(hash: string): Opened | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get("chat");
  if (!value) return null;
  const [channel, leadId, accountId] = value.split(":");
  if (!CHANNELS.includes(channel as ChatChannel)) return null;
  if (!leadId || !/^[0-9a-f-]{36}$/i.test(leadId)) return null;
  if (accountId && !/^[0-9a-f-]{36}$/i.test(accountId)) return null;
  return {
    key: value,
    channel: channel as ChatChannel,
    leadId,
    accountId: accountId || null,
  };
}

// The chat this page opened on top of the list: Back pops it again, so the
// phone's own back button and the arrow do the same thing.
let pushedHash: string | null = null;

function openChat(thread: Opened, replace: boolean) {
  const next = `#chat=${thread.key}`;
  if (window.location.hash === next) return;
  if (replace) window.history.replaceState(window.history.state, "", next);
  else window.history.pushState(window.history.state, "", next);
  if (!replace || pushedHash) pushedHash = next;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function closeChat() {
  if (!window.location.hash) return;
  if (pushedHash === window.location.hash) {
    pushedHash = null;
    window.history.back();
    return;
  }
  pushedHash = null;
  window.history.replaceState(
    window.history.state,
    "",
    window.location.pathname + window.location.search,
  );
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/* ---------- Loading frame ---------- */

function ChatsFrame({
  list,
  thread,
  open,
  panel,
}: {
  list: ReactNode;
  thread: ReactNode;
  open: boolean;
  /** The lead beside the chat (computers only; phones use a sheet). */
  panel?: ReactNode;
}) {
  return (
    <div
      className={styles.root}
      data-open={open ? "thread" : "list"}
      data-panel={panel ? "open" : undefined}
    >
      <aside className={styles.listPane} aria-label="Chats list">
        {list}
      </aside>
      <div className={styles.threadPane}>{thread}</div>
      {panel ? (
        <aside className={styles.panelPane} aria-label="Lead">
          {panel}
        </aside>
      ) : null}
    </div>
  );
}

function PickHint() {
  return (
    <div className={styles.pickHint}>
      <span className={styles.emptyMark} aria-hidden="true">
        <MessagesSquare size={20} />
      </span>
      <p className={styles.emptyTitle}>Pick a chat</p>
      <p className={styles.emptyText}>
        WhatsApp, Messenger and Instagram, all in one place. Chats waiting for a
        reply are at the top.
      </p>
    </div>
  );
}

function FiltersSkeleton() {
  return (
    <div className={styles.filters} aria-hidden="true">
      <span className={styles.search} data-placeholder />
      <div className={styles.chips}>
        <Skeleton width={84} height={28} />
        <Skeleton width={96} height={28} />
      </div>
    </div>
  );
}

export function ChatsSkeleton() {
  return (
    <AcquisitionShell authenticated={false} loading active="chats" mobileFit>
      <ChatsFrame
        open={false}
        list={
          <>
            <FiltersSkeleton />
            <ThreadListSkeleton />
          </>
        }
        thread={<PickHint />}
      />
    </AcquisitionShell>
  );
}

/* ---------- The page ---------- */

export function ChatsRoute() {
  const access = useWorkspaceAccess();
  const hash = useSyncExternalStore(onHash, readHash, () => "");
  const opened = openedFromHash(hash);
  const authenticated =
    access?.authenticated === true &&
    access.status === "ready" &&
    !!access.context;
  const personId = access?.context?.personId ?? null;
  const contextKey = `${personId}:${access?.context?.tenantId}`;

  const [me, setMe] = useState<Desk["me"] | null>(null);
  const [list, setList] = useState<ChatList | null>(null);
  const [listKey, setListKey] = useState<string | null>(null);
  const [error, setError] = useState<LeadsError | null>(null);
  const [sla, setSla] = useState<Sla | null>(null);
  const [filter, setFilter] = useState<ChatFilter>(NO_FILTER);
  const marks = useSeenMarks(personId);
  const [version, setVersion] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const hadList = useRef(false);
  // The lead beside the chat: open by default on wide screens, then as the
  // person last left it; on phones a sheet, opened on demand per chat.
  const narrow = useMedia("(max-width: 899.98px)");
  const wide = useMedia("(min-width: 1200px)");
  const [panelChoice, setPanelChoice] = useState<boolean | null>(
    readPanelChoice,
  );
  const [sheetFor, setSheetFor] = useState<string | null>(null);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  // Who I am here (managers see the team's chats) and the reply target.
  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    readMe(controller.signal)
      .then(setMe)
      .catch(() => undefined);
    void readSla().then(setSla);
    return () => controller.abort();
  }, [authenticated, contextKey]);

  useEffect(() => {
    if (!authenticated) return;
    let live = true;
    readChats()
      .then((next) => {
        if (!live) return;
        hadList.current = true;
        setList(next);
        setListKey(contextKey);
        setError(null);
        setNow(new Date());
        publishChats(next.threads);
        dismissNotice("chats-load");
      })
      .catch((reason: unknown) => {
        if (!live) return;
        const problem =
          reason instanceof LeadsError
            ? reason
            : new LeadsError("Your chats didn't load. Try again.", 0);
        setListKey(contextKey);
        setError(problem);
        // With a list on screen, a failed refresh is a corner card only.
        if (hadList.current && problem.status !== 403)
          notify({
            id: "chats-load",
            tone: "error",
            title: "Chats didn't refresh",
            message: problem.message,
            action: { label: "Try again", run: refresh },
          });
      });
    return () => {
      live = false;
    };
  }, [authenticated, contextKey, version, refresh]);

  // Fresh while open: every 20 s, and when the tab or app comes back.
  useEffect(() => {
    if (!authenticated) return;
    const again = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const listTimer = window.setInterval(again, LIST_EVERY_MS);
    const clock = window.setInterval(() => setNow(new Date()), CLOCK_EVERY_MS);
    document.addEventListener("visibilitychange", again);
    window.addEventListener("focus", again);
    return () => {
      window.clearInterval(listTimer);
      window.clearInterval(clock);
      document.removeEventListener("visibilitychange", again);
      window.removeEventListener("focus", again);
    };
  }, [authenticated, refresh]);

  const current = listKey === contextKey;
  const threads = useMemo(
    () => (current && list ? list.threads : []),
    [current, list],
  );
  const openThread =
    (opened && threads.find((thread) => sameThread(thread, opened))) ?? null;

  // Opening a chat (or a new message arriving in the open one) marks it seen.
  useEffect(() => {
    if (personId && openThread) rememberSeen(personId, openThread);
  }, [personId, openThread]);

  if (!authenticated) {
    const loading =
      !access || access.authenticated === null || access.status === "loading";
    return loading ? (
      <ChatsSkeleton />
    ) : (
      <AcquisitionShell
        authenticated={access?.authenticated === true}
        active="chats"
      >
        <SignedOutWelcome
          title="Sign in to see your chats"
          text="WhatsApp, Messenger and Instagram chats with your leads, in one place."
        />
      </AcquisitionShell>
    );
  }

  if (current && error && !list) {
    const organisation = access?.workspaces?.find(
      (workspace) =>
        workspace.kind === "organisation" && workspace.sales_xray_enabled,
    );
    return (
      <AcquisitionShell authenticated active="chats">
        {error.status === 403 ? (
          <Empty
            icon={Building2}
            title="Chats work inside an organisation"
            text={
              organisation
                ? `Your team's chats are in ${organisation.name}.`
                : "Set up an organisation to bring your leads' chats here."
            }
            action={
              organisation
                ? {
                    onClick: () =>
                      requestWorkspace(organisation.tenant_id, CHATS_PATH),
                    label: `Switch to ${organisation.name}`,
                  }
                : { href: "/organisation", label: "Set up an organisation" }
            }
          />
        ) : (
          <Empty
            icon={MessagesSquare}
            title="Your chats didn't load"
            text={error.message}
            action={{ onClick: refresh, label: "Try again" }}
          />
        )}
      </AcquisitionShell>
    );
  }

  const ready = current && !!list;
  const canManage = me?.can_manage === true;
  const showScopes = canManage && !!list?.owners;
  const channels = [...new Set(threads.map((thread) => thread.channel))];
  const waiting = threads.filter((thread) => thread.waiting).length;
  const unread = threads.filter((thread) => isUnread(thread, marks)).length;
  const shownThread = opened
    ? {
        ...opened,
        // Undefined while the list loads; empty when the chat is older than it.
        leadName: openThread?.leadName ?? (ready ? "" : undefined),
        place: openThread?.place,
      }
    : null;
  const leadId = shownThread?.leadId ?? null;
  const panelShown = !narrow && !!leadId && (panelChoice ?? wide);
  const toggleLead = () => {
    if (narrow) {
      setSheetFor(leadId);
      return;
    }
    setPanelChoice(!panelShown);
    savePanelChoice(!panelShown);
  };

  return (
    <AcquisitionShell
      authenticated
      active="chats"
      mobileFit
      pageName={unread ? `Chats (${unread})` : "Chats"}
    >
      <ChatsFrame
        open={!!opened}
        panel={
          panelShown && leadId ? (
            <LeadPanel
              key={leadId}
              leadId={leadId}
              onClose={() => {
                setPanelChoice(false);
                savePanelChoice(false);
              }}
            />
          ) : null
        }
        list={
          ready ? (
            <>
              <ThreadFilters
                filter={filter}
                onChange={setFilter}
                showScopes={showScopes}
                counts={{ waiting }}
                channels={channels}
              />
              <ThreadList
                threads={threads}
                filter={filter}
                me={me?.person_id ?? personId}
                marks={marks}
                sla={list?.sla ?? sla}
                activeKey={openThread?.key ?? opened?.key ?? null}
                showOwner={showScopes}
                now={now}
                onOpen={(thread) =>
                  openChat(
                    {
                      key: thread.key,
                      channel: thread.channel,
                      leadId: thread.leadId,
                      accountId: thread.accountId,
                    },
                    !!opened,
                  )
                }
                onClear={() => setFilter(NO_FILTER)}
              />
            </>
          ) : (
            <>
              <FiltersSkeleton />
              <ThreadListSkeleton />
            </>
          )
        }
        thread={
          shownThread ? (
            <ThreadView
              key={shownThread.key}
              thread={shownThread}
              leadShown={panelShown}
              onLead={toggleLead}
              onBack={closeChat}
              onChanged={refresh}
            />
          ) : (
            <PickHint />
          )
        }
      />
      {narrow && leadId && sheetFor === leadId ? (
        <LeadSheetDialog leadId={leadId} onClose={() => setSheetFor(null)} />
      ) : null}
    </AcquisitionShell>
  );
}
