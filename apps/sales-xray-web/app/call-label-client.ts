import { acquisition, record, submissionPath } from "./acquisition-client";
import {
  CallLabelContractError,
  callLabelEtag,
  parseCallLabel,
  type CallLabel,
} from "./call-label";

/**
 * PATCH the owner's call name. `displayName: null` clears it. Resolves only
 * with the server-confirmed label; any failure rejects (AcquisitionError keeps
 * the HTTP status, e.g. 409 for a competing stale edit, 403 when unclaimed).
 */
export async function renameCall(
  submissionId: string,
  displayName: string | null,
  revision: number,
  signal?: AbortSignal,
): Promise<CallLabel> {
  const confirmed = parseCallLabel(
    record(
      await acquisition(`${submissionPath(submissionId)}/label`, {
        method: "PATCH",
        headers: {
          "content-type": "application/json",
          "If-Match": callLabelEtag(revision),
        },
        body: JSON.stringify({ display_name: displayName }),
        signal,
      }),
    ),
  );
  if (!confirmed) throw new CallLabelContractError("call_label_missing");
  return confirmed;
}

/** Re-read the current label from the owner-scoped progress read (GET only). */
export async function readCallLabel(
  submissionId: string,
  signal?: AbortSignal,
): Promise<CallLabel | null> {
  return parseCallLabel(
    record(await acquisition(submissionPath(submissionId), { signal })),
  );
}
