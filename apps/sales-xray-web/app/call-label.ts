/**
 * Owner-authored call names (C1). The server is the only source of truth:
 * a label is shown as saved only after a confirmed server response.
 */

export const MAX_CALL_LABEL_LENGTH = 120;

export type CallLabel = Readonly<{
  displayName: string | null;
  revision: number;
}>;

export class CallLabelContractError extends Error {
  constructor(code: string) {
    super(code);
    this.name = "CallLabelContractError";
  }
}

const MAX_REVISION = 2_147_483_647;

/**
 * Reads `display_name` / `display_name_revision` from a list row, progress or
 * report response. Both absent means an older server without labels (null);
 * one without the other, or an invalid value, is a contract error.
 */
export function parseCallLabel(
  item: Record<string, unknown>,
): CallLabel | null {
  const hasName = "display_name" in item;
  const hasRevision = "display_name_revision" in item;
  if (!hasName && !hasRevision) return null;
  const name = item.display_name;
  const revision = item.display_name_revision;
  if (
    !hasName ||
    !hasRevision ||
    !(name === null || typeof name === "string") ||
    typeof revision !== "number" ||
    !Number.isSafeInteger(revision) ||
    revision < 0 ||
    revision > MAX_REVISION ||
    (typeof name === "string" &&
      (!name.trim() || [...name].length > MAX_CALL_LABEL_LENGTH)) ||
    (revision === 0 && name !== null)
  )
    throw new CallLabelContractError("call_label_invalid");
  return { displayName: name, revision };
}

/** The strong entity tag the rename endpoint requires. */
export function callLabelEtag(revision: number) {
  return `"call-label-${revision}"`;
}

/**
 * Mirrors the server rules so the reader gets immediate feedback; the server
 * still decides. Returns the trimmed name, or an explanation.
 */
export function validateCallLabel(
  value: string,
): { ok: true; name: string } | { ok: false; message: string } {
  if (/[\p{Cc}\p{Cs}]/u.test(value))
    return {
      ok: false,
      message: "Remove line breaks or hidden control characters.",
    };
  const name = value.trim();
  if (!name)
    return {
      ok: false,
      message: "Enter a name, or use Clear name to remove it.",
    };
  const length = [...name].length;
  if (length > MAX_CALL_LABEL_LENGTH)
    return {
      ok: false,
      message: `Use at most ${MAX_CALL_LABEL_LENGTH} characters (${length} now).`,
    };
  return { ok: true, name };
}

/** A saved name, or an honest fallback that never pretends to be a name. */
export function callTitle(
  label: CallLabel | null | undefined,
  fallback: string,
) {
  return label?.displayName ?? fallback;
}
