/**
 * Reports and feedback that could not go yet (no connection) wait here, on
 * this device only, and leave as soon as the connection is back: on the
 * `online` event and each time the app frame mounts. Each item keeps its own
 * command id, so a send that half-worked before is never counted twice.
 *
 * IndexedDB, one store; anything that goes wrong here fails quietly and the
 * person keeps their words in the sheet instead.
 */

const DB = "sx-outbox";
const STORE = "items";
const MAX_ITEMS = 20;
const MAX_AGE_MS = 7 * 24 * 3600 * 1000;

export type OutboxItem = Readonly<{
  id: string;
  kind: "bug" | "feedback";
  at: number;
  body: unknown;
}>;

function open(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE, { keyPath: "id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

function done<T>(request: IDBRequest<T>): Promise<T | null> {
  return new Promise((resolve) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
  });
}

/** Keep one item to send later; true when it is safely stored. */
export async function keep(item: OutboxItem): Promise<boolean> {
  const db = await open();
  if (!db) return false;
  try {
    const all = await list();
    if (all.length >= MAX_ITEMS) return false;
    const tx = db.transaction(STORE, "readwrite");
    return (await done(tx.objectStore(STORE).put(item))) !== null;
  } finally {
    db.close();
  }
}

/** Keep one request to send later, stamped now. */
export function keepNow(
  kind: OutboxItem["kind"],
  id: string,
  body: unknown,
): Promise<boolean> {
  return keep({ id, kind, at: Date.now(), body });
}

export async function list(): Promise<OutboxItem[]> {
  const db = await open();
  if (!db) return [];
  try {
    const tx = db.transaction(STORE, "readonly");
    const items = (await done(tx.objectStore(STORE).getAll())) as
      | OutboxItem[]
      | null;
    return (items ?? []).sort((a, b) => a.at - b.at);
  } finally {
    db.close();
  }
}

export async function forget(id: string): Promise<void> {
  const db = await open();
  if (!db) return;
  try {
    await done(
      db.transaction(STORE, "readwrite").objectStore(STORE).delete(id),
    );
  } finally {
    db.close();
  }
}

type Sender = (item: OutboxItem) => Promise<"sent" | "retry" | "drop">;

let flushing: Promise<number> | null = null;

/**
 * Send what waits, oldest first. "retry" stops the round (still offline);
 * "drop" forgets an item the server refused for good. Returns how many went.
 */
export function flush(send: Sender, now = Date.now()): Promise<number> {
  flushing ??= (async () => {
    let sent = 0;
    try {
      for (const item of await list()) {
        if (now - item.at > MAX_AGE_MS) {
          await forget(item.id);
          continue;
        }
        const result = await send(item).catch(() => "retry" as const);
        if (result === "retry") break;
        await forget(item.id);
        if (result === "sent") sent += 1;
      }
    } finally {
      flushing = null;
    }
    return sent;
  })();
  return flushing;
}
