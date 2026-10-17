"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { UsersRound, X } from "lucide-react";
import { ActionButton } from "@ac/ui";

import { ACQUISITION, UUID, record } from "./acquisition-client";
import { voicesOf } from "./call-data";
import { callLabelEtag } from "./call-label";
import type { Transcript } from "./report-contract";
import { getShellState } from "./shell/shell-store";
import { SpeakerAvatar } from "./speaker-avatar";
import {
  MAX_SPEAKER_NAME,
  SpeakerProfilesContext,
  clearSpeakerProfiles,
  readSpeakerProfiles,
  ROLE_WORDS,
  speakerName,
  voiceStyle,
  type SpeakerProfile,
  type SpeakerProfiles,
  type SpeakerRole,
} from "./speaker-profiles";
import styles from "./speaker.module.css";

const CARD_ROLES: readonly SpeakerRole[] = [
  "you",
  "salesperson",
  "prospect",
  "other",
];
/** Roles only one speaker can hold: choosing one that is taken swaps them. */
const ONE_ONLY = new Set<SpeakerRole>(["you", "prospect"]);

/** The first thing each voice said, so people can tell who is who. */
function firstLines(transcript: Transcript | undefined) {
  const lines = new Map<string, string>();
  for (const segment of transcript?.segments ?? []) {
    const id = segment.speaker_id;
    const text = segment.text.replace(/\s+/g, " ").trim();
    if (id && !lines.has(id) && text.length >= 8)
      lines.set(id, text.length > 90 ? `${text.slice(0, 88)}…` : text);
  }
  return lines;
}

type SpeakerMap = {
  etag: string;
  available: boolean;
  profiles: SpeakerProfiles;
  drafts: SpeakerProfiles;
};
const ROLES = new Set(["you", "salesperson", "prospect", "other"]);
const STATUSES = new Set([
  "unavailable",
  "predicted",
  "confirmed",
  "channel",
  "model_named",
]);
const SAVE_ERROR =
  "Couldn’t save speaker details. Check your connection and try again.";
const CONFLICT =
  "Speaker details changed elsewhere. Review the roles and save again, or reopen the editor to use the latest details.";

