/**
 * The words on /testers (owner, 13 Nov 2026: "a tiny, beautiful page with one
 * clear CTA"). English only for now: the Hindi and Marathi of the 26 Oct page
 * come back once a native speaker has checked the new lines.
 */
export const COPY = {
  title: "Test Sales X-Ray before everyone else",
  lead: "Get our Android app early and help shape what it becomes.",
  cta: "Become a tester",
  ctaNote:
    "Android phones · Sign in with the Google account your Play Store uses",

  joiningAs: "Joining as",
  notYou: "Use another account",
  playAccount:
    "This must be the Google account on your phone's Play Store: Play only lets that account in.",
  phone: "Your Android phone",
  phoneHint: "e.g. Redmi 13, OnePlus Nord, Galaxy A15",
  role: "Your role",
  business: "Your business",
  businessHint: "What you sell, or your company",
  join: "Join the waitlist",
  joining: "Joining…",

  waitingTitle: "You're on the list",
  waitingText:
    "We review new testers every day. Once you're in, we'll email {email} with two quick steps.",
  approvedTitle: "You're approved",
  approvedText:
    "We're adding {email} to the tester group. You'll get an email shortly, then it's two taps.",
  readyTitle: "You're in",
  readyText: "Two steps on your Android phone, signed in as {email}:",
  sheetText: "You're in the tester group. Two steps on this phone:",
  stepOneTitle: "Become a tester",
  stepOneText: "Open Play's test page and tap Become a tester.",
  stepOneButton: "Become a tester",
  stepTwoTitle: "Install the app",
  stepTwoText: "Install Sales X-Ray from Google Play with the same account.",
  stepTwoButton: "Open Google Play",
  notFoundTitle: "Play says “Item not found”?",
  notFoundText:
    "Check that Play is on {email} (tap your photo in Play to switch), do step 1 first, then wait five minutes and try step 2 again.",
  declinedTitle: "Thanks for applying",
  declinedText:
    "We can't add you to this round of testing. We'll email {email} if a place opens.",

  problem: "Something went wrong. Try again.",
  privacy: "Privacy",
  footer: "Sales X-Ray by Authority Closers",
} as const;

export function withEmail(text: string, email: string): string {
  return text.replace("{email}", email);
}
