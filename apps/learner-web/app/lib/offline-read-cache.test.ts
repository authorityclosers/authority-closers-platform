import { describe, expect, it, vi } from "vitest";

import { createLearnerApi } from "./learner-api";
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
  type OfflineReadCache,
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

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
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

class DeferredWriteStore extends MemoryOfflineReadStore {
  readonly writeStarted: Promise<void>;
  private releaseWrite!: () => void;
  private readonly writeGate: Promise<void>;

  constructor() {
    super();
    this.writeGate = new Promise<void>((resolve) => {
      this.releaseWrite = resolve;
    });
    this.writeStarted = new Promise<void>((resolve) => {
      this.writeStartedResolver = resolve;
    });
  }

  private writeStartedResolver!: () => void;

  override async write(record: OfflineReadCacheRecord) {
    this.writeStartedResolver();
    await this.writeGate;
    await super.write(record);
  }

  releaseDeferredWrite(): void {
    this.releaseWrite();
  }
}

class DeferredReadStore extends MemoryOfflineReadStore {
  readonly readStarted: Promise<void>;
  private releaseRead!: () => void;
  private readonly readGate: Promise<void>;
  private readStartedResolver!: () => void;

  constructor() {
    super();
    this.readGate = new Promise<void>((resolve) => {
      this.releaseRead = resolve;
    });
    this.readStarted = new Promise<void>((resolve) => {
      this.readStartedResolver = resolve;
    });
  }

  override async read(cacheKey: string) {
    const record = this.records.get(cacheKey) ?? null;
    this.readStartedResolver();
    await this.readGate;
    return record;
  }

  releaseDeferredRead(): void {
    this.releaseRead();
  }
}

