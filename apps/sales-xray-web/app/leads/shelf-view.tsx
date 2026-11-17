"use client";

/**
 * Archived and the Bin (owner's M3-A, 17 Nov 2026): the leads taken off Leads,
 * newest first, each with Restore; tick several for "Restore 12" (one bulk
 * job, with Undo). An archived lead opens on Leads as before; a lead in the
 * Bin opens here to read only, with Restore, and says the day it is deleted
 * for good.
 */

import { Archive, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Button, Empty, Skeleton } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import {
  LeadsError,
  readLead,
  type LeadDetail,
  type LeadRow,
} from "./leads-client";
import { failWords, UNDONE_EVENT } from "./manage-bar";
import {
  readShelf,
  restoreShelved,
  shelfNote,
  type Shelf,
} from "./shelf-client";
import styles from "./shelf-view.module.css";

type Loaded = { leads: LeadRow[]; total: number; next: number | null };

export function ShelfView({
  shelf,
  canBin,
  onShelf,
  onOpen,
}: {
  shelf: Shelf;
  /** Owners and admins: the Bin's tab shows. */
  canBin: boolean;
  onShelf: (next: Shelf) => void;
  /** Open an archived lead on Leads. */
  onOpen: (leadId: string) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  const reload = useCallback(() => setRound((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    readShelf(shelf, 0, controller.signal).then(
      (page) =>
        setLoaded({
          leads: page.leads,
          total: page.total,
          next: page.next_offset,
        }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setLoaded({ leads: [], total: 0, next: null });
        notify({
          id: "shelf-failed",
          tone: "error",
          title:
            shelf === "bin" ? "The Bin didn't load" : "Archived didn't load",
          message: failWords(reason, "Try again."),
        });
      },
    );
    return () => controller.abort();
  }, [shelf, round]);

  // An Undo of a restore puts the leads back here: read the list again.
  useEffect(() => {
    window.addEventListener(UNDONE_EVENT, reload);
    return () => window.removeEventListener(UNDONE_EVENT, reload);
  }, [reload]);

  const restore = async (ids: string[]) => {
    if (!ids.length || busy) return;
    setBusy(true);
    try {
      await restoreShelved(shelf, ids);
      setPicked(new Set());
      setReading(null);
      reload();
    } catch (reason) {
      notify({
        id: "shelf-restore-failed",
        tone: "error",
        title: "Couldn't restore",
        message: failWords(reason, "Try again in a moment."),
      });
    } finally {
      setBusy(false);
    }
  };

  const showMore = async () => {
    if (!loaded?.next) return;
    setMore(true);
    try {
      const page = await readShelf(shelf, loaded.next);
      setLoaded((value) =>
        value
          ? {
              leads: [...value.leads, ...page.leads],
              total: page.total,
              next: page.next_offset,
            }
          : value,
      );
    } catch (reason) {
      notify({
        id: "shelf-more-failed",
        tone: "error",
        title: "More leads didn't load",
        message: failWords(reason, "Try again."),
      });
    } finally {
      setMore(false);
    }
  };

  const toggle = (id: string) =>
    setPicked((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const leads = loaded?.leads ?? [];
  const bin = shelf === "bin";
  return (
    <section
      className={styles.shelf}
      aria-label={bin ? "Bin" : "Archived leads"}
    >
      {canBin ? (
        <nav className={styles.tabs} aria-label="Archived or Bin">
          {(["archived", "bin"] as const).map((key) => (
            <button
              key={key}
              type="button"
              className={styles.tab}
              aria-current={shelf === key ? "page" : undefined}
              onClick={() => shelf !== key && onShelf(key)}
            >
              {key === "bin" ? "Bin" : "Archived"}
            </button>
          ))}
        </nav>
      ) : null}
      <p className={styles.lede}>
        {bin
          ? "Leads in the Bin are deleted for good 30 days after they were moved here. Restore one to put it back on Leads."
          : "Archived leads are off every list and count. Restore one to put it back on Leads."}
      </p>
      {!loaded ? (
        <ol className={styles.list} aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <li key={index} className={styles.skeleton}>
              <Skeleton width="55%" height={14} />
              <Skeleton width={72} height={32} />
            </li>
          ))}
        </ol>
      ) : leads.length === 0 ? (
        <Empty
          icon={bin ? Trash2 : Archive}
          title={bin ? "The Bin is empty" : "Nothing archived"}
          text={
            bin
              ? "Leads moved to the Bin wait here for 30 days."
              : "Leads you archive wait here, ready to bring back."
          }
        />
      ) : (
        <ol
          className={styles.list}
          aria-label={bin ? "Leads in the Bin" : "Archived leads"}
        >
          {leads.map((lead) => {
            const name = displayName(lead.name);
            return (
              <li key={lead.lead_id} className={styles.item}>
                <input
                  type="checkbox"
                  className={styles.tick}
                  checked={picked.has(lead.lead_id)}
                  aria-label={`Choose ${name}`}
                  onChange={() => toggle(lead.lead_id)}
                />
                <button
                  type="button"
                  className={styles.row}
                  data-lead-row=""
                  onClick={() =>
                    bin ? setReading(lead.lead_id) : onOpen(lead.lead_id)
                  }
                >
                  <strong>{name}</strong>
                  <small>
                    {[lead.stage_label, lead.owner_name, lead.source_label]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                  <span data-tone={bin ? "warn" : undefined}>
                    {shelfNote(shelf, lead)}
                  </span>
                </button>
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void restore([lead.lead_id])}
                >
                  <RotateCcw size={16} aria-hidden="true" />
                  Restore
                </Button>
              </li>
            );
          })}
        </ol>
      )}
      {loaded?.next ? (
        <Button variant="ghost" onClick={showMore} disabled={more}>
          {more ? "Loading…" : "Show more"}
        </Button>
      ) : null}
      {picked.size ? (
        <div className={styles.bar} role="toolbar" aria-label="Chosen leads">
          <span>{picked.size} chosen</span>
          <Button variant="ghost" onClick={() => setPicked(new Set())}>
            Clear
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void restore([...picked])}
          >
            <RotateCcw size={16} aria-hidden="true" />
            Restore {picked.size}
          </Button>
        </div>
      ) : null}
      <BinnedLead
        key={reading ?? "none"}
        leadId={reading}
        busy={busy}
        onClose={() => setReading(null)}
        onRestore={(id) => void restore([id])}
      />
    </section>
  );
}

