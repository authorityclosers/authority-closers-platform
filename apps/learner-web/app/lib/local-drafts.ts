import { ApiError } from "./learner-api";

export type OnboardingLocalDraft = {
  experienceContext: string;
  learningGoal: string;
  practiceSituation: string;
  weeklyMinutes: string;
};

export type OnboardingLocalStep = 1 | 2 | 3;

export type OnboardingDraftScope = {
  kind: "onboarding";
  personId: string;
};

export type ActivityDraftScope = {
  kind: "activity";
  tenantId: string;
  personId: string;
  enrollmentId: string;
  activityId: string;
};

export type LocalDraftEnvelope<
  TDraft,
  TScope,
  TVersion extends number = number,
> = {
  version: TVersion;
  scope: TScope;
  baseRevision: number;
  serverFingerprint: string;
  createdAt: string;
  updatedAt: string;
  expiresAt: string;
  draft: TDraft;
};

export type OnboardingDraftEnvelope = LocalDraftEnvelope<
  OnboardingLocalDraft,
  OnboardingDraftScope,
  3
> & {
  /** The local question to restore; this is not a server onboarding step. */
  localStep: OnboardingLocalStep;
};

export type LegacyOnboardingDraftEnvelope = Omit<
  OnboardingDraftEnvelope,
  "version" | "localStep"
> & {
  version: 2;
};

export type OnboardingLocalDraftCleanupTarget =
  | OnboardingDraftEnvelope
  | LegacyOnboardingDraftEnvelope;

export type ActivityDraftEnvelope = LocalDraftEnvelope<
  { response: string },
  ActivityDraftScope,
  2
>;

export type LocalDraftReadResult<TEnvelope> =
  | { status: "missing" }
  | { status: "ready"; envelope: TEnvelope }
  | { status: "expired" }
  | { status: "invalid" }
  | { status: "unavailable" };

export type LocalDraftRawSnapshot = {
  readonly raw: string;
};

export type LocalDraftRecoveryReadResult<TEnvelope> =
  | { status: "missing" }
  | { status: "ready"; envelope: TEnvelope }
  | {
      status: "expired" | "invalid";
      cleanupTarget: LocalDraftRawSnapshot;
      cleanupStatus?: "unavailable" | "changed";
    }
  | { status: "unavailable" };

export type LocalDraftStorageResult =
  | { ok: true }
  | { ok: false; reason: "quota" | "unavailable" };

export type ConditionalLocalDraftStorageResult =
  | LocalDraftStorageResult
  | { ok: false; reason: "busy" | "changed" };

export type LockedOnboardingLocalDraftWrite = {
  result: LocalDraftStorageResult;
  /** The exact envelope written while holding the recovery lock. */
  envelope: OnboardingDraftEnvelope | null;
};

export type LockedActivityLocalDraftWrite = {
  result: LocalDraftStorageResult;
  /** The exact envelope written while holding the recovery lock. */
  envelope: ActivityDraftEnvelope | null;
};

type StorageLike = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem" | "key" | "length"
>;

export type OnboardingRecoveryLockManager = {
  request<T>(
    name: string,
    options: { mode: "exclusive"; ifAvailable: true },
    callback: (lock: unknown | null) => Promise<T> | T,
  ): Promise<T>;
};

export type OnboardingRecoveryLockResult<T> =
  | { ok: true; value: T }
  | { ok: false; reason: "busy" | "unavailable" };

export type OnboardingRecoveryLease = {
  readonly personId: string;
  readonly [onboardingRecoveryLeaseBrand]: true;
};

export type OnboardingLocalDraftRecoveryRead =
  | {
      status: "missing" | "unavailable";
    }
  | {
      status: "expired" | "invalid";
      cleanupTarget: LocalDraftRawSnapshot;
      cleanupStatus?: "unavailable" | "changed";
    }
  | {
      status: "ready";
      envelope: OnboardingDraftEnvelope;
      cleanupTarget: OnboardingLocalDraftCleanupTarget;
    };

type BeforeUnloadTarget = {
  addEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
  ) => void;
  removeEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
  ) => void;
};

type ClickGuardTarget = {
  addEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ) => void;
  removeEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ) => void;
};

type HistoryNavigationGuardTarget = {
  readonly location: { href: string };
  readonly history: {
    readonly state: unknown;
    pushState: (
      data: unknown,
      unused: string,
      url?: string | URL | null,
    ) => void;
  };
  addEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ) => void;
  removeEventListener: (
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ) => void;
  readonly navigation?: {
    addEventListener: (
      type: string,
      listener: EventListenerOrEventListenerObject,
    ) => void;
    removeEventListener: (
      type: string,
      listener: EventListenerOrEventListenerObject,
    ) => void;
  };
};

const LEGACY_LOCAL_DRAFT_VERSION = 2;
const ONBOARDING_LOCAL_DRAFT_VERSION = 3;
const LOCAL_DRAFT_PREFIX = "ac-learner-local-draft";
const LEARNER_RECOVERY_LOCK_NAME = "ac-learner-local-draft:onboarding-recovery";

const onboardingRecoveryLeaseBrand = Symbol("onboarding-recovery-lease");
const activeOnboardingLeases = new WeakSet<object>();

/**
 * Local learner drafts are a recovery cache, not canonical learning records.
 * Seven days gives an interrupted learner a bounded recovery window; successful
 * server saves, sign-out, and membership loss remove the local copy. Expired or
 * malformed copies are retained until an explicit, locked cleanup can verify
 * ownership, so an interleaved write cannot be lost.
 */
