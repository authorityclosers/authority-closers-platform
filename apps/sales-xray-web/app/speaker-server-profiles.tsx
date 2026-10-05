"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { ACQUISITION, UUID, record } from "./acquisition-client";
import {
  SpeakerProfilesContext,
  clearSpeakerProfiles,
  readSpeakerProfiles,
  type SpeakerProfiles,
  type SpeakerRole,
} from "./speaker-profiles";

type SpeakerMap = {
  etag: string;
  profiles: SpeakerProfiles;
  drafts: SpeakerProfiles;
};
const ROLES = new Set(["you", "salesperson", "prospect", "other"]);
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
  const etag = response.headers.get("etag");
  if (
    data.schema !== "ac.sales-xray.speaker-map/1" ||
    data.submission_id !== callId ||
    data.transcript_revision !== transcriptRevision ||
    !Number.isInteger(data.user_revision) ||
    (data.user_revision as number) < 0 ||
    etag !== `"call-label-${data.user_revision}"` ||
    !Array.isArray(data.speakers) ||
    !data.speakers.length ||
    data.speakers.length > 32
  )
    throw new Error("speaker_map_response");
  const drafts: Record<string, SpeakerProfiles[string]> = Object.create(null);
  const profiles: Record<string, SpeakerProfiles[string]> = Object.create(null);
  for (const value of data.speakers) {
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
    (data.status !== "confirmed" ||
      Object.keys(drafts).length !== Object.keys(changes).length ||
      Object.entries(changes).some(
        ([id, profile]) => !drafts[id] || drafts[id].role !== profile.role,
      ))
  )
    throw new Error("speaker_map_unconfirmed");
  return { etag, profiles, drafts };
}

/** Key this provider by call, transcript and authenticated session. No shared cache. */
export function SpeakerServerProfiles({
  callId,
  transcriptRevision,
  enabled,
  children,
}: {
  callId: string | null;
  transcriptRevision: string;
  enabled: boolean;
  children: ReactNode;
}) {
  const [map, setMap] = useState<SpeakerMap | null>(null);
  const [legacy] = useState(() => (enabled ? readSpeakerProfiles(callId) : {}));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
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

  async function save(changes: SpeakerProfiles) {
    const signal = controller.current?.signal;
    if (!validCall || !map || !signal || signal.aborted || inFlight.current)
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

  return (
    <SpeakerProfilesContext.Provider
      value={{
        callId,
        profiles: validCall ? (map?.profiles ?? {}) : {},
        drafts,
        save,
        canSave: validCall && map !== null && !saving,
        error,
        server: true,
      }}
    >
      {error && (
        <p role="alert">
          {error}
          {!map && validCall && (
            <>
              {" "}
              <button type="button" onClick={() => setRetry((n) => n + 1)}>
                Reload speaker details
              </button>
            </>
          )}
        </p>
      )}
      {children}
    </SpeakerProfilesContext.Provider>
  );
}
