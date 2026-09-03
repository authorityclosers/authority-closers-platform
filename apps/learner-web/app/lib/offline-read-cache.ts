/**
 * Bounded, encrypted display recovery for learner GET responses.
 *
 * This cache is deliberately separate from the service worker CacheStorage
 * cache. It is a noncanonical browser convenience only: the server remains
 * authoritative for identity, access, progress, evidence, and mutations.
 *
 * AES-GCM and a non-extractable CryptoKey protect casual at-rest inspection
 * of the browser database. They do not protect data from XSS or another
 * same-origin script compromise, because such code can use the live key and
 * call this module while the page is running.
 */

export const OFFLINE_READ_CACHE_VERSION = 1 as const;
export const OFFLINE_READ_CACHE_MAX_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
export const OFFLINE_READ_CACHE_MAX_ENTRIES = 32;
export const OFFLINE_READ_CACHE_MAX_ENTRY_BYTES = 512 * 1024;
export const OFFLINE_READ_CACHE_MAX_TOTAL_BYTES = 4 * 1024 * 1024;

const DATABASE_NAME = "ac-learner-offline-read-v1";
const DATABASE_VERSION = 1;
const RECORDS_STORE = "records";
const KEY_STORE = "key";
const KEY_RECORD_ID = "aes-gcm-256-v1";
const ACTIVE_OWNER_STORAGE_KEY = "ac.learner.offline.active-owner.v1";
const PUBLIC_OWNER_SCOPE = "public";
const AES_GCM_KEY_BYTES = 32;
const AES_GCM_IV_BYTES = 12;
const OWNER_HASH_PREFIX = "ac-owner-v1:";
const CACHE_KEY_PREFIX = "ac-cache-key-v1:";

export type OfflineReadCacheResult =
  | { ok: true }
  | { ok: false; reason: "unavailable" | "failed" };

export type OfflineReadCacheEntry<T = unknown> = {
  data: T;
  savedAt: number;
};

export type OfflineReadCache = {
  get(path: string): Promise<OfflineReadCacheEntry | null>;
  put(path: string, data: unknown): Promise<OfflineReadCacheResult>;
  activateOwner(
    personId: string,
    tenantId?: string | null,
  ): Promise<OfflineReadCacheResult>;
  purge(): Promise<OfflineReadCacheResult>;
};

export type OfflineReadPolicyKind =
  | "onboarding"
  | "program-list"
  | "program-detail"
  | "learning";

export type OfflineReadPolicy = {
  kind: OfflineReadPolicyKind;
  requiresOwner: boolean;
  allowsPublicFallback: boolean;
};

/**
 * The only API paths eligible for encrypted display recovery.
 *
 * The returned policy is also the cache's defense-in-depth boundary. A
 * caller cannot opt a context, activity, draft, evidence, certificate,
 * authentication, mutation, or ambiguous path into this cache accidentally.
 */
export function getOfflineReadPolicy(
  path: string,
  method = "GET",
): OfflineReadPolicy | null {
  if (method.toUpperCase() !== "GET") return null;
  if (!path.startsWith("/v1/") || path.includes("#") || path.includes("\\")) {
    return null;
  }
  if (path.includes("//")) return null;

  const queryIndex = path.indexOf("?");
  const hasQuery = queryIndex !== -1;
  const pathname = queryIndex === -1 ? path : path.slice(0, queryIndex);
  const query = queryIndex === -1 ? "" : path.slice(queryIndex + 1);
  if (query.includes("?")) return null;

  if (pathname === "/v1/onboarding") {
    return !hasQuery
      ? {
          kind: "onboarding",
          requiresOwner: true,
          allowsPublicFallback: false,
        }
      : null;
  }

  if (pathname === "/v1/programs") {
    // Keep this in lock-step with the bounded listPrograms API contract. The
    // canonical decimal spelling prevents duplicate cache keys for aliases.
    const match = /^limit=([1-9]\d{0,2})$/.exec(query);
    if (!match) return null;
    const limit = Number(match[1]);
    return limit >= 1 && limit <= 100
      ? {
          kind: "program-list",
          requiresOwner: false,
          allowsPublicFallback: true,
        }
      : null;
  }

  if (pathname.startsWith("/v1/programs/")) {
    return !hasQuery && hasSingleEncodedSegment(pathname, "/v1/programs/")
      ? {
          kind: "program-detail",
          requiresOwner: false,
          allowsPublicFallback: true,
        }
      : null;
  }

  if (pathname.startsWith("/v1/learning/")) {
    if (!hasSingleEncodedSegment(pathname, "/v1/learning/")) return null;
    if (!hasQuery) {
      return {
        kind: "learning",
        requiresOwner: true,
        allowsPublicFallback: false,
      };
    }

    const params = new URLSearchParams(query);
    const keys = [...params.keys()];
    if (
      params.size !== 2 ||
      keys.length !== 2 ||
      new Set(keys).size !== 2 ||
      !keys.includes("enrollment_id") ||
      !keys.includes("program_version_id")
    ) {
      return null;
    }
    if (
      !isSafeQueryValue(params.get("enrollment_id")) ||
      !isSafeQueryValue(params.get("program_version_id"))
    ) {
      return null;
    }
    return {
      kind: "learning",
      requiresOwner: true,
      allowsPublicFallback: false,
    };
  }

  return null;
}