export const LEARNER_LOCAL_DRAFT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

function onboardingKey(personId: string): string {
  return `${LOCAL_DRAFT_PREFIX}:onboarding:${encodeURIComponent(personId)}`;
}

function activityKey(scope: ActivityDraftScope): string {
  return `${LOCAL_DRAFT_PREFIX}:activity:${encodeURIComponent(scope.tenantId)}:${encodeURIComponent(scope.personId)}:${encodeURIComponent(scope.enrollmentId)}:${encodeURIComponent(scope.activityId)}`;
}

function storageFailure(error: unknown): LocalDraftStorageResult {
  const name =
    typeof error === "object" && error !== null && "name" in error
      ? String((error as { name: unknown }).name)
      : "";
  return {
    ok: false,
    reason:
      name === "QuotaExceededError" || name === "NS_ERROR_DOM_QUOTA_REACHED"
        ? "quota"
        : "unavailable",
  };
}

function setStored(
  storage: StorageLike | null,
  key: string,
  value: unknown,
): LocalDraftStorageResult {
  if (!storage) return { ok: false, reason: "unavailable" };
  try {
    storage.setItem(key, JSON.stringify(value));
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

function removeStored(
  storage: StorageLike | null,
  key: string,
): LocalDraftStorageResult {
  if (!storage) return { ok: false, reason: "unavailable" };
  try {
    storage.removeItem(key);
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

function readStored(
  storage: StorageLike | null,
  key: string,
):
  | { status: "missing" }
  | { status: "value"; value: unknown; raw: string }
  | { status: "invalid"; raw: string }
  | { status: "unavailable" } {
  if (!storage) return { status: "unavailable" };
  try {
    const stored = storage.getItem(key);
    if (stored === null) return { status: "missing" };
    try {
      return {
        status: "value",
        value: JSON.parse(stored) as unknown,
        raw: stored,
      };
    } catch {
      return { status: "invalid", raw: stored };
    }
  } catch {
    return { status: "unavailable" };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function createOnboardingRecoveryLease(
  personId: string,
): OnboardingRecoveryLease {
  const lease = {
    personId,
    [onboardingRecoveryLeaseBrand]: true,
  } as OnboardingRecoveryLease;
  activeOnboardingLeases.add(lease);
  return lease;
}

function ownsOnboardingRecoveryLease(
  lease: OnboardingRecoveryLease,
  scope: OnboardingDraftScope,
): boolean {
  return activeOnboardingLeases.has(lease) && lease.personId === scope.personId;
}

function browserOnboardingLockManager(): OnboardingRecoveryLockManager | null {
  if (typeof navigator === "undefined") return null;
  try {
    return navigator.locks
      ? (navigator.locks as unknown as OnboardingRecoveryLockManager)
      : null;
  } catch {
    return null;
  }
}

export async function withOnboardingRecoveryLock<T>(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  task: (lease: OnboardingRecoveryLease) => Promise<T> | T,
  lockManager = browserOnboardingLockManager(),
): Promise<OnboardingRecoveryLockResult<T>> {
  if (!storage || !lockManager) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    return await lockManager.request(
      LEARNER_RECOVERY_LOCK_NAME,
      { mode: "exclusive", ifAvailable: true },
      async (lock) => {
        if (!lock) return { ok: false, reason: "busy" };
        const lease = createOnboardingRecoveryLease(scope.personId);
        try {
          return { ok: true, value: await task(lease) };
        } catch {
          return { ok: false, reason: "unavailable" };
        } finally {
          activeOnboardingLeases.delete(lease);
        }
      },
    );
  } catch {
    return { ok: false, reason: "unavailable" };
  }
}

function sameOnboardingScope(
  value: unknown,
  expected: OnboardingDraftScope,
): value is OnboardingDraftScope {
  return (
    isRecord(value) &&
    value.kind === "onboarding" &&
    value.personId === expected.personId
  );
}

function sameActivityScope(
  value: unknown,
  expected: ActivityDraftScope,
): value is ActivityDraftScope {
  return (
    isRecord(value) &&
    value.kind === "activity" &&
    value.tenantId === expected.tenantId &&
    value.personId === expected.personId &&
    value.enrollmentId === expected.enrollmentId &&
    value.activityId === expected.activityId
  );
}

function validEnvelopeMetadata(
  record: Record<string, unknown>,
  expectedVersion: number,
  now = Date.now(),
): boolean {
  const createdAt =
    typeof record.createdAt === "string" ? Date.parse(record.createdAt) : NaN;
  const updatedAt =
    typeof record.updatedAt === "string" ? Date.parse(record.updatedAt) : NaN;
  const expiresAt =
    typeof record.expiresAt === "string" ? Date.parse(record.expiresAt) : NaN;

  return (
    record.version === expectedVersion &&
    typeof record.baseRevision === "number" &&
    Number.isInteger(record.baseRevision) &&
    record.baseRevision >= 0 &&
    typeof record.serverFingerprint === "string" &&
    record.serverFingerprint.length > 0 &&
    typeof record.createdAt === "string" &&
    Number.isFinite(createdAt) &&
    typeof record.updatedAt === "string" &&
    Number.isFinite(updatedAt) &&
    typeof record.expiresAt === "string" &&
    Number.isFinite(expiresAt) &&
    createdAt <= updatedAt &&
    updatedAt <= now &&
    updatedAt - createdAt <= LEARNER_LOCAL_DRAFT_RETENTION_MS &&
    now - createdAt <= LEARNER_LOCAL_DRAFT_RETENTION_MS &&
    expiresAt > updatedAt &&
    expiresAt - updatedAt <= LEARNER_LOCAL_DRAFT_RETENTION_MS
  );
}

function isOnboardingDraft(value: unknown): value is OnboardingLocalDraft {
  return (
    isRecord(value) &&
    typeof value.experienceContext === "string" &&
    typeof value.learningGoal === "string" &&
    typeof value.practiceSituation === "string" &&
    typeof value.weeklyMinutes === "string"
  );
}

function envelopeTimes(now: number, createdAt?: string) {
  return {
    createdAt: createdAt ?? new Date(now).toISOString(),
    updatedAt: new Date(now).toISOString(),
    expiresAt: new Date(now + LEARNER_LOCAL_DRAFT_RETENTION_MS).toISOString(),
  };
}

function existingCreatedAt(
  storage: StorageLike | null,
  key: string,
  now: number,
): string | undefined | null {
  const stored = readStored(storage, key);
  if (stored.status === "unavailable") return null;
  if (stored.status !== "value" || !isRecord(stored.value)) return undefined;
  if (typeof stored.value.createdAt !== "string") return undefined;
  const createdAt = Date.parse(stored.value.createdAt);
  return Number.isFinite(createdAt) &&
    createdAt <= now &&
    now - createdAt <= LEARNER_LOCAL_DRAFT_RETENTION_MS
    ? stored.value.createdAt
    : undefined;
}

function isExpired(record: Record<string, unknown>, now: number): boolean {
  return (
    typeof record.expiresAt === "string" && Date.parse(record.expiresAt) <= now
  );
}

function stableSerialize(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableSerialize(record[key])}`)
    .join(",")}}`;
}

function fingerprint(value: unknown): string {
  const serialized = stableSerialize(value);
  let hash = 0x811c9dc5;
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= serialized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function onboardingServerFingerprint(
  draft: OnboardingLocalDraft,
): string {
  return fingerprint(draft);
}

export function activityServerFingerprint(response: string): string {
  return fingerprint({ response });
}

export function localDraftMatchesServer(
  envelope: Pick<
    LocalDraftEnvelope<unknown, unknown>,
    "baseRevision" | "serverFingerprint"
  >,
  revision: number,
  serverFingerprint: string,
): boolean {
  return (
    envelope.baseRevision === revision &&
    envelope.serverFingerprint === serverFingerprint
  );
}

export function readOnboardingLocalDraft(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now = Date.now(),
  fallbackLocalStep: OnboardingLocalStep = 1,
): LocalDraftReadResult<OnboardingDraftEnvelope> {
  if (typeof window !== "undefined") return { status: "unavailable" };
  return peekOnboardingLocalDraft(storage, scope, now, fallbackLocalStep);
}

export function peekOnboardingLocalDraft(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now = Date.now(),
  fallbackLocalStep: OnboardingLocalStep = 1,
): LocalDraftReadResult<OnboardingDraftEnvelope> {
  if (typeof window !== "undefined") return { status: "unavailable" };
  const result = peekOnboardingLocalDraftForCleanup(storage, scope, now);
  if (result.status !== "ready" || result.envelope.version === 3) {
    return result as LocalDraftReadResult<OnboardingDraftEnvelope>;
  }
  return {
    status: "ready",
    envelope: {
      ...result.envelope,
      version: ONBOARDING_LOCAL_DRAFT_VERSION,
      localStep: fallbackLocalStep,
    } as OnboardingDraftEnvelope,
  };
}

export function peekOnboardingLocalDraftForCleanup(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now = Date.now(),
): LocalDraftReadResult<OnboardingLocalDraftCleanupTarget> {
  if (typeof window !== "undefined") return { status: "unavailable" };
  return peekOnboardingLocalDraftForCleanupCore(storage, scope, now);
}

function peekOnboardingLocalDraftForCleanupCore(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now: number,
): LocalDraftReadResult<OnboardingLocalDraftCleanupTarget> {
  const result = readOnboardingLocalDraftRawCore(storage, scope, now);
  if (result.status === "ready") return result;
  return { status: result.status };
}

function readOnboardingLocalDraftRawCore(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now: number,
): LocalDraftRecoveryReadResult<OnboardingLocalDraftCleanupTarget> {
  const stored = readStored(storage, onboardingKey(scope.personId));
  if (stored.status === "missing" || stored.status === "unavailable") {
    return stored;
  }
  if (stored.status === "invalid") {
    return { status: "invalid", cleanupTarget: { raw: stored.raw } };
  }
  if (!isRecord(stored.value)) {
    return { status: "invalid", cleanupTarget: { raw: stored.raw } };
  }
  const record = stored.value;
  if (isExpired(record, now)) {
    return { status: "expired", cleanupTarget: { raw: stored.raw } };
  }

  if (
    validEnvelopeMetadata(record, ONBOARDING_LOCAL_DRAFT_VERSION, now) &&
    sameOnboardingScope(record.scope, scope) &&
    isOnboardingDraft(record.draft) &&
    isOnboardingLocalStep(record.localStep)
  ) {
    return {
      status: "ready",
      envelope: record as OnboardingLocalDraftCleanupTarget,
    };
  }

  // Version 2 did not preserve the local question. It can be migrated only
  // after the full legacy envelope is validated. The raw v2 record remains the
  // cleanup target so an editor migration cannot bypass conditional cleanup.
  if (
    validEnvelopeMetadata(record, LEGACY_LOCAL_DRAFT_VERSION, now) &&
    sameOnboardingScope(record.scope, scope) &&
    isOnboardingDraft(record.draft)
  ) {
    return {
      status: "ready",
      envelope: record as OnboardingLocalDraftCleanupTarget,
    };
  }

  return { status: "invalid", cleanupTarget: { raw: stored.raw } };
}

function onboardingRecoveryReadAfterPurge(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  initial: LocalDraftRecoveryReadResult<OnboardingLocalDraftCleanupTarget>,
  now: number,
  lease: OnboardingRecoveryLease,
  fallbackLocalStep: OnboardingLocalStep,
): OnboardingLocalDraftRecoveryRead {
  if (initial.status === "missing" || initial.status === "unavailable") {
    return initial;
  }
  if (initial.status === "ready") {
    return {
      status: "ready",
      envelope:
        initial.envelope.version === 2
          ? {
              ...initial.envelope,
              version: ONBOARDING_LOCAL_DRAFT_VERSION,
              localStep: fallbackLocalStep,
            }
          : initial.envelope,
      cleanupTarget: initial.envelope,
    } as OnboardingLocalDraftRecoveryRead;
  }
  const purged = purgeOnboardingLocalDraftIfMatchesCore(
    storage,
    scope,
    initial.cleanupTarget,
    now,
    lease,
  );
  if (purged.ok) return { status: "missing" };
  if (purged.reason === "changed") {
    const current = readOnboardingLocalDraftRawCore(storage, scope, now);
    if (current.status === "ready") {
      return {
        status: "ready",
        envelope: {
          ...current.envelope,
          ...(current.envelope.version === 2
            ? {
                version: ONBOARDING_LOCAL_DRAFT_VERSION,
                localStep: fallbackLocalStep,
              }
            : {}),
        } as OnboardingDraftEnvelope,
        cleanupTarget: current.envelope,
      };
    }
    if (current.status === "expired" || current.status === "invalid") {
      return {
        ...current,
        cleanupStatus: "changed",
      };
    }
    return current;
  }
  return { ...initial, cleanupStatus: "unavailable" };
}

export async function readOnboardingLocalDraftWithLock(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now = Date.now(),
  fallbackLocalStep: OnboardingLocalStep = 1,
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<OnboardingLocalDraftRecoveryRead> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) => {
      const raw = readOnboardingLocalDraftRawUnderLock(
        storage,
        scope,
        now,
        lease,
        fallbackLocalStep,
      );
      return raw;
    },
    lockManager,
  );
  return locked.ok ? locked.value : { status: "unavailable" };
}

export async function peekOnboardingLocalDraftForCleanupWithLock(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<OnboardingLocalDraftRecoveryRead> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) =>
      readOnboardingLocalDraftRawUnderLock(storage, scope, now, lease, 1),
    lockManager,
  );
  return locked.ok ? locked.value : { status: "unavailable" };
}

function readOnboardingLocalDraftRawUnderLock(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  now: number,
  lease: OnboardingRecoveryLease,
  fallbackLocalStep: OnboardingLocalStep,
): OnboardingLocalDraftRecoveryRead {
  if (!ownsOnboardingRecoveryLease(lease, scope)) {
    return { status: "unavailable" };
  }
  const raw = readOnboardingLocalDraftRawCore(storage, scope, now);
  return onboardingRecoveryReadAfterPurge(
    storage,
    scope,
    raw,
    now,
    lease,
    fallbackLocalStep,
  );
}

export function writeOnboardingLocalDraft(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
): LocalDraftStorageResult {
  // Kept for non-browser fixture setup. Browser callers must use the locked
  // async operation below; without Web Locks this path fails closed.
  if (typeof window !== "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  return writeOnboardingLocalDraftCore(storage, input);
}

function writeOnboardingLocalDraftCoreWithEnvelope(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
  lease?: OnboardingRecoveryLease,
): LockedOnboardingLocalDraftWrite {
  if (lease && !ownsOnboardingRecoveryLease(lease, input.scope)) {
    return {
      result: { ok: false, reason: "unavailable" },
      envelope: null,
    };
  }
  const now = input.now ?? Date.now();
  const key = onboardingKey(input.scope.personId);
  const createdAt = existingCreatedAt(storage, key, now);
  if (createdAt === null) {
    return {
      result: { ok: false, reason: "unavailable" },
      envelope: null,
    };
  }
  const envelope = {
    version: ONBOARDING_LOCAL_DRAFT_VERSION,
    scope: input.scope,
    baseRevision: input.baseRevision,
    serverFingerprint: input.serverFingerprint,
    ...envelopeTimes(now, createdAt),
    localStep: input.localStep ?? 1,
    draft: input.draft,
  } satisfies OnboardingDraftEnvelope;
  const result = setStored(storage, key, envelope);
  return { result, envelope: result.ok ? envelope : null };
}

function writeOnboardingLocalDraftCore(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
  lease?: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  return writeOnboardingLocalDraftCoreWithEnvelope(storage, input, lease)
    .result;
}

export async function writeOnboardingLocalDraftWithLock(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftStorageResult> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    input.scope,
    (lease) => writeOnboardingLocalDraftCore(storage, input, lease),
    lockManager,
  );
  return locked.ok ? locked.value : { ok: false, reason: "unavailable" };
}

/**
 * Writes an onboarding recovery copy and returns its exact envelope from the
 * same lock section. Callers that will later clear after a server mutation
 * must carry this returned envelope instead of peeking in a second section.
 */
export async function writeOnboardingLocalDraftWithLockAndEnvelope(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LockedOnboardingLocalDraftWrite> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    input.scope,
    (lease) => writeOnboardingLocalDraftCoreWithEnvelope(storage, input, lease),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { result: { ok: false, reason: "unavailable" }, envelope: null };
}

/**
 * A lease-bound primitive for deterministic tests and code already executing
 * inside the recovery critical section. A captured lease is revoked as soon
 * as that section returns, so it cannot authorize a later write.
 */
export function writeOnboardingLocalDraftWithLease(
  storage: StorageLike | null,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    localStep?: OnboardingLocalStep;
    now?: number;
  },
  lease: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  return writeOnboardingLocalDraftCore(storage, input, lease);
}

