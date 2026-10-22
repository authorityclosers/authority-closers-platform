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
  useState,
  useSyncExternalStore,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import { requestWorkspace } from "../call-ownership";
import { readMe, type Desk } from "../leads/leads-client";
import { notify, dismissNotice } from "../notice-center";
import { SignedOutWelcome } from "../shell/signed-out-welcome";
import { Empty } from "../ui/kit";
import { useWorkspaceAccess } from "../workspace-access";
import { rememberSeen, useSeenMarks } from "./chats-badge";
import {
  CHANNELS,
  CHATS_PATH,
  isUnread,
  NO_FILTER,
  sameThread,
  readSla,
  type ChatChannel,
  type ChatFilter,
  type ChatThread,
  type Sla,
} from "./chats-client";
import { refreshChats, useChats } from "./chats-store";
import {
  ChatsFrame,
  ChatsSkeleton,
  FiltersSkeleton,
  PickHint,
  ThreadListSkeleton,
  useManagesChats,
} from "./chats-skeleton";
import { ThreadFilters, ThreadList } from "./thread-list";
import { LeadPanel, LeadSheetDialog } from "./lead-panel";
import { readPanelChoice, savePanelChoice, useMedia } from "./media";
import { ThreadView } from "./thread-view";

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

export { ChatsSkeleton };

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
  const [sla, setSla] = useState<Sla | null>(null);
  const [filter, setFilter] = useState<ChatFilter>(NO_FILTER);
  const marks = useSeenMarks(personId);
  const manages = useManagesChats();
  // One shared reader: every 15 s while this screen is open and in view,
  // paused while hidden, again on coming back and right after a send.
  const { list, error } = useChats({ live: authenticated, screen: true });
  const [now, setNow] = useState(() => new Date());
  // The lead beside the chat: open by default on wide screens, then as the
  // person last left it; on phones a sheet, opened on demand per chat.
  const narrow = useMedia("(max-width: 899.98px)");
  const wide = useMedia("(min-width: 1200px)");
  const [panelChoice, setPanelChoice] = useState<boolean | null>(
    readPanelChoice,
  );
  const [sheetFor, setSheetFor] = useState<string | null>(null);

  const refresh = useCallback(() => void refreshChats({ force: true }), []);

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

  // With a list on screen, a failed refresh is a corner card only.
  useEffect(() => {
    if (!error) {
      dismissNotice("chats-load");
      return;
    }
    if (list && error.status !== 403)
      notify({
        id: "chats-load",
        tone: "error",
        title: "Chats didn't refresh",
        message: error.message,
        action: { label: "Try again", run: refresh },
      });
  }, [error, list, refresh]);

  // The waiting clocks move on by themselves.
  useEffect(() => {
    const clock = window.setInterval(() => setNow(new Date()), CLOCK_EVERY_MS);
    return () => window.clearInterval(clock);
  }, []);

  const threads = useMemo(() => list?.threads ?? [], [list]);
  const openThread =
    (opened && threads.find((thread) => sameThread(thread, opened))) ?? null;

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

  if (error && !list) {
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

  const ready = !!list;
  // The role is in the session from the first paint; the desk's own answer
  // only fills in when the session doesn't say.
  const canManage = manages ?? me?.can_manage === true;
  const showScopes = canManage && (list ? list.owners : true);
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
      immersive={!!opened}
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
                canConnect={canManage}
              />
            </>
          ) : (
            <>
              <FiltersSkeleton scopes={canManage} />
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
              onSeen={(at, accountId) => {
                // Read up to the newest message on screen, on every device.
                if (personId && openThread)
                  rememberSeen(personId, openThread, at, accountId);
              }}
            />
          ) : (
            <PickHint />
          )
        }
      />
      {narrow && leadId ? (
        <LeadSheetDialog
          key={leadId}
          leadId={leadId}
          open={sheetFor === leadId}
          onClose={() => setSheetFor(null)}
        />
      ) : null}
    </AcquisitionShell>
  );
}