export function isOfflineReadPath(path: string, method = "GET"): boolean {
  return getOfflineReadPolicy(path, method) !== null;
}

function hasSingleEncodedSegment(pathname: string, prefix: string): boolean {
  const segment = pathname.slice(prefix.length);
  if (!segment || segment.includes("/")) return false;

  let decoded: string;
  try {
    decoded = decodeURIComponent(segment);
  } catch {
    return false;
  }

  if (
    !decoded ||
    decoded === "." ||
    decoded === ".." ||
    decoded.includes("/") ||
    decoded.includes("\\") ||
    decoded.includes("%") ||
    /[\u0000-\u001f\u007f]/.test(decoded)
  ) {
    return false;
  }

  return encodeURIComponent(decoded) === segment;
}

function isSafeQueryValue(value: string | null): value is string {
  return Boolean(
    value &&
      value.length <= 200 &&
      !/[\u0000-\u001f\u007f/\\]/.test(value) &&
      value.trim() === value,
  );
}

export type OfflineReadCacheRecord = {
  cacheKey: string;
  ownerHash: string | null;
  version: typeof OFFLINE_READ_CACHE_VERSION;
  savedAt: number;
  expiresAt: number;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
};

type OfflineReadCacheKeyRecord = {
  id: string;
  key: CryptoKey;
};

/**
 * Storage seam used by the browser IndexedDB implementation and focused
 * tests. Implementations must persist only OfflineReadCacheRecord fields;
 * raw paths and response bodies must never be added to a record.
 */
export interface OfflineReadCacheStore {
  read(cacheKey: string): Promise<OfflineReadCacheRecord | null>;
  list(): Promise<OfflineReadCacheRecord[]>;
  write(record: OfflineReadCacheRecord): Promise<void>;
  remove(cacheKey: string): Promise<void>;
  readKey(): Promise<CryptoKey | null>;
  writeKey(key: CryptoKey): Promise<void>;
  clear(): Promise<void>;
}

export type CreateOfflineReadCacheOptions = {
  crypto?: Crypto | null;
  indexedDB?: IDBFactory | null;
  sessionStorage?: Storage | null;
  now?: () => number;
  store?: OfflineReadCacheStore | null;
};

type ActiveOwner = {
  ownerHash: string;
  sessionKey: string;
};

function runtimeCrypto(): Crypto | null {
  return typeof globalThis.crypto === "undefined" ? null : globalThis.crypto;
}

function runtimeIndexedDb(): IDBFactory | null {
  return typeof window === "undefined" ||
    typeof globalThis.indexedDB === "undefined"
    ? null
    : globalThis.indexedDB;
}

function runtimeSessionStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function getUtf8(value: string): Uint8Array<ArrayBuffer> {
  const encoded = new TextEncoder().encode(value);
  const copy = new Uint8Array(new ArrayBuffer(encoded.byteLength));
  copy.set(encoded);
  return copy;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

async function sha256Hex(crypto: Crypto, value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", getUtf8(value));
  return bytesToHex(new Uint8Array(digest));
}

function additionalDataFor(
  version: typeof OFFLINE_READ_CACHE_VERSION,
  cacheKey: string,
  ownerHash: string | null,
  savedAt: number,
  expiresAt: number,
): Uint8Array<ArrayBuffer> {
  return getUtf8(
    `${version}\u0000${cacheKey}\u0000${ownerHash ?? PUBLIC_OWNER_SCOPE}\u0000${savedAt}\u0000${expiresAt}`,
  );
}

function resultFailure(error: unknown): OfflineReadCacheResult {
  return {
    ok: false,
    reason: error instanceof Error ? "failed" : "unavailable",
  };
}

function validStoredRecord(record: OfflineReadCacheRecord): boolean {
  return (
    record.version === OFFLINE_READ_CACHE_VERSION &&
    typeof record.cacheKey === "string" &&
    /^[0-9a-f]{64}$/.test(record.cacheKey) &&
    (record.ownerHash === null || /^[0-9a-f]{64}$/.test(record.ownerHash)) &&
    Number.isSafeInteger(record.savedAt) &&
    Number.isSafeInteger(record.expiresAt) &&
    record.expiresAt > record.savedAt &&
    record.expiresAt - record.savedAt === OFFLINE_READ_CACHE_MAX_RETENTION_MS &&
    record.iv instanceof ArrayBuffer &&
    record.iv.byteLength === AES_GCM_IV_BYTES &&
    record.ciphertext instanceof ArrayBuffer &&
    record.ciphertext.byteLength > 0 &&
    record.ciphertext.byteLength <= OFFLINE_READ_CACHE_MAX_ENTRY_BYTES + 32
  );
}

function activeOwnerValue(owner: ActiveOwner): string {
  return `v1:${owner.ownerHash}:${owner.sessionKey}`;
}

function parseActiveOwner(value: string | null): ActiveOwner | null {
  if (!value) return null;
  const match = /^v1:([0-9a-f]{64}):([A-Za-z0-9_-]{22})$/.exec(value);
  return match ? { ownerHash: match[1], sessionKey: match[2] } : null;
}

class IndexedDbOfflineReadCacheStore implements OfflineReadCacheStore {
  private databasePromise: Promise<IDBDatabase> | null = null;

  constructor(private readonly factory: IDBFactory) {}

  private openDatabase(): Promise<IDBDatabase> {
    if (this.databasePromise) return this.databasePromise;
    this.databasePromise = new Promise<IDBDatabase>((resolve, reject) => {
      let request: IDBOpenDBRequest;
      try {
        request = this.factory.open(DATABASE_NAME, DATABASE_VERSION);
      } catch (error) {
        reject(error);
        return;
      }
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(RECORDS_STORE)) {
          database.createObjectStore(RECORDS_STORE, { keyPath: "cacheKey" });
        }
        if (!database.objectStoreNames.contains(KEY_STORE)) {
          database.createObjectStore(KEY_STORE, { keyPath: "id" });
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
      request.onerror = () =>
        reject(request.error ?? new Error("IndexedDB open failed."));
      request.onblocked = () =>
        reject(new Error("IndexedDB open was blocked."));
    }).catch((error) => {
      this.databasePromise = null;
      throw error;
    });
    return this.databasePromise;
  }

  private request<T>(
    storeName: string,
    mode: IDBTransactionMode,
    operation: (store: IDBObjectStore) => IDBRequest<T>,
  ): Promise<T> {
    return this.openDatabase().then(
      (database) =>
        new Promise<T>((resolve, reject) => {
          let settled = false;
          let result!: T;
          let transaction: IDBTransaction;
          try {
            transaction = database.transaction(storeName, mode);
            const request = operation(transaction.objectStore(storeName));
            request.onsuccess = () => {
              result = request.result;
            };
            request.onerror = () => {
              if (!settled) {
                settled = true;
                reject(request.error ?? new Error("IndexedDB request failed."));
              }
            };
            transaction.oncomplete = () => {
              if (!settled) {
                settled = true;
                resolve(result);
              }
            };
            transaction.onerror = () => {
              if (!settled) {
                settled = true;
                reject(
                  transaction.error ??
                    new Error("IndexedDB transaction failed."),
                );
              }
            };
            transaction.onabort = () => {
              if (!settled) {
                settled = true;
                reject(new Error("IndexedDB transaction aborted."));
              }
            };
          } catch (error) {
            if (!settled) {
              settled = true;
              reject(error);
            }
          }
        }),
    );
  }

  read(cacheKey: string): Promise<OfflineReadCacheRecord | null> {
    return this.request<OfflineReadCacheRecord | undefined>(
      RECORDS_STORE,
      "readonly",
      (store) => store.get(cacheKey),
    ).then((record) => record ?? null);
  }

  list(): Promise<OfflineReadCacheRecord[]> {
    return this.request<OfflineReadCacheRecord[]>(
      RECORDS_STORE,
      "readonly",
      (store) => store.getAll(),
    );
  }

  write(record: OfflineReadCacheRecord): Promise<void> {
    return this.request(RECORDS_STORE, "readwrite", (store) =>
      store.put(record),
    ).then(() => undefined);
  }

  remove(cacheKey: string): Promise<void> {
    return this.request(RECORDS_STORE, "readwrite", (store) =>
      store.delete(cacheKey),
    ).then(() => undefined);
  }

  readKey(): Promise<CryptoKey | null> {
    return this.request<OfflineReadCacheKeyRecord | undefined>(
      KEY_STORE,
      "readonly",
      (store) => store.get(KEY_RECORD_ID),
    ).then((record) => record?.key ?? null);
  }

  writeKey(key: CryptoKey): Promise<void> {
    return this.request(KEY_STORE, "readwrite", (store) =>
      store.put({ id: KEY_RECORD_ID, key } satisfies OfflineReadCacheKeyRecord),
    ).then(() => undefined);
  }

  clear(): Promise<void> {
    return this.openDatabase().then(
      (database) =>
        new Promise<void>((resolve, reject) => {
          let settled = false;
          try {
            const transaction = database.transaction(
              [RECORDS_STORE, KEY_STORE],
              "readwrite",
            );
            transaction.objectStore(RECORDS_STORE).clear();
            transaction.objectStore(KEY_STORE).clear();
            transaction.oncomplete = () => {
              if (!settled) {
                settled = true;
                resolve();
              }
            };
            transaction.onerror = () => {
              if (!settled) {
                settled = true;
                reject(
                  transaction.error ?? new Error("IndexedDB purge failed."),
                );
              }
            };
            transaction.onabort = () => {
              if (!settled) {
                settled = true;
                reject(new Error("IndexedDB purge was aborted."));
              }
            };
          } catch (error) {
            if (!settled) {
              settled = true;
              reject(error);
            }
          }
        }),
    );
  }
}

export function createOfflineReadCache(
  options: CreateOfflineReadCacheOptions = {},
): OfflineReadCache {
  const crypto =
    options.crypto === undefined ? runtimeCrypto() : options.crypto;
  const sessionStorage =
    options.sessionStorage === undefined
      ? runtimeSessionStorage()
      : options.sessionStorage;
  const store =
    options.store === undefined
      ? (() => {
          const factory =
            options.indexedDB === undefined
              ? runtimeIndexedDb()
              : options.indexedDB;
          return factory ? new IndexedDbOfflineReadCacheStore(factory) : null;
        })()
      : options.store;
  const now = options.now ?? (() => Date.now());
  let memoryOwner: ActiveOwner | null = null;
  let cryptoKeyPromise: Promise<CryptoKey | null> | null = null;

  function readOwner(): ActiveOwner | null {
    if (sessionStorage) {
      try {
        const owner = parseActiveOwner(
          sessionStorage.getItem(ACTIVE_OWNER_STORAGE_KEY),
        );
        if (owner) {
          memoryOwner = owner;
          return owner;
        }
      } catch {
        // The in-memory session owner remains a safe same-page fallback.
      }
    }
    return memoryOwner;
  }

  function writeOwner(owner: ActiveOwner): boolean {
    memoryOwner = owner;
    if (!sessionStorage) return true;
    try {
      sessionStorage.setItem(ACTIVE_OWNER_STORAGE_KEY, activeOwnerValue(owner));
      return true;
    } catch {
      return false;
    }
  }

  function clearOwner(): boolean {
    memoryOwner = null;
    if (!sessionStorage) return true;
    try {
      sessionStorage.removeItem(ACTIVE_OWNER_STORAGE_KEY);
      return true;
    } catch {
      return false;
    }
  }

  async function getCryptoKey(): Promise<CryptoKey | null> {
    if (!crypto?.subtle || !store) return null;
    if (cryptoKeyPromise) return cryptoKeyPromise;
    cryptoKeyPromise = (async () => {
      const existing = await store.readKey();
      if (existing && existing.extractable === false) return existing;
      const generated = (await crypto.subtle.generateKey(
        { name: "AES-GCM", length: AES_GCM_KEY_BYTES * 8 },
        false,
        ["encrypt", "decrypt"],
      )) as CryptoKey;
      if (generated.extractable !== false) {
        throw new Error("Offline cache key must be non-extractable.");
      }
      await store.writeKey(generated);
      return generated;
    })()
      .catch(() => null)
      .then((key) => {
        if (!key) cryptoKeyPromise = null;
        return key;
      });
    return cryptoKeyPromise;
  }

  async function cacheKeyFor(
    path: string,
    ownerHash: string | null,
    sessionKey: string | null,
  ): Promise<string> {
    if (!crypto) throw new Error("Web Crypto is unavailable.");
    const scope = ownerHash
      ? `owner:${ownerHash}:session:${sessionKey ?? ""}`
      : PUBLIC_OWNER_SCOPE;
    return sha256Hex(crypto, `${CACHE_KEY_PREFIX}${scope}\u0000${path}`);
  }

  async function removeBestEffort(cacheKey: string): Promise<void> {
    try {
      await store?.remove(cacheKey);
    } catch {
      // Corrupt or expired entries are disposable. A later purge can retry.
    }
  }

  async function readCandidate(
    path: string,
    ownerHash: string | null,
    sessionKey: string | null,
    key: CryptoKey,
  ): Promise<OfflineReadCacheEntry | null> {
    if (!crypto || !store) return null;
    const cacheKey = await cacheKeyFor(path, ownerHash, sessionKey);
    let record: OfflineReadCacheRecord | null;
    try {
      record = await store.read(cacheKey);
    } catch {
      return null;
    }
    if (!record) return null;
    if (
      !validStoredRecord(record) ||
      record.cacheKey !== cacheKey ||
      record.ownerHash !== ownerHash
    ) {
      await removeBestEffort(cacheKey);
      return null;
    }
    const currentTime = now();
    if (!Number.isFinite(currentTime) || record.expiresAt <= currentTime) {
      await removeBestEffort(cacheKey);
      return null;
    }

    try {
      const additionalData = additionalDataFor(
        record.version,
        record.cacheKey,
        record.ownerHash,
        record.savedAt,
        record.expiresAt,
      );
      const plaintext = await crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: record.iv,
          additionalData,
        },
        key,
        record.ciphertext,
      );
      const decoded = new TextDecoder().decode(plaintext);
      return { data: JSON.parse(decoded) as unknown, savedAt: record.savedAt };
    } catch {
      await removeBestEffort(cacheKey);
      return null;
    }
  }

  async function get(path: string): Promise<OfflineReadCacheEntry | null> {
    const policy = getOfflineReadPolicy(path);
    if (!policy || !store || !crypto) return null;

    const owner = readOwner();
    if (policy.requiresOwner && !owner) return null;

    const key = await getCryptoKey();
    if (!key) return null;

    const candidates = policy.requiresOwner
      ? [owner as ActiveOwner]
      : owner
        ? [owner, null]
        : [null];
    for (const candidate of candidates) {
      const result = await readCandidate(
        path,
        candidate ? candidate.ownerHash : null,
        candidate ? candidate.sessionKey : null,
        key,
      );
      if (result) return result;
    }
    return null;
  }

  async function put(
    path: string,
    data: unknown,
  ): Promise<OfflineReadCacheResult> {
    const policy = getOfflineReadPolicy(path);
    if (!policy || !store || !crypto)
      return { ok: false, reason: "unavailable" };

    const owner = readOwner();
    if (policy.requiresOwner && !owner) {
      return { ok: false, reason: "unavailable" };
    }

    let serialized: string;
    try {
      serialized = JSON.stringify(data);
    } catch (error) {
      return resultFailure(error);
    }
    if (serialized === undefined) return { ok: false, reason: "failed" };

    const plaintext = getUtf8(serialized);
    if (plaintext.byteLength > OFFLINE_READ_CACHE_MAX_ENTRY_BYTES) {
      return { ok: false, reason: "failed" };
    }
    const ownerHash = owner?.ownerHash ?? null;
    const sessionKey = owner?.sessionKey ?? null;
    const key = await getCryptoKey();
    if (!key) return { ok: false, reason: "unavailable" };

    const savedAt = now();
    if (!Number.isSafeInteger(savedAt)) return { ok: false, reason: "failed" };

    try {
      const cacheKey = await cacheKeyFor(path, ownerHash, sessionKey);
      const iv: Uint8Array<ArrayBuffer> = new Uint8Array(
        new ArrayBuffer(AES_GCM_IV_BYTES),
      );
      crypto.getRandomValues(iv);
      const expiresAt = savedAt + OFFLINE_READ_CACHE_MAX_RETENTION_MS;
      const additionalData = additionalDataFor(
        OFFLINE_READ_CACHE_VERSION,
        cacheKey,
        ownerHash,
        savedAt,
        expiresAt,
      );
      const ciphertext = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv, additionalData },
        key,
        plaintext,
      );
      const record: OfflineReadCacheRecord = {
        cacheKey,
        ownerHash,
        version: OFFLINE_READ_CACHE_VERSION,
        savedAt,
        expiresAt,
        iv: new Uint8Array(iv).buffer,
        ciphertext,
      };

      const existing = await store.list();
      const live = existing.filter(
        (candidate) =>
          validStoredRecord(candidate) &&
          candidate.expiresAt > savedAt &&
          candidate.cacheKey !== cacheKey,
      );
      const keep = [record, ...live].sort(
        (left, right) => right.savedAt - left.savedAt,
      );
      let totalBytes = 0;
      const retained: OfflineReadCacheRecord[] = [];
      for (const candidate of keep) {
        const candidateBytes = candidate.ciphertext.byteLength;
        if (
          retained.length >= OFFLINE_READ_CACHE_MAX_ENTRIES ||
          totalBytes + candidateBytes > OFFLINE_READ_CACHE_MAX_TOTAL_BYTES
        ) {
          continue;
        }
        retained.push(candidate);
        totalBytes += candidateBytes;
      }
      const retainedKeys = new Set(
        retained.map((candidate) => candidate.cacheKey),
      );
      for (const candidate of existing) {
        if (!retainedKeys.has(candidate.cacheKey)) {
          await store.remove(candidate.cacheKey);
        }
      }
      if (!retainedKeys.has(record.cacheKey)) {
        return { ok: false, reason: "failed" };
      }
      await store.write(record);
      return { ok: true };
    } catch (error) {
      return resultFailure(error);
    }
  }

  async function activateOwner(
    personId: string,
    tenantId: string | null = null,
  ): Promise<OfflineReadCacheResult> {
    if (!personId || !store || !crypto) {
      return { ok: false, reason: "unavailable" };
    }

    let ownerHash: string;
    try {
      ownerHash = await sha256Hex(
        crypto,
        `${OWNER_HASH_PREFIX}${personId}\u0000tenant:${tenantId ?? "none"}`,
      );
    } catch (error) {
      return resultFailure(error);
    }

    const previous = readOwner();
    if (previous && previous.ownerHash !== ownerHash) {
      try {
        await store.clear();
      } catch (error) {
        // Do not leave the old owner active if the private purge failed.
        clearOwner();
        return resultFailure(error);
      }
      cryptoKeyPromise = null;
    }

    const sessionKey =
      previous && previous.ownerHash === ownerHash
        ? previous.sessionKey
        : await createSessionKey(crypto);
    if (!sessionKey) {
      clearOwner();
      return { ok: false, reason: "unavailable" };
    }
    if (!writeOwner({ ownerHash, sessionKey })) {
      // The in-memory owner is safe for the current page; returning a failure
      // keeps callers honest about persistence across a reload.
      return { ok: false, reason: "unavailable" };
    }
    return { ok: true };
  }

  async function purge(): Promise<OfflineReadCacheResult> {
    let cacheCleared = false;
    try {
      if (store) {
        await store.clear();
        cacheCleared = true;
        cryptoKeyPromise = null;
      }
    } catch {
      // Keep going so the session owner is not accidentally retained.
    }
    const ownerCleared = clearOwner();
    return cacheCleared && ownerCleared
      ? { ok: true }
      : { ok: false, reason: "unavailable" };
  }

  return { get, put, activateOwner, purge };
}

