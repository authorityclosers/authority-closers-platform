"use client";

/**
 * Home opens its leads where you are (owner, 15 Nov 2026: "it redirects to the
 * Leads page, then opens something; that's a bad design"). A tile opens its
 * list in a sheet over Home; a lead, or Call, opens the lead's own sheet over
 * Home, the call started there. Leads is one tap away at the list's foot.
 */

import { ChevronRight, Phone } from "lucide-react";
import Link from "next/link";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

import { displayName } from "../display-name";
import { takeHandedLead } from "../leads/lead-handoff";
import { LeadSheet, type LeadIntent } from "../leads/lead-sheet";
import {
  readLeadAhead,
  readLeads,
  readTasks,
  type Desk,
  type LeadRow,
  type ListMore,
  type ListedTask,
} from "../leads/leads-client";
import { Sheet } from "../ui/sheet";
import styles from "./home-lead.module.css";

type Opener = {
  lead: (leadId: string, intent?: LeadIntent | null) => void;
  list: (title: string, href: string) => void;
};

const HomeLead = createContext<Opener | null>(null);

/** Open a lead or a tile's list on Home; null outside Home (then links go to Leads). */
export function useHomeLead(): Opener | null {
  return useContext(HomeLead);
}

/** The list a Leads address stands for: its side, view and stage. */
function moreFrom(href: string): ListMore | "tasks" {
  const url = new URL(href, "https://x.invalid");
  if (url.searchParams.get("tab") === "tasks") return "tasks";
  const get = (key: string) => url.searchParams.get(key);
  return {
    // No side in a Home address means Inbound (leadsHref adds only cold).
    side: (get("side") ?? "inbound") as ListMore["side"],
    view: get("view") as ListMore["view"],
    step: get("step"),
    when: get("when") as ListMore["when"],
  };
}

export function HomeLeadHost({
  me,
  onChanged,
  children,
}: {
  me: Desk["me"] | null;
  onChanged: () => void;
  children: ReactNode;
}) {
  const [lead, setLead] = useState<{
    id: string;
    intent: LeadIntent | null;
  } | null>(null);
  const [list, setList] = useState<{ title: string; href: string } | null>(
    null,
  );
  const opener = useMemo<Opener>(
    () => ({
      lead: (id, intent = null) => {
        readLeadAhead(id);
        setList(null);
        setLead({ id, intent });
      },
      list: (title, href) => setList({ title, href }),
    }),
    [],
  );
  // Every lead link and tile on Home opens here, whoever drew it: a tap on
  // "/leads?lead=<id>" opens that lead over Home; a tile opens its list. A
  // Call handed over on the same tap (handOverLead) becomes this sheet's call.
  const area = useRef<HTMLDivElement>(null);
  const onClickCapture = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey) return;
    const anchor = (event.target as Element).closest?.("a[href]");
    if (!(anchor instanceof HTMLAnchorElement)) return;
    const url = new URL(anchor.href, location.href);
    if (url.pathname !== "/leads") return;
    if (anchor.hasAttribute("data-card")) {
      event.preventDefault();
      const label =
        anchor.querySelector(":scope > span:nth-child(2)")?.textContent ?? "";
      opener.list(label.trim() || "Leads", url.pathname + url.search);
      return;
    }
    const id = url.searchParams.get("lead");
    if (!id) return;
    event.preventDefault();
    window.setTimeout(() => {
      const handed = takeHandedLead();
      opener.lead(
        id,
        handed?.leadId === id
          ? handed.call
            ? "call"
            : handed.log
              ? "log"
              : null
          : null,
      );
    }, 0);
  };
  // Snappy: the leads on screen are read ahead, so the one tapped opens at
  // once; a finger landing on one starts it at once if it isn't yet.
  useEffect(() => {
    const warm = () => {
      for (const tile of area.current?.querySelectorAll<HTMLAnchorElement>(
        "a[data-card]",
      ) ?? []) {
        const url = new URL(tile.href, location.href);
        if (url.pathname === "/leads")
          void readTileList(url.pathname + url.search).catch(() => undefined);
      }
      const seen = new Set<string>();
      for (const anchor of area.current?.querySelectorAll<HTMLAnchorElement>(
        'a[href*="lead="]',
      ) ?? []) {
        const id = new URL(anchor.href, location.href).searchParams.get("lead");
        if (id && !seen.has(id) && seen.size < 8) {
          seen.add(id);
          readLeadAhead(id);
        }
      }
    };
    const timer = window.setTimeout(warm, 1200);
    return () => window.clearTimeout(timer);
  });
  const onPointerDownCapture = (event: React.PointerEvent<HTMLDivElement>) => {
    const anchor = (event.target as Element).closest?.('a[href*="lead="]');
    if (!(anchor instanceof HTMLAnchorElement)) return;
    const id = new URL(anchor.href, location.href).searchParams.get("lead");
    if (id) readLeadAhead(id);
  };
  return (
    <HomeLead.Provider value={opener}>
      <div
        ref={area}
        style={{ display: "contents" }}
        onClickCapture={onClickCapture}
        onPointerDownCapture={onPointerDownCapture}
      >
        {children}
      </div>
      <TileSheet
        open={list !== null}
        title={list?.title ?? ""}
        href={list?.href ?? null}
        onClose={() => setList(null)}
        onLead={(id, intent) => opener.lead(id, intent)}
      />
      {lead ? (
        <LeadSheet
          framed="sheet"
          leadId={lead.id}
          me={me}
          intent={lead.intent}
          onClose={() => setLead(null)}
          onChanged={onChanged}
        />
      ) : null}
    </HomeLead.Provider>
  );
}