export function clearOnboardingLocalDraft(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
): LocalDraftStorageResult {
  // Kept for non-browser fixture setup. Browser callers must use the locked
  // conditional operation below; an unguarded browser removal fails closed.
  if (typeof window !== "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  return removeStored(storage, onboardingKey(scope.personId));
}

export function clearOnboardingLocalDraftIfMatches(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  expected: OnboardingLocalDraftCleanupTarget | null,
  now = Date.now(),
): ConditionalLocalDraftStorageResult {
  if (typeof window !== "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  return clearOnboardingLocalDraftIfMatchesCore(storage, scope, expected, now);
}

function clearOnboardingLocalDraftIfMatchesCore(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  expected: OnboardingLocalDraftCleanupTarget | null,
  now: number,
  lease?: OnboardingRecoveryLease,
): ConditionalLocalDraftStorageResult {
  if (lease && !ownsOnboardingRecoveryLease(lease, scope)) {
    return { ok: false, reason: "unavailable" };
  }
  if (!storage) return { ok: false, reason: "unavailable" };
  const key = onboardingKey(scope.personId);
  const stored = readStored(storage, key);
  if (stored.status === "missing") return { ok: true };
  if (stored.status !== "value" || !isRecord(stored.value)) {
    return { ok: false, reason: "changed" };
  }
  if (!expected) return { ok: false, reason: "changed" };

  const record = stored.value;
  const matches =
    validEnvelopeMetadata(record, expected.version, now) &&
    sameOnboardingScope(record.scope, scope) &&
    isOnboardingDraft(record.draft) &&
    stableSerialize(record) === stableSerialize(expected);
  if (!matches) return { ok: false, reason: "changed" };
  return removeStored(storage, key);
}

export async function clearOnboardingLocalDraftIfMatchesWithLock(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  expected: OnboardingLocalDraftCleanupTarget | null,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<ConditionalLocalDraftStorageResult> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) =>
      clearOnboardingLocalDraftIfMatchesCore(
        storage,
        scope,
        expected,
        now,
        lease,
      ),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { ok: false, reason: locked.reason === "busy" ? "busy" : "unavailable" };
}

function purgeOnboardingLocalDraftIfMatchesCore(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  expectedRaw: LocalDraftRawSnapshot,
  now: number,
  lease?: OnboardingRecoveryLease,
): ConditionalLocalDraftStorageResult {
  if (lease && !ownsOnboardingRecoveryLease(lease, scope)) {
    return { ok: false, reason: "unavailable" };
  }
  if (!storage) return { ok: false, reason: "unavailable" };
  const stored = readStored(storage, onboardingKey(scope.personId));
  if (stored.status === "missing") return { ok: true };
  if (stored.status === "unavailable") {
    return { ok: false, reason: "unavailable" };
  }

  if (stored.raw !== expectedRaw.raw) return { ok: false, reason: "changed" };

  // Read the raw bytes again before removal. This also protects against a
  // non-cooperating writer that changes storage without taking the Web Lock.
  const confirmed = readStored(storage, onboardingKey(scope.personId));
  if (
    confirmed.status === "missing" ||
    confirmed.status === "unavailable" ||
    confirmed.raw !== expectedRaw.raw
  ) {
    return {
      ok: false,
      reason: confirmed.status === "unavailable" ? "unavailable" : "changed",
    };
  }

  if (confirmed.status === "invalid") {
    return removeStored(storage, onboardingKey(scope.personId));
  }
  if (!isRecord(confirmed.value)) {
    return removeStored(storage, onboardingKey(scope.personId));
  }
  const record = confirmed.value;
  const valid =
    (validEnvelopeMetadata(record, ONBOARDING_LOCAL_DRAFT_VERSION, now) &&
      sameOnboardingScope(record.scope, scope) &&
      isOnboardingDraft(record.draft) &&
      isOnboardingLocalStep(record.localStep)) ||
    (validEnvelopeMetadata(record, LEGACY_LOCAL_DRAFT_VERSION, now) &&
      sameOnboardingScope(record.scope, scope) &&
      isOnboardingDraft(record.draft));
  if (!isExpired(record, now) && valid) {
    return { ok: false, reason: "changed" };
  }
  return removeStored(storage, onboardingKey(scope.personId));
}

/**
 * Explicitly purge an expired or invalid onboarding record only when its raw
 * snapshot is unchanged and the caller holds the learner recovery lock.
 */
export async function purgeOnboardingLocalDraftIfMatchesWithLock(
  storage: StorageLike | null,
  scope: OnboardingDraftScope,
  expectedRaw: LocalDraftRawSnapshot,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<ConditionalLocalDraftStorageResult> {
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) =>
      purgeOnboardingLocalDraftIfMatchesCore(
        storage,
        scope,
        expectedRaw,
        now,
        lease,
      ),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { ok: false, reason: locked.reason === "busy" ? "busy" : "unavailable" };
}

export async function withActivityRecoveryLock<T>(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  task: (lease: OnboardingRecoveryLease) => Promise<T> | T,
  lockManager = browserOnboardingLockManager(),
): Promise<OnboardingRecoveryLockResult<T>> {
  return withOnboardingRecoveryLock(
    storage,
    { kind: "onboarding", personId: scope.personId },
    task,
    lockManager,
  );
}

export function readActivityLocalDraft(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  now = Date.now(),
): LocalDraftReadResult<ActivityDraftEnvelope> {
  if (typeof window !== "undefined") return { status: "unavailable" };
  const result = readActivityLocalDraftRawCore(storage, scope, now);
  if (result.status === "ready" || result.status === "missing") return result;
  return { status: result.status };
}

function readActivityLocalDraftRawCore(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  now: number,
): LocalDraftRecoveryReadResult<ActivityDraftEnvelope> {
  const key = activityKey(scope);
  const stored = readStored(storage, key);
  if (stored.status === "missing" || stored.status === "unavailable") {
    return stored;
  }
  if (stored.status === "invalid") {
    return { status: "invalid", cleanupTarget: { raw: stored.raw } };
  }
  if (!isRecord(stored.value)) {
    return { status: "invalid", cleanupTarget: { raw: stored.raw } };
  }
  const record = stored.value;
  if (isExpired(record, now)) {
    return { status: "expired", cleanupTarget: { raw: stored.raw } };
  }
  if (
    !validEnvelopeMetadata(record, LEGACY_LOCAL_DRAFT_VERSION, now) ||
    !sameActivityScope(record.scope, scope) ||
    !isRecord(record.draft) ||
    typeof record.draft.response !== "string"
  ) {
    return { status: "invalid", cleanupTarget: { raw: stored.raw } };
  }
  return {
    status: "ready",
    envelope: record as ActivityDraftEnvelope,
  };
}

function purgeActivityLocalDraftIfMatchesCore(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  expectedRaw: LocalDraftRawSnapshot,
  now: number,
  lease?: OnboardingRecoveryLease,
): ConditionalLocalDraftStorageResult {
  if (
    lease &&
    (!activeOnboardingLeases.has(lease) || lease.personId !== scope.personId)
  ) {
    return { ok: false, reason: "unavailable" };
  }
  if (!storage) return { ok: false, reason: "unavailable" };
  const stored = readStored(storage, activityKey(scope));
  if (stored.status === "missing") return { ok: true };
  if (stored.status === "unavailable") {
    return { ok: false, reason: "unavailable" };
  }
  if (stored.raw !== expectedRaw.raw) {
    return { ok: false, reason: "changed" };
  }
  const confirmed = readStored(storage, activityKey(scope));
  if (
    confirmed.status === "missing" ||
    confirmed.status === "unavailable" ||
    confirmed.raw !== expectedRaw.raw
  ) {
    return {
      ok: false,
      reason: confirmed.status === "unavailable" ? "unavailable" : "changed",
    };
  }
  if (confirmed.status === "invalid")
    return removeStored(storage, activityKey(scope));
  if (!isRecord(confirmed.value))
    return removeStored(storage, activityKey(scope));
  const record = confirmed.value;
  const valid =
    validEnvelopeMetadata(record, LEGACY_LOCAL_DRAFT_VERSION, now) &&
    sameActivityScope(record.scope, scope) &&
    isRecord(record.draft) &&
    typeof record.draft.response === "string";
  if (valid && !isExpired(record, now)) {
    return { ok: false, reason: "changed" };
  }
  return removeStored(storage, activityKey(scope));
}

function activityRecoveryReadAfterPurge(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  initial: LocalDraftRecoveryReadResult<ActivityDraftEnvelope>,
  now: number,
  lease: OnboardingRecoveryLease,
): LocalDraftRecoveryReadResult<ActivityDraftEnvelope> {
  if (initial.status !== "expired" && initial.status !== "invalid") {
    return initial;
  }
  const purged = purgeActivityLocalDraftIfMatchesCore(
    storage,
    scope,
    initial.cleanupTarget,
    now,
    lease,
  );
  if (purged.ok) return { status: "missing" };
  if (purged.reason === "changed") {
    const current = readActivityLocalDraftRawCore(storage, scope, now);
    if (current.status === "ready" || current.status === "missing") {
      return current;
    }
    if (current.status === "expired" || current.status === "invalid") {
      return { ...current, cleanupStatus: "changed" };
    }
    return current;
  }
  return { ...initial, cleanupStatus: "unavailable" };
}

export function writeActivityLocalDraft(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
): LocalDraftStorageResult {
  if (typeof window !== "undefined")
    return { ok: false, reason: "unavailable" };
  return writeActivityLocalDraftCore(storage, input);
}

function writeActivityLocalDraftCoreWithEnvelope(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
  lease?: OnboardingRecoveryLease,
): LockedActivityLocalDraftWrite {
  if (
    lease &&
    (!activeOnboardingLeases.has(lease) ||
      lease.personId !== input.scope.personId)
  ) {
    return {
      result: { ok: false, reason: "unavailable" },
      envelope: null,
    };
  }
  const now = input.now ?? Date.now();
  const key = activityKey(input.scope);
  const createdAt = existingCreatedAt(storage, key, now);
  if (createdAt === null) {
    return {
      result: { ok: false, reason: "unavailable" },
      envelope: null,
    };
  }
  const envelope = {
    version: LEGACY_LOCAL_DRAFT_VERSION,
    scope: input.scope,
    baseRevision: input.baseRevision,
    serverFingerprint: input.serverFingerprint,
    ...envelopeTimes(now, createdAt),
    draft: { response: input.response },
  } satisfies ActivityDraftEnvelope;
  const result = setStored(storage, key, envelope);
  return { result, envelope: result.ok ? envelope : null };
}

function writeActivityLocalDraftCore(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
  lease?: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  return writeActivityLocalDraftCoreWithEnvelope(storage, input, lease).result;
}

export function clearActivityLocalDraft(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
): LocalDraftStorageResult {
  if (typeof window !== "undefined")
    return { ok: false, reason: "unavailable" };
  return removeStored(storage, activityKey(scope));
}

export async function readActivityLocalDraftWithLock(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftRecoveryReadResult<ActivityDraftEnvelope>> {
  const locked = await withActivityRecoveryLock(
    storage,
    scope,
    (lease) => {
      if (!activeOnboardingLeases.has(lease)) {
        return { status: "unavailable" as const };
      }
      const raw = readActivityLocalDraftRawCore(storage, scope, now);
      return activityRecoveryReadAfterPurge(storage, scope, raw, now, lease);
    },
    lockManager,
  );
  return locked.ok ? locked.value : { status: "unavailable" };
}

export async function purgeActivityLocalDraftIfMatchesWithLock(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  expectedRaw: LocalDraftRawSnapshot,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<ConditionalLocalDraftStorageResult> {
  const locked = await withActivityRecoveryLock(
    storage,
    scope,
    (lease) =>
      purgeActivityLocalDraftIfMatchesCore(
        storage,
        scope,
        expectedRaw,
        now,
        lease,
      ),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { ok: false, reason: locked.reason === "busy" ? "busy" : "unavailable" };
}

export async function writeActivityLocalDraftWithLock(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftStorageResult> {
  const locked = await withActivityRecoveryLock(
    storage,
    input.scope,
    (lease) => writeActivityLocalDraftCore(storage, input, lease),
    lockManager,
  );
  return locked.ok ? locked.value : { ok: false, reason: "unavailable" };
}

/**
 * Writes an activity recovery copy and returns its exact envelope from the
 * same lock section. Save and submit operations use this ownership token for
 * post-server conditional cleanup.
 */
export async function writeActivityLocalDraftWithLockAndEnvelope(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LockedActivityLocalDraftWrite> {
  const locked = await withActivityRecoveryLock(
    storage,
    input.scope,
    (lease) => writeActivityLocalDraftCoreWithEnvelope(storage, input, lease),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { result: { ok: false, reason: "unavailable" }, envelope: null };
}

export function writeActivityLocalDraftWithLease(
  storage: StorageLike | null,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
  lease: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  return writeActivityLocalDraftCore(storage, input, lease);
}

function clearActivityLocalDraftIfMatchesCore(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  expected: ActivityDraftEnvelope | null,
  now: number,
  lease?: OnboardingRecoveryLease,
): ConditionalLocalDraftStorageResult {
  if (
    lease &&
    (!activeOnboardingLeases.has(lease) || lease.personId !== scope.personId)
  ) {
    return { ok: false, reason: "unavailable" };
  }
  if (!storage) return { ok: false, reason: "unavailable" };
  const stored = readStored(storage, activityKey(scope));
  if (stored.status === "missing") return { ok: true };
  if (stored.status !== "value" || !isRecord(stored.value)) {
    return { ok: false, reason: "changed" };
  }
  if (!expected) return { ok: false, reason: "changed" };
  const record = stored.value;
  const matches =
    validEnvelopeMetadata(record, LEGACY_LOCAL_DRAFT_VERSION, now) &&
    sameActivityScope(record.scope, scope) &&
    isRecord(record.draft) &&
    typeof record.draft.response === "string" &&
    stableSerialize(record) === stableSerialize(expected);
  if (!matches) return { ok: false, reason: "changed" };
  return removeStored(storage, activityKey(scope));
}

export async function clearActivityLocalDraftIfMatchesWithLock(
  storage: StorageLike | null,
  scope: ActivityDraftScope,
  expected: ActivityDraftEnvelope | null,
  now = Date.now(),
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<ConditionalLocalDraftStorageResult> {
  const locked = await withActivityRecoveryLock(
    storage,
    scope,
    (lease) =>
      clearActivityLocalDraftIfMatchesCore(
        storage,
        scope,
        expected,
        now,
        lease,
      ),
    lockManager,
  );
  return locked.ok
    ? locked.value
    : { ok: false, reason: locked.reason === "busy" ? "busy" : "unavailable" };
}

export function clearAllLearnerLocalDrafts(
  storage: StorageLike | null,
): LocalDraftStorageResult {
  if (!storage) return { ok: false, reason: "unavailable" };
  // Broad browser purges must use the locked async operation. The legacy sync
  // entry point fails closed so callers cannot remove onboarding data outside
  // the Web Locks critical section.
  if (typeof window !== "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  return clearAllLearnerLocalDraftsCore(storage);
}

function clearAllLearnerLocalDraftsCore(
  storage: StorageLike | null,
  lease?: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  if (!storage) return { ok: false, reason: "unavailable" };
  if (
    lease &&
    !ownsOnboardingRecoveryLease(lease, {
      kind: "onboarding",
      personId: "*",
    })
  ) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(`${LOCAL_DRAFT_PREFIX}:`)) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

export async function clearAllLearnerLocalDraftsWithLock(
  storage: StorageLike | null,
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftStorageResult> {
  if (!storage) return { ok: false, reason: "unavailable" };
  const scope: OnboardingDraftScope = { kind: "onboarding", personId: "*" };
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) => clearAllLearnerLocalDraftsCore(storage, lease),
    lockManager,
  );
  return locked.ok ? locked.value : { ok: false, reason: "unavailable" };
}

function activityKeyBelongsToPerson(key: string, personId: string): boolean {
  const prefix = `${LOCAL_DRAFT_PREFIX}:activity:`;
  if (!key.startsWith(prefix)) return false;
  const segments = key.slice(prefix.length).split(":");
  return segments[1] === encodeURIComponent(personId);
}

export function clearLearnerLocalDraftsForPerson(
  storage: StorageLike | null,
  personId: string | null | undefined,
): LocalDraftStorageResult {
  if (!storage || !personId) return { ok: false, reason: "unavailable" };
  if (typeof window !== "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  return clearLearnerLocalDraftsForPersonCore(storage, personId);
}

function clearLearnerLocalDraftsForPersonCore(
  storage: StorageLike | null,
  personId: string,
  lease?: OnboardingRecoveryLease,
): LocalDraftStorageResult {
  if (!storage) return { ok: false, reason: "unavailable" };
  if (
    lease &&
    !ownsOnboardingRecoveryLease(lease, {
      kind: "onboarding",
      personId,
    })
  ) {
    return { ok: false, reason: "unavailable" };
  }
  try {
    const onboardingDraftKey = onboardingKey(personId);
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (
        key === onboardingDraftKey ||
        (key !== null && activityKeyBelongsToPerson(key, personId))
      ) {
        keys.push(key);
      }
    }
    for (const key of keys) storage.removeItem(key);
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

export async function clearLearnerLocalDraftsForPersonWithLock(
  storage: StorageLike | null,
  personId: string | null | undefined,
  lockManager?: OnboardingRecoveryLockManager | null,
): Promise<LocalDraftStorageResult> {
  if (!storage || !personId) return { ok: false, reason: "unavailable" };
  const scope: OnboardingDraftScope = { kind: "onboarding", personId };
  const locked = await withOnboardingRecoveryLock(
    storage,
    scope,
    (lease) => clearLearnerLocalDraftsForPersonCore(storage, personId, lease),
    lockManager,
  );
  return locked.ok ? locked.value : { ok: false, reason: "unavailable" };
}

export function onboardingRecoveryText(draft: OnboardingLocalDraft): string {
  return [
    "Authority Closers learner profile recovery copy",
    `Experience context: ${draft.experienceContext}`,
    `Learning goal: ${draft.learningGoal}`,
    `Practice situation: ${draft.practiceSituation}`,
    `Weekly minutes: ${draft.weeklyMinutes}`,
  ].join("\n");
}

export function activityRecoveryText(response: string): string {
  return ["Authority Closers activity recovery copy", "", response].join("\n");
}

export type MutationFailureKind = "conflict" | "offline" | "session" | "retry";

export function availableLocalStorage(owner: {
  readonly localStorage: Storage;
}): Storage | null {
  try {
    return owner.localStorage;
  } catch {
    return null;
  }
}

function isOnboardingLocalStep(value: unknown): value is OnboardingLocalStep {
  return value === 1 || value === 2 || value === 3;
}

export function mutationFailureKind(
  error: unknown,
  online: boolean,
): MutationFailureKind {
  if (error instanceof ApiError && error.status === 409) return "conflict";
  if (error instanceof ApiError && error.status === 401) return "session";
  if (!online || error instanceof TypeError) return "offline";
  return "retry";
}

export function registerBeforeUnloadGuard(
  target: BeforeUnloadTarget,
  dirty: boolean,
): () => void {
  if (!dirty) return () => undefined;
  const listener: EventListener = (event) => {
    event.preventDefault();
    (event as BeforeUnloadEvent).returnValue = "";
  };
  target.addEventListener("beforeunload", listener);
  return () => target.removeEventListener("beforeunload", listener);
}

export function registerInternalNavigationGuard(
  target: ClickGuardTarget,
  active: boolean,
  confirmNavigation: () => boolean,
): () => void {
  if (!active) return () => undefined;
  const listener: EventListener = (rawEvent) => {
    const event = rawEvent as MouseEvent;
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    const eventTarget = event.target;
    if (!(eventTarget instanceof Element)) return;
    const anchor = eventTarget.closest("a[href]");
    if (!(anchor instanceof HTMLAnchorElement)) return;
    if (anchor.target && anchor.target !== "_self") return;
    const destination = new URL(anchor.href, window.location.href);
    if (destination.origin !== window.location.origin) return;
    if (confirmNavigation()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  target.addEventListener("click", listener, true);
  return () => target.removeEventListener("click", listener, true);
}

export function registerHistoryNavigationGuard(
  target: HistoryNavigationGuardTarget,
  active: boolean,
  confirmNavigation: () => boolean,
): () => void {
  if (!active) return () => undefined;
  const guardedHref = target.location.href;
  const guardedState = target.history.state;
  const popstateListener: EventListener = (event) => {
    if (confirmNavigation()) return;
    event.stopImmediatePropagation();
    target.history.pushState(guardedState, "", guardedHref);
  };
  const navigateListener: EventListener = (event) => {
    if (!event.cancelable || confirmNavigation()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  target.addEventListener("popstate", popstateListener, true);
  target.navigation?.addEventListener("navigate", navigateListener);
  return () => {
    target.removeEventListener("popstate", popstateListener, true);
    target.navigation?.removeEventListener("navigate", navigateListener);
  };
}