async function createSessionKey(crypto: Crypto): Promise<string | null> {
  try {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return bytesToBase64Url(bytes);
  } catch {
    return null;
  }
}

let defaultOfflineReadCache: OfflineReadCache | null = null;

export function getDefaultOfflineReadCache(): OfflineReadCache {
  defaultOfflineReadCache ??= createOfflineReadCache();
  return defaultOfflineReadCache;
}

export type OfflineReadMetadata = {
  readonly isOfflineCopy: true;
  readonly savedAt: number;
};

export function offlineReadTimestamp(savedAt: number): string {
  const date = new Date(savedAt);
  return Number.isNaN(date.getTime()) ? "an unknown time" : date.toISOString();
}

export function offlineReadNotice(metadata: OfflineReadMetadata): string {
  return `Offline copy · last synced ${offlineReadTimestamp(metadata.savedAt)}. Reconnect to enable live actions.`;
}

const offlineMetadata = new WeakMap<object, OfflineReadMetadata>();
const OFFLINE_METADATA = Symbol("authority-closers-offline-read-metadata");

/**
 * Marks a decoded JSON object without adding enumerable fields or changing
 * its response wire shape. WeakMap storage handles frozen/non-extensible
 * response objects; the symbol is a convenient non-enumerable accessor for
 * code that needs to inspect the object directly.
 */
