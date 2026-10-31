/**
 * A list's next page added to the rows already shown, each lead once (owner's
 * bug report, 31 Oct 2026: leads repeated after the first page). The server's
 * order now ends on the lead's id, so pages no longer overlap; a lead that
 * moves between two reads still shows once.
 */
export function withoutRepeats<Row extends { lead_id: string }>(
  rows: readonly Row[],
  next: readonly Row[],
): Row[] {
  const seen = new Set(rows.map((row) => row.lead_id));
  const added = next.filter((row) => {
    if (seen.has(row.lead_id)) return false;
    seen.add(row.lead_id);
    return true;
  });
  return [...rows, ...added];
}
