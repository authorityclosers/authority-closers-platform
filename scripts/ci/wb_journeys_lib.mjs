// Seller journeys (lever 5 of the testing plan; the orchestrator for the owner, 27 Oct 2026): what a seller does in a
// day, step by step, on the review fixtures (fictional people and calls, no API, no account; nothing leaves the page).
// The bug radar (wb_radar.mjs) walks each one as a phone and as the Android app on a slow phone: every step is timed,
// the screen after it is checked like a page, and a step that can't be done is a finding (journey-broken). Journeys
// on staging with a real sign-in wait for the owner's synthetic workspace.
//
// A journey is { title, steps, draft? }: a draft runs only when asked for (`--radar journeys`), not every night.
// A step is { name, goto?, click?, fill?, check?, file?, wait?, has?, gone?, optional? }, done in that order:
// - goto opens a fixture path. The first step always does; a later one stands in for what happens off the page (the
//   phone's dialler, the server's analysis);
// - click taps the first match (optional: skipped when there is none); fill is [selector, text]; check ticks a box
//   the way a person does, on its label; file picks a fictional recording (fictionalRecording);
// - wait must then be visible, has present (a hidden input), and gone hidden, within the time allowed.
// Selectors are Playwright's: CSS plus :text-matches() and :has-text().

/** A button whose words start with these (a regex source), as the fixtures' own taps press them. */
const button = (start) => `button:text-matches("^${start}")`;
// The lead's "How did it go?" box (lead-sheet.tsx).
const OUTCOME =
  'section:has(h3:text-matches("How did (it|the call with .+) go"))';
// A report's section link, tab or view by its words.
const link = (words) => `:is(a, button, [role="tab"]):has-text("${words}")`;

export const JOURNEYS = {
  "sign-in-setup": {
    title: "A new seller signs in with an email code and sets up the business",
    steps: [
      {
        name: "Open sign-in",
        goto: "/review-fixture/sign-in?chrome=0",
        wait: 'input[type="email"]',
      },
      {
        name: "Type the email",
        fill: ['input[type="email"]', "asha@fictional-homes.example"],
      },
      {
        name: "Accept the terms",
        check: 'input[type="checkbox"][form="account-email-form"]',
      },
      {
        name: "Send the code",
        click: button("Send sign-in code"),
        wait: 'input[autocomplete="one-time-code"]',
      },
      {
        name: "Type the code",
        fill: ['input[autocomplete="one-time-code"]', "123456"],
      },
      {
        name: "Sign in",
        click:
          'form:has(input[autocomplete="one-time-code"]) button[type="submit"]',
        optional: true,
        wait: 'h1:text-matches("How will you use")',
      },
      {
        name: "For my business",
        click: '[role="radiogroup"] >> text=For my business',
      },
      {
        name: "Set up my business",
        click: button("Set up my business"),
        wait: 'input[autocomplete="organization"]',
      },
      {
        name: "Name the business",
        fill: ['input[autocomplete="organization"]', "Fictional Homes"],
      },
      // Created, it goes straight on to "What does your business sell?" (run 40502619852).
      {
        name: "Create it",
        click: button("Create my business"),
        wait: 'ul[aria-label="Kinds of business"]',
      },
      {
        name: "Pick real estate",
        click:
          'ul[aria-label="Kinds of business"] button:has-text("Real estate")',
      },
      {
        name: "Use these stages",
        click: button("Use these stages"),
        wait: button("Send( \\\\d+)? invites?"),
      },
      {
        name: "Skip inviting the team",
        click: button("Skip for now"),
        wait: button("Add your first lead"),
      },
      {
        name: "Add the first lead",
        click: button("Add your first lead"),
        wait: 'h1:text-matches("opens next")',
      },
    ],
  },
  "after-call": {
    title: "Back from a call, a seller saves that they will call back",
    steps: [
      // The phone logged 1 min 22 s of talk, so "We talked" is chosen; Save then needs what happens next.
      {
        name: "Back from the call",
        goto: "/review-fixture/leads?after-call=1",
        wait: 'h3:text-matches("How did (it|the call with .+) go")',
      },
      { name: "Call back", click: `${OUTCOME} button:has-text("Call back")` },
      // Saved, the sheet says so and names who is next; the question stays above it (run 40509682184).
      {
        name: "Save",
        click: `${OUTCOME} button:text-matches("^Save$")`,
        wait: '[role="status"]:has-text("Saved.")',
      },
    ],
  },
  "call-mode": {
    title: "A seller works down the call list in Call mode",
    steps: [
      {
        name: "Open the leads to call",
        goto: "/review-fixture/leads?loop=1",
        wait: 'button:has-text("Start calling")',
      },
      {
        name: "Start calling",
        click: 'button:has-text("Start calling")',
        wait: "dialog[open]",
      },
      {
        name: "No answer",
        click: `dialog[open] ${button("No answer")}`,
        wait: button("Save and call "),
      },
      {
        name: "Save and stop here",
        click: button("Save and stop here"),
        gone: button("Save and call "),
      },
    ],
  },
  "upload-recording": {
    title:
      "A seller uploads a recording they already have and asks for its analysis",
    // As the Android app, the pick answers "That didn't go through" (run 40509682184): the app's own path or this
    // profile's stand-in for it, to be looked at before this walks every night.
    draft: true,
    steps: [
      {
        name: "Open new analysis",
        goto: "/review-fixture/upload",
        has: 'input[aria-label="Choose sales call audio"]',
      },
      {
        name: "Pick the recording",
        file: 'input[aria-label="Choose sales call audio"]',
        wait: "text=fictional-call.wav",
      },
      // Picked, the page goes straight on to the language and the terms (run 40507981905).
      {
        name: "Accept the terms",
        check: 'label:has-text("Terms") input[type="checkbox"]',
      },
      // The preview only observes its box (it never counts as consent), so "Analyse my call" stays off here: its own
      // details step, terms ticked, stands in, then the analysing screen for the server's part.
      {
        name: "Ready to analyse",
        goto: "/review-fixture/upload?step=details",
        wait: button("Analyse my call"),
      },
      {
        name: "The call is analysed",
        goto: "/review-fixture/upload?step=analysing",
        wait: "main",
      },
    ],
  },
  "read-report": {
    title: "A seller reads a call's report and listens to its key moments",
    // As the phone, the page never went quiet enough to open (90 s, twice); as the app, "Play" brought no player
    // (run 40509682184). To settle before this walks every night.
    draft: true,
    steps: [
      // One page in three sections (Overview & Score, Detailed Call Analysis, Final Call Outcome), each a link at the
      // top, and Report, Coaching, Document and Details views (run 40507981905).
      {
        name: "Open the report",
        goto: "/review-fixture/report/story?example=api&clean=1",
        wait: ':is(h1, h2, h3):has-text("Overview & Score")',
      },
      {
        name: "Detailed call analysis",
        click: link("Detailed Call Analysis"),
        wait: ':is(h1, h2, h3):has-text("Detailed Call Analysis")',
      },
      {
        name: "Final call outcome",
        click: link("Final Call Outcome"),
        wait: '[aria-label^="Listen to call outcome at"]',
      },
      {
        name: "Listen to the outcome",
        click: '[aria-label^="Listen to call outcome at"]',
        wait: '[aria-label="Call audio player"]',
      },
      { name: "Coaching view", click: link("Coaching view") },
    ],
  },
};

