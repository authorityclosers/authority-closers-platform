/**
 * The tester programme's Play links, in one place (orchestrator, 26 Oct 2026:
 * "make step 1's URL a constant I can change in one place"). Since 13 Nov 2026
 * people join a waitlist and the team adds approved Google accounts to the
 * closed test's Google Group (salesxray-testers@), so the page shows only
 * Play's two steps: the opt-in page and the store page.
 */
export type TestersConfig = Readonly<{
  /** Play's closed test, "Closed testing - Alpha": tap "Become a tester". */
  optInUrl: string;
  /** The app's store page, for the install once opted in. */
  playUrl: string;
}>;

export const TESTERS: TestersConfig = {
  optInUrl:
    "https://play.google.com/apps/testing/com.authorityclosers.salesxray",
  playUrl:
    "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray",
};
