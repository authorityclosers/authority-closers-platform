/**
 * Where Leads opens (Dipak's Home + Leads handoff, 31 Oct 2026, items 37 and
 * 56): Inbound Leads, To Call, the next lead on top. The list itself has no
 * stage filter; the work view and the Pipeline stage pick narrow it. The page,
 * its server read and the early read share these, so all three ask for the
 * same first list.
 */
export const OPENING_STAGE = "all";
export const OPENING_WORK: Readonly<Record<string, string>> = {
  side: "inbound",
  view: "to_call",
};
/** The opening list's question, in the order the list asks it. */
export const OPENING_QUERY = "side=inbound&view=to_call";
