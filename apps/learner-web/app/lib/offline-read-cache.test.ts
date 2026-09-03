import { describe, expect, it, vi } from "vitest";

import {
  createOfflineReadCache,
  getEarliestOfflineReadMetadata,
  getOfflineReadMetadata,
  getOfflineReadPolicy,
  isOfflineReadPath,
  markOfflineRead,
  OFFLINE_READ_CACHE_MAX_ENTRIES,
  OFFLINE_READ_CACHE_MAX_RETENTION_MS,
  type OfflineReadCacheRecord,
  type OfflineReadCacheStore,
} from "./offline-read-cache";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  };
}

class MemoryOfflineReadStore implements OfflineReadCacheStore {
  readonly records = new Map<string, OfflineReadCacheRecord>();
  private key: CryptoKey | null = null;

  async read(cacheKey: string) {
    return this.records.get(cacheKey) ?? null;
  }

  async list() {
    return [...this.records.values()];
  }

  async write(record: OfflineReadCacheRecord) {
    this.records.set(record.cacheKey, record);
  }

  async remove(cacheKey: string) {
    this.records.delete(cacheKey);
  }

  async readKey() {
    return this.key;
  }

  async writeKey(key: CryptoKey) {
    this.key = key;
  }

  async clear() {
    this.records.clear();
    this.key = null;
  }
}

function makeCache(now: () => number = () => Date.now()) {
  const store = new MemoryOfflineReadStore();
  const sessionStorage = memoryStorage();
  const crypto = globalThis.crypto;
  if (!crypto?.subtle) {
    throw new Error("The focused cache tests require Web Crypto.");
  }
  const cache = createOfflineReadCache({
    crypto,
    now,
    sessionStorage,
    store,
  });
  return { cache, crypto, sessionStorage, store };
}

describe("offline learner read policy", () => {
  it("allows only the bounded read paths", () => {
    expect(getOfflineReadPolicy("/v1/onboarding")).toMatchObject({
      kind: "onboarding",
    });
    expect(getOfflineReadPolicy("/v1/programs?limit=50")).toMatchObject({
      kind: "program-list",
    });
    expect(getOfflineReadPolicy("/v1/programs/free-course")).toMatchObject({
      kind: "program-detail",
    });
    expect(
      getOfflineReadPolicy(
        "/v1/learning/program-1?enrollment_id=enrollment-1&program_version_id=version-1",
      ),
    ).toMatchObject({ kind: "learning" });

    for (const path of [
      "/v1/context",
      "/v1/me",
      "/v1/activities/activity-1",
      "/v1/activities/activity-1/draft",
      "/v1/activities/activity-1/evidence",
      "/v1/certificates/certificate-1",
      "/v1/auth/password/login",
      "/v1/programs?limit=0",
      "/v1/programs?limit=101",
      "/v1/programs?limit=50&limit=50",
      "/v1/programs/free-course?extra=1",
      "/v1/programs/free-course/child",
      "/v1/programs/%2F",
      "/v1/programs/%E0%A4%A",
      "/v1/learning/program-1?enrollment_id=one",
      "/v1/learning/program-1?enrollment_id=one&program_version_id=two&extra=three",
      "/v1/learning/program-1?enrollment_id=one&program_version_id=two&program_version_id=three",
      "/v1/me?unexpected=true",
      "/v1/me?",
      "/v1//me",
    ]) {
      expect(isOfflineReadPath(path), path).toBe(false);
    }
    expect(isOfflineReadPath("/v1/me", "POST")).toBe(false);
  });
});