export function markOfflineRead<T>(value: T, savedAt: number): T {
  if (!Number.isSafeInteger(savedAt)) return value;

  // API response helpers often immediately project a collection (for example,
  // `programs.items`) or spread several responses into a route model. Mark the
  // complete decoded JSON tree so provenance survives those non-authoritative
  // projections without adding enumerable fields to the wire shape.
  const seen = new WeakSet<object>();
  const mark = (candidate: unknown): void => {
    if (
      (typeof candidate !== "object" || candidate === null) &&
      typeof candidate !== "function"
    ) {
      return;
    }
    const objectValue = candidate as object;
    if (seen.has(objectValue)) return;
    seen.add(objectValue);
    const metadata: OfflineReadMetadata = Object.freeze({
      isOfflineCopy: true,
      savedAt,
    });
    offlineMetadata.set(objectValue, metadata);
    try {
      Object.defineProperty(objectValue, OFFLINE_METADATA, {
        configurable: true,
        enumerable: false,
        value: metadata,
        writable: false,
      });
    } catch {
      // WeakMap metadata remains available for frozen/non-extensible values.
    }
    try {
      if (Array.isArray(candidate)) {
        for (const child of candidate) mark(child);
        return;
      }
      for (const child of Object.values(candidate)) mark(child);
    } catch {
      // The decoded API payload is plain JSON. If a caller supplies a hostile
      // proxy/getter, preserve the root marker and stop traversing safely.
    }
  };
  mark(value);
  return value;
}

export function getOfflineReadMetadata(
  value: unknown,
): OfflineReadMetadata | null {
  if (
    (typeof value !== "object" || value === null) &&
    typeof value !== "function"
  ) {
    return null;
  }
  return offlineMetadata.get(value as object) ?? null;
}

/**
 * Returns the oldest cached snapshot represented by a route model. Showing
 * the oldest timestamp keeps a mixed live/offline response honest: the notice
 * cannot imply that every displayed section was fetched at the same time.
 */
export function getEarliestOfflineReadMetadata(
  ...values: unknown[]
): OfflineReadMetadata | null {
  let earliest: OfflineReadMetadata | null = null;
  for (const value of values) {
    const metadata = getOfflineReadMetadata(value);
    if (metadata && (!earliest || metadata.savedAt < earliest.savedAt)) {
      earliest = metadata;
    }
  }
  return earliest;
}

export function isOfflineReadCopy(value: unknown): boolean {
  return getOfflineReadMetadata(value)?.isOfflineCopy === true;
}