async function requestMap(
  callId: string,
  transcriptRevision: string,
  signal: AbortSignal,
  previous?: SpeakerMap,
  changes?: SpeakerProfiles,
): Promise<SpeakerMap> {
  const response = await fetch(
    `${ACQUISITION}/submissions/${callId}/speaker-map`,
    {
      method: changes ? "PUT" : "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: {
        accept: "application/json",
        ...(changes && previous
          ? { "content-type": "application/json", "If-Match": previous.etag }
          : {}),
      },
      body: changes
        ? JSON.stringify({
            transcript_revision: transcriptRevision,
            speakers: Object.keys(previous!.drafts).map((speaker_id) => {
              const profile =
                changes[speaker_id] ?? previous!.drafts[speaker_id];
              return {
                speaker_id,
                role: profile.role,
                display_name: profile.name.trim() || null,
                icon: profile.icon,
              };
            }),
          })
        : undefined,
    },
  );
  if (!response.ok) throw response.status;
  const data = record(await response.json());
  // The edge proxy compresses larger replies and marks the tag (`"…-gzip"`,
  // `W/"…"`), so a populated map arrived "wrong" and naming broke (AUT-1276).
  // The body's revision decides; If-Match always sends the strong tag.
  const header = (response.headers.get("etag") ?? "")
    .replace(/^W\//, "")
    .replace(/-(?:gzip|zstd|br|deflate)"$/, '"');
  if (
    data.schema !== "ac.sales-xray.speaker-map/1" ||
    data.submission_id !== callId ||
    !STATUSES.has(data.status as string) ||
    !Number.isInteger(data.user_revision) ||
    (data.user_revision as number) < 0 ||
    (header !== "" && header !== callLabelEtag(data.user_revision as number)) ||
    !Array.isArray(data.speakers) ||
    data.speakers.length > 32
  )
    throw new Error("speaker_map_response");
  const available = data.status !== "unavailable" && data.speakers.length > 0;
  // A missing retained transcript has a null revision and no speaker map.
  // Populated maps must still belong to the transcript shown by this report.
  if (
    data.transcript_revision !== transcriptRevision &&
    (available || data.transcript_revision !== null)
  )
    throw new Error("speaker_map_response");
  const drafts: Record<string, SpeakerProfiles[string]> = Object.create(null);
  const profiles: Record<string, SpeakerProfiles[string]> = Object.create(null);
  for (const value of available ? data.speakers : []) {
    const row = record(value);
    if (
      typeof row.speaker_id !== "string" ||
      !row.speaker_id ||
      Object.hasOwn(drafts, row.speaker_id) ||
      (row.role !== null && !ROLES.has(row.role as string)) ||
      (row.display_name !== null && typeof row.display_name !== "string") ||
      (row.icon != null &&
        (typeof row.icon !== "string" ||
          !/^[a-z][a-z0-9-]{0,63}$/.test(row.icon)))
    )
      throw new Error("speaker_map_response");
    const profile = {
      name: (row.display_name as string | null) ?? "",
      role: row.role as SpeakerRole | null,
      icon: (row.icon as string | undefined) ?? null,
    };
    drafts[row.speaker_id] = profile;
    // Predictions can prefill confirmation; measured signals require known roles.
    profiles[row.speaker_id] = {
      ...profile,
      role:
        row.role_source === "confirmed" || row.role_source === "channel"
          ? profile.role
          : null,
    };
    if (row.speaker_id === "unattributed")
      drafts[row.speaker_id] = { name: "", role: "other", icon: null };
  }
  if (
    changes &&
    (!available ||
      data.status !== "confirmed" ||
      Object.keys(drafts).length !== Object.keys(changes).length ||
      Object.entries(changes).some(
        ([id, profile]) => !drafts[id] || drafts[id].role !== profile.role,
      ))
  )
    throw new Error("speaker_map_unconfirmed");
  return {
    etag: callLabelEtag(data.user_revision as number),
    available,
    profiles,
    drafts,
  };
}

/** Key this provider by call, transcript and authenticated session. No shared cache. */
export function SpeakerServerProfiles({
  callId,
  transcriptRevision,
  enabled,
  transcript,
  children,
}: {
  callId: string | null;
  transcriptRevision: string;
  enabled: boolean;
  /** The report's transcript: voice colours, order and first lines for the card. */
  transcript?: Transcript;
  children: ReactNode;
}) {
  const [map, setMap] = useState<SpeakerMap | null>(null);
  const [legacy] = useState(() => (enabled ? readSpeakerProfiles(callId) : {}));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
  // "Not now" on the detected-speakers card, for this call in this visit.
  const [laterFor, setLaterFor] = useState<string | null>(null);
  // The card's Change mode: the roles and names being edited.
  const [changing, setChanging] = useState<Record<
    string,
    SpeakerProfile
  > | null>(null);
  const voices = useMemo(
    () => (transcript ? voicesOf(transcript) : []),
    [transcript],
  );
  const lines = useMemo(() => firstLines(transcript), [transcript]);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const validCall = enabled && callId !== null && UUID.test(callId);

  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    if (validCall)
      void requestMap(callId!, transcriptRevision, abort.signal)
        .then((next) => {
          if (!abort.signal.aborted) {
            setMap(next);
            setError(null);
          }
        })
        .catch(() => {
          // Owner 5 Oct: a missing or not-yet-built speaker map must never
          // cover the report with an error; the report renders without names
          // and save failures still surface (AUT-1193 aligns the contract).
          if (!abort.signal.aborted) setMap(null);
        });
    return () => abort.abort();
  }, [callId, transcriptRevision, validCall, retry]);

  const drafts =
    validCall && map
      ? Object.fromEntries(
          Object.entries(map.drafts).map(([id, profile]) => [
            id,
            id !== "unattributed" && map.etag === '"call-label-0"' && legacy[id]
              ? legacy[id]
              : profile,
          ]),
        )
      : {};
  const predicted = Object.entries(drafts).filter(
    ([id]) => id !== "unattributed",
  );
  const needsConfirmation =
    validCall &&
    map?.available &&
    predicted.some(([id, profile]) => profile.role && !map.profiles[id]?.role);
  const completeSuggestion =
    predicted.length > 1 &&
    predicted.every(([, profile]) => profile.role !== null) &&
    predicted.filter(
      ([, profile]) => profile.role === "you" || profile.role === "salesperson",
    ).length === 1 &&
    predicted.filter(([, profile]) => profile.role === "prospect").length === 1;

  async function save(changes: SpeakerProfiles) {
    const signal = controller.current?.signal;
    if (
      !validCall ||
      !map?.available ||
      !signal ||
      signal.aborted ||
      inFlight.current
    )
      return false;
    const next = { ...map.drafts, ...changes };
    if (
      Object.keys(changes).some((id) => !Object.hasOwn(map.drafts, id)) ||
      Object.values(next).some((profile) => profile.role === null) ||
      Object.entries(map.profiles).some(
        ([id, profile]) =>
          id !== "unattributed" &&
          profile.role === null &&
          !Object.hasOwn(changes, id),
      ) ||
      Object.values(next).filter((profile) => profile.role === "you").length > 1
    ) {
      setError(
        "Choose a role for every speaker, with at most one You. Open a speaker to review the full list.",
      );
      return false;
    }
    inFlight.current = true;
    setSaving(true);
    setError(null);
    try {
      const confirmed = await requestMap(
        callId!,
        transcriptRevision,
        signal,
        map,
        next,
      );
      if (signal.aborted) return false;
      setMap(confirmed);
      clearSpeakerProfiles(callId!);
      return true;
    } catch (caught) {
      if (signal.aborted) return false;
      if (caught === 409) {
        try {
          const latest = await requestMap(callId!, transcriptRevision, signal);
          if (!signal.aborted) setMap(latest);
        } catch {
          /* Keep the last confirmed display and the unsaved editor. */
        }
      }
      if (!signal.aborted) {
        if (caught === 401 || caught === 403 || caught === 404) setMap(null);
        setError(caught === 409 ? CONFLICT : SAVE_ERROR);
      }
      return false;
    } finally {
      inFlight.current = false;
      if (!signal.aborted) setSaving(false);
    }
  }

  const showCard =
    Boolean(needsConfirmation && completeSuggestion) && laterFor !== callId;
  const accountName = getShellState().profileName;
  const voiceOf = (id: string) => {
    const at = voices.indexOf(id);
    return at >= 0 ? at : predicted.findIndex(([other]) => other === id);
  };
  const shownRows: Array<[string, SpeakerProfile]> = changing
    ? predicted.map(([id]) => [id, changing[id]])
    : predicted;
  const choose = (id: string, role: SpeakerRole) =>
    setChanging((current) => {
      if (!current) return current;
      const before = current[id].role;
      const next = { ...current, [id]: { ...current[id], role } };
      // Two people can't both be the prospect (or you): picking a taken role
      // gives the other speaker this one's old role, so a swap is one tap.
      if (ONE_ONLY.has(role))
        for (const [other, profile] of Object.entries(next))
          if (other !== id && profile.role === role)
            next[other] = { ...profile, role: before };
      return next;
    });
  const rename = (id: string, name: string) =>
    setChanging((current) =>
      current
        ? {
            ...current,
            [id]: { ...current[id], name: name.slice(0, MAX_SPEAKER_NAME) },
          }
        : current,
    );

  return (
    <SpeakerProfilesContext.Provider
      value={{
        callId,
        profiles: validCall ? (map?.profiles ?? {}) : {},
        drafts,
        save,
        canSave: validCall && map?.available === true && !saving,
        error,
        server: true,
      }}
    >
      {/* While the card asks, a save problem shows inside it, not above the report. */}
      {error && !showCard && (
        <p role="alert">
          {error}
          {!map && validCall && (
            <>
              {" "}
              <ActionButton
                variant="quiet"
                onClick={() => setRetry((n) => n + 1)}
              >
                Reload speaker details
              </ActionButton>
            </>
          )}
        </p>
      )}
      {validCall && map && !map.available && (
        <div className={styles.mapNotice}>
          <span>Speaker names not set yet.</span>
          <ActionButton variant="quiet" onClick={() => setRetry((n) => n + 1)}>
            Reload speaker details
          </ActionButton>
        </div>
      )}
      {/* A floating corner card (owner, 17 Oct): it arrives after the report
          and never pushes it down. 18 Oct: "pretty shit UI" with raw
          speaker_0 ids; it now shows each voice's name, role and first line,
          asks one question, and offers Confirm or Change. */}
      {showCard && (
        <div
          className={styles.detected}
          role="region"
          aria-label="Detected speakers"
          data-changing={changing ? "" : undefined}
        >
          <div className={styles.detectedHead}>
            <span className={styles.detectedIcon} aria-hidden="true">
              <UsersRound size={16} />
            </span>
            <p className={styles.detectedTitle}>
              {changing
                ? "Who is who on this call?"
                : "Did we get the speakers right?"}
            </p>
            <button
              type="button"
              className={styles.detectedClose}
              aria-label="Not now"
              title="Not now"
              disabled={saving}
              onClick={() => {
                setChanging(null);
                setLaterFor(callId);
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <ul className={styles.detectedList}>
            {shownRows.map(([id, profile]) => {
              const voice = voiceOf(id);
              const label = speakerName(voice, profile, accountName);
              const line = lines.get(id);
              return (
                <li key={id} style={voiceStyle(voice)}>
                  <SpeakerAvatar
                    voice={voice}
                    profile={profile}
                    youName={accountName}
                    size={28}
                  />
                  {changing ? (
                    <input
                      className={styles.detectedName}
                      value={profile.name}
                      placeholder={`Speaker ${voice + 1}`}
                      maxLength={MAX_SPEAKER_NAME}
                      aria-label={`Name for speaker ${voice + 1}`}
                      onChange={(event) => rename(id, event.target.value)}
                    />
                  ) : (
                    <span className={styles.detectedWho}>
                      <strong>{label}</strong>
                      {line ? <q>{line}</q> : null}
                    </span>
                  )}
                  {changing ? (
                    <div
                      className={styles.detectedRoles}
                      role="group"
                      aria-label={`Role for speaker ${voice + 1}`}
                    >
                      {CARD_ROLES.map((role) => (
                        <button
                          key={role}
                          type="button"
                          aria-pressed={profile.role === role}
                          onClick={() => choose(id, role)}
                        >
                          {ROLE_WORDS[role]}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <span className={styles.detectedRole}>
                      {ROLE_WORDS[profile.role!]}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {error ? (
            <p className={styles.detectedError} role="alert">
              {error}
            </p>
          ) : null}
          <div className={styles.detectedActions}>
            <button
              type="button"
              className={styles.detectedPrimary}
              disabled={saving}
              onClick={() =>
                void save(changing ?? drafts).then((saved) => {
                  if (saved) setChanging(null);
                })
              }
            >
              {saving ? "Saving…" : changing ? "Save" : "Confirm"}
            </button>
            <button
              type="button"
              className={styles.detectedSecondary}
              disabled={saving}
              onClick={() =>
                setChanging(changing ? null : Object.fromEntries(predicted))
              }
            >
              {changing ? "Cancel" : "Change"}
            </button>
          </div>
        </div>
      )}
      {children}
    </SpeakerProfilesContext.Provider>
  );
}
