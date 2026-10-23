"use client";

/**
 * Shared offers: the control accounts' common store. Save the draft as a
 * new version, open the newest version of any shared offer (or restore an
 * older one as the newest), archive, and share every browser-only draft at
 * once. A save on a version someone has replaced is refused; open the newest
 * and save again.
 */
import { Archive, CloudUpload, History, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { newId, normalizeOffer, type Offer, type Studio } from "./offer-model";
import {
  archiveShared,
  historyOf,
  listShared,
  saveShared,
  versionOf,
  type SharedVersion,
} from "./offer-server";
import { withOffer } from "./offer-store";
import styles from "./offers.module.css";

const when = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
};

const newSharedId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : null;

/** The studio with a shared version opened as a working draft (replacing its earlier copy). */
export function openShared(
  studio: Studio,
  shared: SharedVersion,
  asVersion: number = shared.version,
): Studio {
  const opened = normalizeOffer(shared.body);
  const existing = studio.offers.find((o) => o.shared?.id === shared.offerId);
  const clash = studio.offers.some((o) => o.id === opened.id && o !== existing);
  const offer: Offer = {
    ...opened,
    id: existing?.id ?? (clash ? newId("offer") : opened.id),
    shared: { id: shared.offerId, version: asVersion },
  };
  return {
    ...studio,
    offers: existing
      ? studio.offers.map((o) => (o === existing ? offer : o))
      : [...studio.offers, offer],
    activeId: offer.id,
  };
}

