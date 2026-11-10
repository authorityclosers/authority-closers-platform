/**
 * Global search's reads (Redmi QA on production, 10 Nov 2026: "Looking for
 * leads and calls..." for 3-4 s, while the server's search queries take a few
 * ms each): the leads read and the screens' own searches go out together, not
 * one after another, and the lead reader's code starts loading as search opens.
 */

/** Leads and every other search at once; a failed one adds nothing. */
export async function searchTogether<T>(
  leads: () => Promise<T[]>,
  others: readonly (() => Promise<T[]>)[],
): Promise<[T[], T[]]> {
  const [found, theirs] = await Promise.all([
    leads().catch(() => [] as T[]),
    Promise.allSettled(others.map((search) => search())),
  ]);
  return [
    found,
    theirs.flatMap((result) =>
      result.status === "fulfilled" ? result.value : [],
    ),
  ];
}

/** The lead reader's code, fetched once before it is needed. */
export function warmLeadsSearch(): void {
  void import("../leads/leads-client").catch(() => undefined);
}