function makeCache(
  now: () => number = () => Date.now(),
  store = new MemoryOfflineReadStore(),
) {
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

function trackCacheWrites(cache: OfflineReadCache) {
  const writes: Array<Promise<unknown>> = [];
  const trackedCache: OfflineReadCache = {
    ...cache,
    put: (...args) => {
      const write = cache.put(...args);
      writes.push(write);
      return write;
    },
  };
  return { cache: trackedCache, writes };
}

describe("offline learner read policy", () => {
  it("allows only the bounded read paths", () => {
    expect(getOfflineReadPolicy("/v1/onboarding")).toMatchObject({
      kind: "onboarding",
    });
    expect(getOfflineReadPolicy("/v1/me")).toMatchObject({
      kind: "me",
      requiresOwner: true,
      allowsPublicFallback: false,
    });
    expect(getOfflineReadPolicy("/v1/programs?limit=50")).toMatchObject({
      kind: "program-list",
    });
    expect(getOfflineReadPolicy("/v1/learning?limit=50")).toMatchObject({
      kind: "learning",
      requiresOwner: true,
      allowsPublicFallback: false,
    });
    expect(
      getOfflineReadPolicy("/v1/learning?limit=50&cursor=cursor-2"),
    ).toMatchObject({ kind: "learning" });
    expect(
      getOfflineReadPolicy(`/v1/learning?limit=50&cursor=${"c".repeat(512)}`),
    ).toMatchObject({ kind: "learning" });
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
      "/v1/activities/activity-1",
      "/v1/activities/activity-1/draft",
      "/v1/activities/activity-1/evidence",
      "/v1/certificates/certificate-1",
      "/v1/auth/password/login",
      "/v1/programs?limit=0",
      "/v1/programs?limit=101",
      "/v1/programs?limit=50&limit=50",
      "/v1/learning?limit=49",
      "/v1/learning?cursor=cursor-2",
      "/v1/learning?limit=50&cursor=",
      "/v1/learning?limit=50&cursor=cursor-2&cursor=cursor-3",
      `/v1/learning?limit=50&cursor=${"c".repeat(513)}`,
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
    await expect(cache.get("/v1/learning?limit=50")).resolves.toBeNull();
  });

  it("stores authenticated self and every bounded learning page under the active owner", async () => {
    const { cache } = makeCache(() => 2_500);
    const me = {
      person_id: "person-1",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
    };
    const collection = {
      items: [],
      next_cursor: "cursor-2",
      saved_filter_available: true,
    };

    await cache.activateOwner("person-1", "tenant-1");
    await expect(cache.put("/v1/me", me)).resolves.toMatchObject({ ok: true });
    await expect(
      cache.put("/v1/learning?limit=50", collection),
    ).resolves.toMatchObject({ ok: true });
    await expect(
      cache.put("/v1/learning?limit=50&cursor=cursor-2", {
        ...collection,
        next_cursor: null,
      }),
    ).resolves.toMatchObject({ ok: true });

    await expect(cache.get("/v1/me")).resolves.toMatchObject({
      data: me,
      savedAt: 2_500,
    });
    await expect(cache.get("/v1/learning?limit=50")).resolves.toMatchObject({
      data: collection,
      savedAt: 2_500,
    });
    await expect(
      cache.get("/v1/learning?limit=50&cursor=cursor-2"),
    ).resolves.toMatchObject({ savedAt: 2_500 });
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
    await cache.put("/v1/me", { person_id: "person-1" });
    await cache.put("/v1/learning?limit=50", {
      items: [],
      next_cursor: null,
      saved_filter_available: false,
    });
    expect(store.records.size).toBe(2);

    await expect(
      cache.activateOwner("person-1", "tenant-2"),
    ).resolves.toMatchObject({ ok: true });
    expect(store.records.size).toBe(0);
    await expect(cache.get("/v1/me")).resolves.toBeNull();
    await expect(cache.get("/v1/learning?limit=50")).resolves.toBeNull();
  });

  it("fails closed when a cross-person or cross-tenant owner write throws", async () => {
    for (const [nextPerson, nextTenant] of [
      ["person-2", "tenant-1"],
      ["person-1", "tenant-2"],
    ] as const) {
      const { cache, sessionStorage, store } = makeCache(() => 7_500);
      await cache.activateOwner("person-1", "tenant-1");
      await cache.put("/v1/me", { person_id: "person-1" });
      await cache.put("/v1/learning?limit=50", {
        items: [{ program_id: "private-course" }],
        next_cursor: null,
      });
      expect(store.records.size).toBe(2);

      sessionStorage.setItem = () => {
        throw new Error("sessionStorage is unavailable");
      };

      await expect(
        cache.activateOwner(nextPerson, nextTenant),
      ).resolves.toMatchObject({ ok: false, reason: "unavailable" });
      expect(store.records.size).toBe(0);
      expect(await cache.get("/v1/me")).toBeNull();
      expect(await cache.get("/v1/learning?limit=50")).toBeNull();
      await expect(
        cache.put("/v1/learning?limit=50", { items: [] }),
      ).resolves.toMatchObject({ ok: false, reason: "unavailable" });
    }
  });

  it("drops an in-flight private write after the owner generation changes", async () => {
    const store = new DeferredWriteStore();
    const { cache } = makeCache(() => 8_000, store);
    const firstActivation = await cache.activateOwner("person-1", "tenant-1");
    if (!firstActivation.ok) throw new Error("Expected the first owner lease.");

    const pendingWrite = cache.put(
      "/v1/me",
      { person_id: "person-1" },
      firstActivation.lease,
    );
    await store.writeStarted;

    const secondActivation = await cache.activateOwner("person-2", "tenant-1");
    if (!secondActivation.ok) {
      throw new Error("Expected the second owner lease.");
    }
    store.releaseDeferredWrite();

    await expect(pendingWrite).resolves.toMatchObject({
      ok: false,
      reason: "unavailable",
    });
    expect(store.records.size).toBe(0);

    await expect(
      cache.put("/v1/me", { person_id: "person-2" }, secondActivation.lease),
    ).resolves.toMatchObject({ ok: true });
    await expect(cache.get("/v1/me")).resolves.toMatchObject({
      data: { person_id: "person-2" },
    });
  });

  it("drops an in-flight private write after logout purge", async () => {
    const store = new DeferredWriteStore();
    const { cache } = makeCache(() => 8_500, store);
    const activation = await cache.activateOwner("person-1", "tenant-1");
    if (!activation.ok) throw new Error("Expected the owner lease.");

    const pendingWrite = cache.put(
      "/v1/learning?limit=50",
      { items: [{ program_id: "private-course" }] },
      activation.lease,
    );
    await store.writeStarted;
    await expect(cache.purge()).resolves.toMatchObject({ ok: true });
    store.releaseDeferredWrite();

    await expect(pendingWrite).resolves.toMatchObject({
      ok: false,
      reason: "unavailable",
    });
    expect(store.records.size).toBe(0);
    await expect(cache.get("/v1/learning?limit=50")).resolves.toBeNull();
  });

  it("rejects a stale lease held by another cache instance after a shared-owner rebind", async () => {
    const sessionStorage = memoryStorage();
    const store = new MemoryOfflineReadStore();
    const crypto = globalThis.crypto;
    if (!crypto?.subtle) {
      throw new Error("The focused cache tests require Web Crypto.");
    }
    const firstCache = createOfflineReadCache({
      crypto,
      now: () => 9_000,
      sessionStorage,
      store,
    });
    const secondCache = createOfflineReadCache({
      crypto,
      now: () => 9_000,
      sessionStorage,
      store,
    });

    const firstActivation = await firstCache.activateOwner(
      "person-1",
      "tenant-1",
    );
    if (!firstActivation.ok) throw new Error("Expected the first owner lease.");
    const secondActivation = await secondCache.activateOwner(
      "person-2",
      "tenant-1",
    );
    if (!secondActivation.ok) {
      throw new Error("Expected the second owner lease.");
    }

    await expect(
      firstCache.put(
        "/v1/learning?limit=50",
        { items: [{ program_id: "person-1-course" }] },
        firstActivation.lease,
      ),
    ).resolves.toMatchObject({ ok: false, reason: "unavailable" });
    await expect(
      secondCache.put(
        "/v1/learning?limit=50",
        { items: [{ program_id: "person-2-course" }] },
        secondActivation.lease,
      ),
    ).resolves.toMatchObject({ ok: true });
    await expect(
      secondCache.get("/v1/learning?limit=50"),
    ).resolves.toMatchObject({
      data: { items: [{ program_id: "person-2-course" }] },
    });
  });

  it("rejects all private API responses that resolve after an A-to-B rebind", async () => {
    const {
      cache: firstCache,
      crypto,
      sessionStorage,
      store,
    } = makeCache(() => 9_250);
    const secondCache = createOfflineReadCache({
      crypto,
      now: () => 9_250,
      sessionStorage,
      store,
    });
    const trackedFirstCache = trackCacheWrites(firstCache);
    const firstMe = {
      person_id: "person-a",
      email: "a@example.com",
      display_name: "Learner A",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: ["learner:read"],
    };
    const secondMe = {
      ...firstMe,
      person_id: "person-b",
      email: "b@example.com",
      display_name: "Learner B",
    };
    const firstCollection = {
      items: [{ program_id: "course-a" }],
      next_cursor: null,
      saved_filter_available: true,
    };
    const firstOnboarding = {
      person_id: "person-a",
      status: "in_progress",
      current_step: 2,
    };
    const firstDetail = {
      program_id: "course-a",
      program_title: "Course A",
      enrollment_id: "enrollment-a",
    };
    let resolveCollection!: (value: Response) => void;
    let resolveOnboarding!: (value: Response) => void;
    let resolveDetail!: (value: Response) => void;
    const collectionResponse = new Promise<Response>((resolve) => {
      resolveCollection = resolve;
    });
    const onboardingResponse = new Promise<Response>((resolve) => {
      resolveOnboarding = resolve;
    });
    const detailResponse = new Promise<Response>((resolve) => {
      resolveDetail = resolve;
    });
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(firstMe))
      .mockReturnValueOnce(collectionResponse)
      .mockReturnValueOnce(onboardingResponse)
      .mockReturnValueOnce(detailResponse)
      .mockResolvedValueOnce(response(secondMe));
    const api = createLearnerApi(fetcher, {
      offlineReadCache: trackedFirstCache.cache,
    });
    await expect(api.me()).resolves.toEqual(firstMe);
    await Promise.all(trackedFirstCache.writes.splice(0));

    const pendingCollection = api.learningCollection();
    const pendingOnboarding = api.onboarding();
    const pendingDetail = api.learning("course-a", {
      enrollmentId: "enrollment-a",
      programVersionId: "version-a",
    });
    await expect(api.me()).resolves.toEqual(secondMe);
    await Promise.all(trackedFirstCache.writes.splice(0));

    resolveCollection(response(firstCollection));
    resolveOnboarding(response(firstOnboarding));
    resolveDetail(response(firstDetail));
    await expect(pendingCollection).resolves.toEqual(firstCollection);
    await expect(pendingOnboarding).resolves.toEqual(firstOnboarding);
    await expect(pendingDetail).resolves.toEqual(firstDetail);
    const staleWrites = trackedFirstCache.writes.splice(0);
    await expect(Promise.all(staleWrites)).resolves.toEqual([
      { ok: false, reason: "unavailable" },
      { ok: false, reason: "unavailable" },
      { ok: false, reason: "unavailable" },
    ]);

    const secondApi = createLearnerApi(
      vi.fn().mockRejectedValue(new TypeError("offline")),
      { offlineReadCache: secondCache },
    );
    await expect(secondApi.me()).resolves.toEqual(secondMe);
    await expect(secondApi.learningCollection()).rejects.toThrow("offline");
    await expect(secondApi.onboarding()).rejects.toThrow("offline");
    await expect(
      secondApi.learning("course-a", {
        enrollmentId: "enrollment-a",
        programVersionId: "version-a",
      }),
    ).rejects.toThrow("offline");
    expect(store.records.size).toBe(1);
  });

  it("does not return an in-flight private /v1/me read after another cache instance rebinds the owner", async () => {
    const sessionStorage = memoryStorage();
    const store = new DeferredReadStore();
    const crypto = globalThis.crypto;
    if (!crypto?.subtle) {
      throw new Error("The focused cache tests require Web Crypto.");
    }
    const firstCache = createOfflineReadCache({
      crypto,
      now: () => 9_500,
      sessionStorage,
      store,
    });
    const secondCache = createOfflineReadCache({
      crypto,
      now: () => 9_500,
      sessionStorage,
      store,
    });
    const firstMe = {
      person_id: "person-1",
      email: "first@example.com",
      display_name: "First learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: ["learner:read"],
    };

    const firstActivation = await firstCache.activateOwner(
      "person-1",
      "tenant-1",
    );
    if (!firstActivation.ok) throw new Error("Expected the first owner lease.");
    await expect(
      firstCache.put("/v1/me", firstMe, firstActivation.lease),
    ).resolves.toMatchObject({
      ok: true,
    });

    const networkFailure = new TypeError("offline");
    const api = createLearnerApi(vi.fn().mockRejectedValue(networkFailure), {
      offlineReadCache: firstCache,
    });
    const pendingRead = api.me();
    await store.readStarted;

    const secondActivation = await secondCache.activateOwner(
      "person-2",
      "tenant-1",
    );
    if (!secondActivation.ok) {
      throw new Error("Expected the second owner lease.");
    }
    store.releaseDeferredRead();

    await expect(pendingRead).rejects.toBe(networkFailure);
    expect(store.records.size).toBe(0);
  });

  it("does not return an in-flight private /v1/me decrypt after logout purge", async () => {
    const { cache, crypto, sessionStorage, store } = makeCache(() => 10_000);
    const purgeCache = createOfflineReadCache({
      crypto,
      now: () => 10_000,
      sessionStorage,
      store,
    });
    const me = {
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: ["learner:read"],
    };
    const activation = await cache.activateOwner("person-1", "tenant-1");
    if (!activation.ok) throw new Error("Expected the owner lease.");
    await expect(
      cache.put("/v1/me", me, activation.lease),
    ).resolves.toMatchObject({
      ok: true,
    });

    let releaseDecrypt!: () => void;
    let decryptStartedResolver!: () => void;
    const decryptGate = new Promise<void>((resolve) => {
      releaseDecrypt = resolve;
    });
    const decryptStarted = new Promise<void>((resolve) => {
      decryptStartedResolver = resolve;
    });
    const originalDecrypt = crypto.subtle.decrypt.bind(crypto.subtle);
    const decryptSpy = vi
      .spyOn(crypto.subtle, "decrypt")
      .mockImplementation(async (...args) => {
        decryptStartedResolver();
        await decryptGate;
        return originalDecrypt(...args);
      });

    try {
      const networkFailure = new TypeError("offline");
      const api = createLearnerApi(vi.fn().mockRejectedValue(networkFailure), {
        offlineReadCache: cache,
      });
      const pendingRead = api.me();
      await decryptStarted;

      await expect(purgeCache.purge()).resolves.toMatchObject({ ok: true });
      releaseDecrypt();

      await expect(pendingRead).rejects.toBe(networkFailure);
      expect(store.records.size).toBe(0);
    } finally {
      decryptSpy.mockRestore();
    }
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