export function SharedPanel({
  studio,
  offer,
  commit,
  onClose,
}: {
  studio: Studio;
  offer: Offer | null;
  commit: (next: Studio | ((current: Studio) => Studio)) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<readonly SharedVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<{
    offerId: string;
    versions: readonly SharedVersion[];
  } | null>(null);

  const show = useCallback((result: Awaited<ReturnType<typeof listShared>>) => {
    if (result.ok) {
      setItems(result.data);
      setError(null);
    } else setError(result.message);
  }, []);
  const load = useCallback(async () => show(await listShared()), [show]);

  useEffect(() => {
    let live = true;
    void listShared().then((result) => {
      if (live) show(result);
    });
    return () => {
      live = false;
    };
  }, [show]);

  const linkSaved = (local: Offer, saved: SharedVersion) =>
    commit((current) => {
      const live = current.offers.find((o) => o.id === local.id) ?? local;
      return withOffer(current, {
        ...live,
        shared: { id: saved.offerId, version: saved.version },
      });
    });

  const save = async (local: Offer): Promise<boolean> => {
    const id = local.shared?.id ?? newSharedId();
    if (!id) {
      setError("This browser can't make an id for a shared offer.");
      return false;
    }
    const result = await saveShared(local, id);
    if (!result.ok) {
      setError(
        result.status === 409
          ? `${result.message} (“${local.naming.chosen || local.name}”)`
          : result.message,
      );
      return false;
    }
    linkSaved(local, result.data);
    return true;
  };

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await work();
    } finally {
      setBusy(false);
    }
  };

  const browserOnly = studio.offers.filter((o) => !o.shared);

  return (
    <section className={styles.shared} aria-label="Shared offers">
      <header className={styles.cardHead}>
        <span>
          <h3>Shared offers</h3>
          <p>
            Every save is a new version that other control accounts can open.
            Nothing is overwritten.
          </p>
        </span>
        <button
          type="button"
          className={styles.iconButton}
          onClick={onClose}
          aria-label="Close shared offers"
        >
          <X size={16} />
        </button>
      </header>
      <div className={styles.opTools}>
        {offer ? (
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() =>
              run(async () => {
                if (await save(offer)) {
                  setNote("Saved as a new shared version.");
                  await load();
                }
              })
            }
          >
            <CloudUpload size={14} aria-hidden="true" />
            {offer.shared
              ? `Save version ${offer.shared.version + 1}`
              : "Share this offer"}
          </button>
        ) : null}
        {browserOnly.length ? (
          <button
            type="button"
            className={styles.add}
            disabled={busy}
            onClick={() =>
              run(async () => {
                let done = 0;
                for (const local of browserOnly)
                  if (await save(local)) done += 1;
                setNote(
                  `Shared ${done} of ${browserOnly.length} browser-only offer${browserOnly.length === 1 ? "" : "s"}.`,
                );
                await load();
              })
            }
          >
            Share all {browserOnly.length} browser-only
          </button>
        ) : null}
        <button
          type="button"
          className={styles.add}
          disabled={busy}
          onClick={() => run(load)}
        >
          <RefreshCw size={14} aria-hidden="true" /> Refresh
        </button>
      </div>
      {note ? (
        <p className={styles.message} role="status">
          {note}
        </p>
      ) : null}
      {error ? (
        <p className={styles.message} role="alert">
          {error}
          <button
            type="button"
            onClick={() => setError(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </p>
      ) : null}
      {items === null && !error ? (
        <p className={styles.empty}>Loading shared offers…</p>
      ) : null}
      {items && !items.length ? (
        <p className={styles.empty}>
          Nothing shared yet. Share an offer to let the other control accounts
          open it.
        </p>
      ) : null}
      {items?.length ? (
        <ul className={styles.sharedList}>
          {items.map((item) => {
            const local = studio.offers.find(
              (o) => o.shared?.id === item.offerId,
            );
            const behind = local?.shared && local.shared.version < item.version;
            return (
              <li key={item.offerId}>
                <span className={styles.pickMain}>
                  <strong>{item.name}</strong>
                  <span>
                    Version {item.version}
                    {item.author ? ` · ${item.author}` : ""}
                    {item.createdAt ? ` · ${when(item.createdAt)}` : ""}
                    {local
                      ? behind
                        ? " · your copy is older"
                        : " · open here"
                      : ""}
                  </span>
                </span>
                <span className={styles.rowTools}>
                  <button
                    type="button"
                    className={styles.add}
                    disabled={busy}
                    onClick={() => {
                      commit((current) => openShared(current, item));
                      setNote(`Opened “${item.name}” version ${item.version}.`);
                    }}
                  >
                    Open newest
                  </button>
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-label={`History of ${item.name}`}
                    title="History"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const result = await historyOf(item.offerId);
                        if (result.ok)
                          setHistory({
                            offerId: item.offerId,
                            versions: result.data,
                          });
                        else setError(result.message);
                      })
                    }
                  >
                    <History size={15} />
                  </button>
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-label={`Archive ${item.name}`}
                    title="Archive"
                    disabled={busy}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Archive “${item.name}” for everyone? Its history is kept.`,
                        )
                      )
                        return;
                      void run(async () => {
                        const result = await archiveShared(
                          item.offerId,
                          item.version,
                        );
                        if (!result.ok) {
                          setError(result.message);
                          return;
                        }
                        commit((current) => ({
                          ...current,
                          offers: current.offers.map((o) =>
                            o.shared?.id === item.offerId
                              ? { ...o, shared: null }
                              : o,
                          ),
                        }));
                        setNote(`Archived “${item.name}”.`);
                        await load();
                      });
                    }}
                  >
                    <Archive size={15} />
                  </button>
                </span>
                {history?.offerId === item.offerId ? (
                  <ol className={styles.versions}>
                    {history.versions.map((v) => (
                      <li key={v.version}>
                        <span>
                          Version {v.version}
                          {v.archived ? " (archived)" : ""}
                          {v.author ? ` · ${v.author}` : ""}
                          {v.createdAt ? ` · ${when(v.createdAt)}` : ""}
                        </span>
                        {v.version < item.version ? (
                          <button
                            type="button"
                            className={styles.add}
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                const result = await versionOf(
                                  item.offerId,
                                  v.version,
                                );
                                if (!result.ok || !result.data) {
                                  setError(
                                    result.ok
                                      ? "That version couldn't be read."
                                      : result.message,
                                  );
                                  return;
                                }
                                const old = result.data;
                                // Opened on top of the newest, so saving it restores it.
                                commit((current) =>
                                  openShared(current, old, item.version),
                                );
                                setNote(
                                  `Opened version ${v.version}. Save it to make it the newest.`,
                                );
                              })
                            }
                          >
                            Restore
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