const ACTIONS = [
  "goto",
  "click",
  "fill",
  "check",
  "file",
  "wait",
  "has",
  "gone",
];

/** A step does something: one action at least. */
export const stepActions = (step) =>
  ACTIONS.filter((action) => step[action] !== undefined);

/** `journeys` asks for every journey, `journey:<key>` for one; anything else is a page. */
export const isJourneyRoute = (route) =>
  route === "journeys" || route.startsWith("journey:");

/** The radar asked for journeys only (no page at all). */
export const onlyJourneys = (routes = []) =>
  routes.length > 0 && routes.every(isJourneyRoute);

/**
 * The journeys a request asks for: `journeys` every one, `journey:<key>` that one, none for pages only. A request
 * naming nothing (the nightly, a release hold) walks the finished ones: a draft's stops would be cards about the
 * journey itself, not the app.
 */
export function pickJourneys(routes = [], journeys = JOURNEYS) {
  const asked = routes.filter(isJourneyRoute);
  if (asked.includes("journeys")) return Object.entries(journeys);
  if (!routes.length)
    return Object.entries(journeys).filter(([, plan]) => !plan.draft);
  return asked.map((route) => {
    const key = route.slice("journey:".length);
    if (!journeys[key]) throw new Error(`unknown journey ${key}`);
    return [key, journeys[key]];
  });
}

// Time a step may take on a GitHub runner against `next dev` (the fixtures' server): over it, the step is slow (low;
// real phones' speed is Admin → Speed and journeys). The Android profile's CPU is 4x slower, so its budget is too.
export const STEP_BUDGET_MS = 5000;
export const journeyBudget = (android) => STEP_BUDGET_MS * (android?.cpu ?? 1);
// How long a step's control or result may take to show before the journey stops there.
export const journeyTimeout = (android) => (android?.cpu ? 30000 : 15000);

/** The recording a journey picks: a quiet tone, made here, fictional, never sent (16-bit mono WAV). */
export function fictionalRecording(seconds = 10, rate = 8000) {
  const samples = seconds * rate;
  const data = Buffer.alloc(44 + samples * 2);
  data.write("RIFF", 0);
  data.writeUInt32LE(36 + samples * 2, 4);
  data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16);
  data.writeUInt16LE(1, 20); // PCM
  data.writeUInt16LE(1, 22); // mono
  data.writeUInt32LE(rate, 24);
  data.writeUInt32LE(rate * 2, 28);
  data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34);
  data.write("data", 36);
  data.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++)
    data.writeInt16LE(
      Math.round(4000 * Math.sin((2 * Math.PI * 440 * i) / rate)),
      44 + i * 2,
    );
  return { name: "fictional-call.wav", mimeType: "audio/wav", buffer: data };
}

/** One walk's line in the report: steps done, time, the slowest step, where it stopped. */
export function journeySummary(walk) {
  const total = walk.steps.reduce((sum, step) => sum + step.ms, 0);
  const slowest = walk.steps.reduce(
    (most, step) => (!most || step.ms > most.ms ? step : most),
    null,
  );
  return {
    done: `${walk.steps.length}/${walk.total}`,
    seconds: (total / 1000).toFixed(1),
    slowest: slowest
      ? `${slowest.name} (${(slowest.ms / 1000).toFixed(1)} s)`
      : "",
    stopped: walk.stopped ?? "",
  };
}