type Row = { id: string; leadId: string | null; name: string; line: string };
type List = { rows: Row[]; total: number };

/** Each tile's list, read once when Home opens and kept a minute, so a tap
 *  shows it at once (owner, 15 Nov 2026: "it should feel snappy"). */
const lists = new Map<string, { at: number; read: Promise<List> }>();

export function readTileList(href: string): Promise<List> {
  const kept = lists.get(href);
  if (kept && Date.now() - kept.at < 60_000) return kept.read;
  const more = moreFrom(href);
  const read: Promise<List> =
    more === "tasks"
      ? readTasks("today").then((page) => ({
          total: page.tasks.length,
          rows: page.tasks.map((task: ListedTask) => ({
            id: task.task_id,
            leadId: task.lead_id,
            name: task.lead_name ? displayName(task.lead_name) : "Your task",
            line: String((task as { title?: string }).title ?? "Task"),
          })),
        }))
      : readLeads({ scope: "mine", more }).then((page) => ({
          total: page.total,
          rows: page.leads.map((row: LeadRow) => ({
            id: row.lead_id,
            leadId: row.lead_id,
            name: displayName(row.name),
            line: [row.stage_label, row.source_label, row.why]
              .filter(Boolean)
              .join(" · "),
          })),
        }));
  read.catch(() => lists.delete(href));
  lists.set(href, { at: Date.now(), read });
  return read;
}

function TileSheet({
  open,
  title,
  href,
  onClose,
  onLead,
}: {
  open: boolean;
  title: string;
  href: string | null;
  onClose: () => void;
  onLead: (leadId: string, intent: LeadIntent | null) => void;
}) {
  // What came back, for which list; set only when a read lands.
  const [got, setGot] = useState<{
    href: string;
    list: List | null;
    failed: boolean;
  } | null>(null);
  useEffect(() => {
    if (!open || !href) return;
    let live = true;
    readTileList(href)
      .then((list) => live && setGot({ href, list, failed: false }))
      .catch(() => live && setGot({ href, list: null, failed: true }));
    return () => {
      live = false;
    };
  }, [open, href]);
  const mine = got && got.href === href ? got : null;
  const rows = mine?.list?.rows ?? null;
  const total = mine?.list?.total ?? null;
  const failed = mine?.failed ?? false;
  const shown = rows?.slice(0, 12) ?? null;
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      description={
        total === null
          ? undefined
          : `${total} ${total === 1 ? "lead" : "leads"}`
      }
      wide="right"
    >
      {failed ? (
        <p className={styles.note}>
          This list didn&apos;t load. Close it and try again.
        </p>
      ) : shown === null ? (
        <ul className={styles.rows} aria-busy="true">
          {[0, 1, 2, 3].map((n) => (
            <li key={n} className={styles.wait} />
          ))}
        </ul>
      ) : shown.length === 0 ? (
        <p className={styles.note}>Nothing here right now.</p>
      ) : (
        <ul className={styles.rows}>
          {shown.map((row, n) => (
            <li key={row.id} style={{ animationDelay: `${60 + n * 35}ms` }}>
              <button
                type="button"
                className={styles.row}
                disabled={!row.leadId}
                onClick={() => row.leadId && onLead(row.leadId, null)}
              >
                <span className={styles.face} aria-hidden="true">
                  {row.name.slice(0, 1)}
                </span>
                <span className={styles.words}>
                  <b>{row.name}</b>
                  <small>{row.line}</small>
                </span>
              </button>
              {row.leadId ? (
                <button
                  type="button"
                  className={styles.call}
                  aria-label={`Call ${row.name}`}
                  onClick={() => row.leadId && onLead(row.leadId, "call")}
                >
                  <Phone size={18} aria-hidden="true" />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {href ? (
        <Link className={styles.all} href={href} onClick={onClose}>
          See all in Leads
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      ) : null}
    </Sheet>
  );
}
