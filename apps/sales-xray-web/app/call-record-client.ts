import { acquisition, record, submissionPath } from "./acquisition-client";
import { parseCallRecord, type CallRecord } from "./call-record-contract";

/**
 * Reads the Call Record from the server (GET only).
 * Resolves with the parsed CallRecord, or null if not yet available or on failure.
 */
export async function readCallRecord(
  submissionId: string,
  signal?: AbortSignal,
): Promise<CallRecord | null> {
  try {
    const response = await acquisition(
      `${submissionPath(submissionId)}/call-record`,
      { signal },
    );
    return parseCallRecord(record(response));
  } catch {
    return null;
  }
}