describe("encrypted offline learner reads", () => {
  it("stores ciphertext-only records and a non-extractable AES-GCM key", async () => {
    const { cache, store } = makeCache(() => 1_000);
    await expect(cache.activateOwner("person-1")).resolves.toMatchObject({
      ok: true,
    });
    const body = {
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Suyash",
      completed_count: 3,
    };

    await expect(cache.put("/v1/onboarding", body)).resolves.toMatchObject({
      ok: true,
    });
    const record = [...store.records.values()][0];
    expect(record).toBeDefined();
    expect(JSON.stringify(record)).not.toContain("learner@example.com");
    expect(JSON.stringify(record)).not.toContain("Suyash");
    expect(JSON.stringify(record)).not.toContain("/v1/onboarding");
    expect(record?.ciphertext).toBeInstanceOf(ArrayBuffer);
    expect(record?.iv).toBeInstanceOf(ArrayBuffer);
    expect(await store.readKey()).toMatchObject({ extractable: false });

    await expect(cache.get("/v1/onboarding")).resolves.toEqual({
      data: body,
      savedAt: 1_000,
    });
  });

  it("keeps public catalog reads available without an owner but requires one for private reads", async () => {
    const { cache } = makeCache(() => 2_000);
    const programs = { items: [], next_cursor: null };

    await expect(cache.put("/v1/programs?limit=50", programs)).resolves.toEqual(
      {
        ok: true,
      },
    );
    await expect(cache.get("/v1/programs?limit=50")).resolves.toEqual({
      data: programs,
      savedAt: 2_000,
    });
    await expect(cache.get("/v1/me")).resolves.toBeNull();
  });

  it("purges expired and tampered records instead of returning them", async () => {
    let currentTime = 3_000;
    const { cache, store } = makeCache(() => currentTime);
    await cache.activateOwner("person-1");
    await cache.put("/v1/onboarding", { person_id: "person-1" });
    currentTime += OFFLINE_READ_CACHE_MAX_RETENTION_MS + 1;
    await expect(cache.get("/v1/onboarding")).resolves.toBeNull();
    expect(store.records.size).toBe(0);

    currentTime = 5_000;
    await cache.put("/v1/onboarding", { person_id: "person-1" });
    const record = [...store.records.values()][0];
    if (!record) throw new Error("Expected an encrypted record.");
    new Uint8Array(record.ciphertext)[0] ^= 0xff;
    await expect(cache.get("/v1/onboarding")).resolves.toBeNull();
    expect(store.records.size).toBe(0);
  });

  it("purges the prior owner before activating a different owner", async () => {
    const { cache, store } = makeCache(() => 6_000);
    await cache.activateOwner("person-1");
    await cache.put("/v1/onboarding", { person_id: "person-1" });
    expect(store.records.size).toBe(1);

    await expect(cache.activateOwner("person-2")).resolves.toMatchObject({
      ok: true,
    });
    expect(store.records.size).toBe(0);
    await expect(cache.get("/v1/onboarding")).resolves.toBeNull();
  });

  it("purges private reads before activating a different tenant for the same person", async () => {
    const { cache, store } = makeCache(() => 7_000);
    await cache.activateOwner("person-1", "tenant-1");
    await cache.put("/v1/onboarding", { person_id: "person-1" });
    expect(store.records.size).toBe(1);

    await expect(
      cache.activateOwner("person-1", "tenant-2"),
    ).resolves.toMatchObject({ ok: true });
    expect(store.records.size).toBe(0);
    await expect(cache.get("/v1/onboarding")).resolves.toBeNull();
  });

  it("bounds the number of retained encrypted records", async () => {
    let currentTime = 10_000;
    const { cache, store } = makeCache(() => currentTime++);
    for (
      let index = 0;
      index < OFFLINE_READ_CACHE_MAX_ENTRIES + 5;
      index += 1
    ) {
      await cache.put(`/v1/programs/program-${index}`, { index });
    }
    expect(store.records.size).toBeLessThanOrEqual(
      OFFLINE_READ_CACHE_MAX_ENTRIES,
    );
  });

  it("fails closed when browser persistence or crypto is unavailable", async () => {
    const cache = createOfflineReadCache({
      crypto: null,
      indexedDB: null,
      sessionStorage: null,
      store: null,
    });
    await expect(cache.get("/v1/programs?limit=50")).resolves.toBeNull();
    await expect(cache.put("/v1/programs?limit=50", {})).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    await expect(cache.purge()).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("exposes offline metadata without changing enumerable response fields", () => {
    const body = {
      title: "Cached lesson",
      items: [{ id: "lesson-1", nested: { label: "Read only" } }],
    };
    markOfflineRead(body, 7_000);
    expect(getOfflineReadMetadata(body)).toEqual({
      isOfflineCopy: true,
      savedAt: 7_000,
    });
    expect(getOfflineReadMetadata(body.items)).toEqual({
      isOfflineCopy: true,
      savedAt: 7_000,
    });
    expect(getOfflineReadMetadata(body.items[0]?.nested)).toEqual({
      isOfflineCopy: true,
      savedAt: 7_000,
    });
    expect(Object.keys(body)).toEqual(["title", "items"]);
    expect(Object.keys(body.items[0] ?? {})).toEqual(["id", "nested"]);
  });

  it("keeps provenance available for frozen response trees", () => {
    const nested = Object.freeze({ title: "Cached lesson" });
    const body = Object.freeze({ items: Object.freeze([nested]) });

    markOfflineRead(body, 8_000);

    expect(getOfflineReadMetadata(body)).toEqual({
      isOfflineCopy: true,
      savedAt: 8_000,
    });
    expect(getOfflineReadMetadata(body.items)).toEqual({
      isOfflineCopy: true,
      savedAt: 8_000,
    });
    expect(getOfflineReadMetadata(nested)).toEqual({
      isOfflineCopy: true,
      savedAt: 8_000,
    });
    const live = { title: "Live" };
    markOfflineRead(live, 9_000);
    expect(getEarliestOfflineReadMetadata(live, body)).toEqual({
      isOfflineCopy: true,
      savedAt: 8_000,
    });
  });

  it("does not leak crypto failures from best-effort cleanup", async () => {
    const store = new MemoryOfflineReadStore();
    const cache = createOfflineReadCache({
      crypto: {
        subtle: {
          digest: vi.fn().mockRejectedValue(new Error("blocked")),
        },
      } as unknown as Crypto,
      sessionStorage: memoryStorage(),
      store,
    });
    await expect(cache.activateOwner("person-1")).resolves.toMatchObject({
      ok: false,
    });
    expect(store.records.size).toBe(0);
  });
});