/** A lead in the Bin, to read only: who, what it said, and Restore. */
function BinnedLead({
  leadId,
  busy,
  onClose,
  onRestore,
}: {
  leadId: string | null;
  busy: boolean;
  onClose: () => void;
  onRestore: (leadId: string) => void;
}) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    // Keyed by its lead (below): a new lead starts empty.
    if (!leadId) return;
    const controller = new AbortController();
    readLead(leadId, controller.signal).then(setDetail, (reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError")
        return;
      setFailed(
        reason instanceof LeadsError
          ? reason.message
          : "Try again in a moment.",
      );
    });
    return () => controller.abort();
  }, [leadId]);

  const lead = detail?.lead.lead_id === leadId ? detail : null;
  return (
    <Sheet
      open={leadId !== null}
      onClose={onClose}
      title={lead ? displayName(lead.lead.name) : "Lead in the Bin"}
      wide="center"
    >
      <div className={styles.read}>
        {failed ? (
          <p>{failed}</p>
        ) : !lead ? (
          <Skeleton width="70%" height={14} />
        ) : (
          <>
            <p className={styles.warn}>
              {shelfNote("bin", lead.lead)}. Read only: restore it to call,
              change or assign it.
            </p>
            <dl className={styles.facts}>
              {[
                ["Stage", lead.lead.stage_label],
                ["Phone", lead.phone],
                ["Email", lead.email],
                ["Source", lead.lead.source_label],
                ["Owner", lead.lead.owner_name],
                ...lead.fields.map((field) => [field.label, field.value]),
              ]
                .filter((pair): pair is [string, string] => !!pair[1])
                .map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
            </dl>
            {lead.events.some((event) => event.note) ? (
              <ol className={styles.notes} aria-label="Notes">
                {lead.events
                  .filter((event) => event.note)
                  .slice(0, 5)
                  .map((event, index) => (
                    <li key={`${event.at}:${index}`}>{event.note}</li>
                  ))}
              </ol>
            ) : null}
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => onRestore(lead.lead.lead_id)}
            >
              <RotateCcw size={16} aria-hidden="true" />
              Restore to Leads
            </Button>
          </>
        )}
      </div>
    </Sheet>
  );
}
