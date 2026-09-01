import { ApiError } from "./learner-api";

export type OnboardingLocalDraft = {
  experienceContext: string;
  learningGoal: string;
  practiceSituation: string;
  weeklyMinutes: string;
};

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

export type LocalDraftEnvelope<TDraft, TScope> = {
  version: 2;
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
  OnboardingDraftScope
>;

export type ActivityDraftEnvelope = LocalDraftEnvelope<
  { response: string },
  ActivityDraftScope
>;

export type LocalDraftReadResult<TEnvelope> =
  | { status: "missing" }
  | { status: "ready"; envelope: TEnvelope }
  | { status: "expired" }
  | { status: "invalid" }
  | { status: "unavailable" };

export type LocalDraftStorageResult =
  | { ok: true }
  | { ok: false; reason: "quota" | "unavailable" };

type StorageLike = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem" | "key" | "length"
>;

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

const LOCAL_DRAFT_VERSION = 2;
const LOCAL_DRAFT_PREFIX = "ac-learner-local-draft";

/**
 * Local learner drafts are a recovery cache, not canonical learning records.
 * Seven days gives an interrupted learner a bounded recovery window; successful
 * server saves, sign-out, membership loss, or expiry remove the local copy.
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
  storage: StorageLike,
  key: string,
  value: unknown,
): LocalDraftStorageResult {
  try {
    storage.setItem(key, JSON.stringify(value));
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

function removeStored(
  storage: StorageLike,
  key: string,
): LocalDraftStorageResult {
  try {
    storage.removeItem(key);
    return { ok: true };
  } catch (error) {
    return storageFailure(error);
  }
}

function readStored(
  storage: StorageLike,
  key: string,
):
  | { status: "missing" }
  | { status: "value"; value: unknown }
  | { status: "invalid" }
  | { status: "unavailable" } {
  try {
    const stored = storage.getItem(key);
    if (stored === null) return { status: "missing" };
    try {
      return { status: "value", value: JSON.parse(stored) as unknown };
    } catch {
      return { status: "invalid" };
    }
  } catch {
    return { status: "unavailable" };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function validEnvelopeMetadata(record: Record<string, unknown>): boolean {
  return (
    record.version === LOCAL_DRAFT_VERSION &&
    typeof record.baseRevision === "number" &&
    Number.isInteger(record.baseRevision) &&
    record.baseRevision >= 0 &&
    typeof record.serverFingerprint === "string" &&
    record.serverFingerprint.length > 0 &&
    typeof record.createdAt === "string" &&
    Number.isFinite(Date.parse(record.createdAt)) &&
    typeof record.updatedAt === "string" &&
    Number.isFinite(Date.parse(record.updatedAt)) &&
    typeof record.expiresAt === "string" &&
    Number.isFinite(Date.parse(record.expiresAt))
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
  storage: StorageLike,
  key: string,
): string | undefined {
  const stored = readStored(storage, key);
  if (stored.status !== "value" || !isRecord(stored.value)) return undefined;
  return typeof stored.value.createdAt === "string"
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
  storage: StorageLike,
  scope: OnboardingDraftScope,
  now = Date.now(),
): LocalDraftReadResult<OnboardingDraftEnvelope> {
  const key = onboardingKey(scope.personId);
  const stored = readStored(storage, key);
  if (stored.status !== "value") return stored;
  if (!isRecord(stored.value)) return { status: "invalid" };
  const record = stored.value;
  if (isExpired(record, now)) {
    removeStored(storage, key);
    return { status: "expired" };
  }
  if (
    !validEnvelopeMetadata(record) ||
    !sameOnboardingScope(record.scope, scope) ||
    !isOnboardingDraft(record.draft)
  ) {
    removeStored(storage, key);
    return { status: "invalid" };
  }
  return {
    status: "ready",
    envelope: record as OnboardingDraftEnvelope,
  };
}

export function writeOnboardingLocalDraft(
  storage: StorageLike,
  input: {
    scope: OnboardingDraftScope;
    draft: OnboardingLocalDraft;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
): LocalDraftStorageResult {
  const now = input.now ?? Date.now();
  const key = onboardingKey(input.scope.personId);
  return setStored(storage, key, {
    version: LOCAL_DRAFT_VERSION,
    scope: input.scope,
    baseRevision: input.baseRevision,
    serverFingerprint: input.serverFingerprint,
    ...envelopeTimes(now, existingCreatedAt(storage, key)),
    draft: input.draft,
  } satisfies OnboardingDraftEnvelope);
}

export function clearOnboardingLocalDraft(
  storage: StorageLike,
  scope: OnboardingDraftScope,
): LocalDraftStorageResult {
  return removeStored(storage, onboardingKey(scope.personId));
}

export function readActivityLocalDraft(
  storage: StorageLike,
  scope: ActivityDraftScope,
  now = Date.now(),
): LocalDraftReadResult<ActivityDraftEnvelope> {
  const key = activityKey(scope);
  const stored = readStored(storage, key);
  if (stored.status !== "value") return stored;
  if (!isRecord(stored.value)) return { status: "invalid" };
  const record = stored.value;
  if (isExpired(record, now)) {
    removeStored(storage, key);
    return { status: "expired" };
  }
  if (
    !validEnvelopeMetadata(record) ||
    !sameActivityScope(record.scope, scope) ||
    !isRecord(record.draft) ||
    typeof record.draft.response !== "string"
  ) {
    removeStored(storage, key);
    return { status: "invalid" };
  }
  return {
    status: "ready",
    envelope: record as ActivityDraftEnvelope,
  };
}

export function writeActivityLocalDraft(
  storage: StorageLike,
  input: {
    scope: ActivityDraftScope;
    response: string;
    baseRevision: number;
    serverFingerprint: string;
    now?: number;
  },
): LocalDraftStorageResult {
  const now = input.now ?? Date.now();
  const key = activityKey(input.scope);
  return setStored(storage, key, {
    version: LOCAL_DRAFT_VERSION,
    scope: input.scope,
    baseRevision: input.baseRevision,
    serverFingerprint: input.serverFingerprint,
    ...envelopeTimes(now, existingCreatedAt(storage, key)),
    draft: { response: input.response },
  } satisfies ActivityDraftEnvelope);
}

export function clearActivityLocalDraft(
  storage: StorageLike,
  scope: ActivityDraftScope,
): LocalDraftStorageResult {
  return removeStored(storage, activityKey(scope));
}

export function clearAllLearnerLocalDrafts(
  storage: StorageLike,
): LocalDraftStorageResult {
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
