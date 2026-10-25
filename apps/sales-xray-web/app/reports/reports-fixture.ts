/**
 * Fictional numbers for Reports: its tests and its review fixture
 * (/review-fixture/reports). Nothing here is shown to a real account.
 */

import type { ReportsData } from "./reports-hub";

const conversion = (
  key: string,
  label: string,
  entered: number,
  passed: number,
) => ({
  key,
  label,
  entered,
  passed,
  rate: entered ? passed / entered : null,
});

export const REPORTS_FIXTURE: ReportsData = {
  calls: { total: 24, processing: 2, completed: 19, needsAttention: 3 },
  pipeline: {
    pipeline: "main",
    days: 30,
    generated_at: "2026-10-25T05:00:00Z",
    total: 41,
    enough: true,
    groups: { open: 30, won: 5, lost: 6 },
    stages: [],
    first_connect: conversion("first_connect", "New → reached", 41, 19),
    first_connect_minutes: 14,
    conversions: [
      conversion("interested_meeting", "Interested → Meeting", 12, 7),
      conversion("meeting_demo", "Meeting → Demo done", 7, 5),
      conversion("demo_won", "Demo done → Won", 5, 3),
    ],
    show_rate: 0.71,
    lost_now: [
      { label: "Price", count: 6 },
      { label: "Bought elsewhere", count: 2 },
    ],
    lost_moves: [{ label: "Price", count: 4 }],
    junk_now: 3,
    junk_moves: 1,
    overdue: 12,
    no_next: 4,
    sellers: [],
    sources: [],
    mine: false,
  },
  performance: {
    days: 7,
    start: "2026-10-18",
    end: "2026-10-24",
    current: {
      calls: 50,
      connected: 23,
      leads_called: 38,
      interested: 9,
      won: 6,
      new_leads: 31,
      first_call_minutes: 9,
    },
    previous: {
      calls: 48,
      connected: 18,
      leads_called: 35,
      interested: 7,
      won: 4,
      new_leads: 29,
      first_call_minutes: 12,
    },
    sellers: [],
    pipeline: {},
  },
  sla: {
    settings: { on: true, minutes: 10, alertManagers: true, targets: [] },
    start: "2026-10-18",
    end: "2026-10-24",
    sellers: [],
    late: [
      {
        leadId: "00000000-0000-4000-8000-000000000301",
        leadName: "meera fictional",
        seller: "rahul example",
        minutesLate: 42,
      },
      {
        leadId: "00000000-0000-4000-8000-000000000302",
        leadName: "karan example",
        seller: "kavya fictional",
        minutesLate: 14,
      },
    ],
  },
} as ReportsData;
