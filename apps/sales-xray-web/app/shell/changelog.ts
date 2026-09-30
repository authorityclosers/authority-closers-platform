/**
 * What's new, in plain words. Every entry is a change that is live on the
 * site; the newest comes first and its id marks what a viewer has seen.
 */
export type ChangeEntry = {
  id: string;
  /** Calendar date, YYYY-MM-DD. */
  date: string;
  title: string;
  items: string[];
};

export const CHANGELOG: ChangeEntry[] = [
  {
    id: "2026-09-30-settings-card",
    date: "2026-09-30",
    title: "Everything from one card",
    items: [
      "The gear opens one card for settings, language, usage, plans and this list.",
      "The minutes pill is smaller and shows the full picture on hover.",
    ],
  },
  {
    id: "2026-09-30-dashboard",
    date: "2026-09-30",
    title: "A cleaner dashboard",
    items: [
      "Recent calls fit your screen, with no scrollbar.",
      "Your last 30 days drawn as one waveform, and a ring for where your calls are.",
      "Tiles show your trend, how many calls have a report and minutes used.",
    ],
  },
  {
    id: "2026-09-30-status",
    date: "2026-09-30",
    title: "Live status on every call",
    items: [
      "A small mark shows if a report is ready, in progress or needs you.",
      "Calls being analysed play a little equaliser.",
      "The call you have open is highlighted in Recents.",
    ],
  },
  {
    id: "2026-09-30-report",
    date: "2026-09-30",
    title: "More from every report",
    items: [
      "Switch the call map between who talked, call stages and the prospect's interest.",
      "Key facts to confirm or fill in: time asked for, price, next step and numbers heard.",
      "A Raw data tab with every question, number and finding, ready to download.",
      "The transcript uses the names you gave each speaker.",
    ],
  },
  {
    id: "2026-09-29-speakers",
    date: "2026-09-29",
    title: "Name the people on the call",
    items: [
      "A lane for every voice, with names, roles and icons.",
      "One tap to confirm which voice is you.",
      "Reports work in dark mode.",
    ],
  },
  {
    id: "2026-09-29-header",
    date: "2026-09-29",
    title: "A report header that stays with you",
    items: [
      "The call name and menu stay pinned while you read.",
      "The waveform folds into the header as you scroll.",
    ],
  },
];
