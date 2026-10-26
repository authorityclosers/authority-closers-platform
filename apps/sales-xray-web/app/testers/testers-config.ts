/**
 * The tester programme's links, in one place (orchestrator, 26 Oct 2026: "make
 * step 1's URL a constant I can change in one place"). Switching from the
 * WhatsApp route to the public group, or adding the help group, is an edit
 * here and nothing else.
 *
 * - `route: "group"`: step 1 is "Join the tester group" (`groupUrl`).
 * - `route: "whatsapp"`: step 1 is "Send us your Gmail", which opens WhatsApp
 *   to `whatsappNumber` with the message typed. Only while the group is not
 *   public; it needs a number.
 * - `helpUrl`: the testers' WhatsApp help group, for "Still stuck?". Without
 *   one, that line is left out.
 */
export type TestersConfig = Readonly<{
  route: "group" | "whatsapp";
  groupUrl: string;
  /** International format without "+" or spaces, e.g. "9198xxxxxxxx". */
  whatsappNumber: string | null;
  optInUrl: string;
  playUrl: string;
  helpUrl: string | null;
}>;

export const TESTERS: TestersConfig = {
  route: "group",
  groupUrl:
    "https://groups.google.com/a/authorityclosers.com/g/salesxray-testers",
  whatsappNumber: null,
  optInUrl:
    "https://play.google.com/apps/testing/com.authorityclosers.salesxray",
  playUrl:
    "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray",
  helpUrl: null,
};

/** WhatsApp with the tester's message typed, for the Gmail route. */
export function whatsappLink(number: string, text: string): string {
  return `https://wa.me/${number}?text=${encodeURIComponent(text)}`;
}
