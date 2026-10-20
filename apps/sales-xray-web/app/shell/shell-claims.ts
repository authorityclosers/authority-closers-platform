/**
 * Which screen's chrome the app frame shows: the active place, the title and
 * whether the screen fits the window or the page scrolls.
 *
 * Every mounted <LightboxShell> claims the frame with its settings: the page,
 * its own loading screen, and the outline standing in for a tapped place. The
 * newest stand-in wins while it is up; otherwise the newest page does. When a
 * stand-in goes without its place arriving (a press that turned into a
 * scroll, a move given up), the page under it gets its own chrome back.
 * Before this, the stand-in's settings stayed: after a scroll that began on
 * the Chats switch, Leads kept Chats' fitted height and could not scroll
 * (20 Oct).
 */

export type ShellClaim<Page> = {
  readonly page: Page;
  readonly standIn: boolean;
};

export type ShellClaims<Page> = ReadonlyArray<
  readonly [id: string, claim: ShellClaim<Page>]
>;

/** A page that has left keeps the frame until the next page claims it. */
const KEPT = "kept";

/** Adds a claim, or updates one in place (a page's settings changing). */
export function claimShell<Page>(
  claims: ShellClaims<Page>,
  id: string,
  claim: ShellClaim<Page>,
): ShellClaims<Page> {
  const rest = claim.standIn ? claims : claims.filter(([key]) => key !== KEPT);
  const at = rest.findIndex(([key]) => key === id);
  if (at < 0) return [...rest, [id, claim]];
  return rest.map((entry, index) => (index === at ? [id, claim] : entry));
}

/**
 * Drops a claim. The last page to leave stays shown, so the frame never
 * falls back to placeholders between one page and the next.
 */
export function releaseShell<Page>(
  claims: ShellClaims<Page>,
  id: string,
): ShellClaims<Page> {
  const gone = claims.find(([key]) => key === id);
  const rest = claims.filter(([key]) => key !== id);
  if (!gone || gone[1].standIn || rest.some(([, claim]) => !claim.standIn)) {
    return rest;
  }
  return [...rest, [KEPT, gone[1]]];
}

/** The claim the frame shows: the newest stand-in, else the newest page. */
export function shownClaim<Page>(
  claims: ShellClaims<Page>,
): ShellClaim<Page> | null {
  const standIn = claims.findLast(([, claim]) => claim.standIn);
  const page = claims.findLast(([, claim]) => !claim.standIn);
  return (standIn ?? page)?.[1] ?? null;
}
