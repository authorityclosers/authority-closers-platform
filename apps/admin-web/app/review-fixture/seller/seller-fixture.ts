/**
 * A fictional seller's days for the local review page and tests, in the API's
 * own shape (GET /v1/admin/sellers/{id}/timeline). Never real people.
 */
export type SellerFixtureState = "gap" | "clean" | "empty";

const ORG = "6f3d2a10-0000-4000-8000-00000000a001";
const PERSONAL = "6f3d2a10-0000-4000-8000-00000000a002";

export function sellerFixture(state: SellerFixtureState = "gap") {
  const person = {
    id: "6f3d2a10-0000-4000-8000-00000000b001",
    name: "Fictional Seller",
    email: "seller@example.test",
    status: "active",
    created_at: "2026-09-20T05:00:00+00:00",
  };
  const workspaces = [
    {
      id: ORG,
      name: "Fictional Realty",
      kind: "organisation",
      role: "member",
      status: "active",
      joined_at: "2026-09-21T05:00:00+00:00",
      ended_at: null,
      analytics: "on",
      sign_ins: state === "empty" ? 0 : 3,
      last_opened_at: state === "empty" ? null : "2026-10-23T12:40:00+00:00",
    },
    {
      id: PERSONAL,
      name: "Personal accounts",
      kind: "personal",
      role: "owner",
      status: "active",
      joined_at: "2026-09-20T05:00:00+00:00",
      ended_at: null,
      analytics: "on",
      sign_ins: state === "empty" ? 0 : 1,
      last_opened_at: state === "empty" ? null : "2026-10-21T04:10:00+00:00",
    },
  ];
  const quiet = {
    calls_started: 0,
    results_saved: 0,
    stage_moves_saved: 0,
    waiting: 0,
    refused: 0,
    oldest_waiting_min: 0,
    errors: 0,
    error_codes: [],
    script_errors: 0,
    slow_taps: 0,
    slow_requests: 0,
    slow_screens: [],
    crashes: 0,
  };
  const day22 = {
    day: "2026-10-22",
    label: "22 Oct",
    server: {
      calls_app: 3,
      calls_logged: 9,
      connected: 6,
      test_calls: 0,
      results: 7,
      notes: 2,
      stage_moves: 3,
    },
    phone: {
      ...quiet,
      calls_started: 3,
      results_saved: 7,
      stage_moves_saved: 3,
      slow_taps: 1,
    },
    sign_ins: 1,
    sign_outs: 0,
    workspaces: ["Fictional Realty"],
    versions: ["1.0.25"],
    installs: ["a1b2c3d4"],
    flags: [],
    moments: [
      {
        at: "2026-10-22T03:35:00+00:00",
        time: "09:05",
        words: "Signed in, opened Fictional Realty",
      },
    ],
  };
  if (state === "empty")
    return {
      schema: "ac.admin.seller-timeline/1",
      person,
      window: {
        days: 14,
        since: "2026-10-10T18:30:00+00:00",
        until: "2026-10-24T12:00:00+00:00",
      },
      summary: { tone: "neutral", words: "No activity in the last 14 days" },
      totals: {
        calls_app: 0,
        calls_logged: 0,
        results: 0,
        notes: 0,
        stage_moves: 0,
        results_saved: 0,
        stage_moves_saved: 0,
        crashes: 0,
        errors: 0,
        days_with_gaps: 0,
      },
      workspaces,
      devices: [],
      phones: [],
      installs: [],
      consent: {
        terms_version: "2026-10-01",
        terms_at: "2026-09-20T05:02:00+00:00",
      },
      days: [],
      truncated: [],
    };
  const days =
    state === "clean"
      ? [day22]
      : [
          {
            day: "2026-10-23",
            label: "23 Oct",
            server: {
              calls_app: 4,
              calls_logged: 10,
              connected: 7,
              test_calls: 0,
              results: 0,
              notes: 0,
              stage_moves: 0,
            },
            phone: {
              ...quiet,
              calls_started: 4,
              results_saved: 9,
              stage_moves_saved: 2,
              waiting: 11,
              oldest_waiting_min: 310,
              errors: 2,
              error_codes: ["leads: offline"],
              slow_taps: 3,
              slow_requests: 5,
              slow_screens: ["lead"],
            },
            sign_ins: 1,
            sign_outs: 0,
            workspaces: ["Fictional Realty"],
            versions: ["1.0.26"],
            installs: ["e5f6a7b8"],
            flags: [
              {
                tone: "bad",
                words: "9 results saved on the phone, 0 reached the server",
              },
              {
                tone: "bad",
                words: "2 stage moves saved on the phone, 0 reached the server",
              },
              {
                tone: "warn",
                words: "The phone held 11 unsent changes (oldest 5 hours)",
              },
              { tone: "warn", words: "2 errors shown (leads: offline)" },
              {
                tone: "warn",
                words: "A new install or a new phone started logging calls",
              },
            ],
            moments: [
              {
                at: "2026-10-23T03:30:00+00:00",
                time: "09:00",
                words: "App version now 1.0.26",
              },
              {
                at: "2026-10-23T03:41:00+00:00",
                time: "09:11",
                words: "Signed in, opened Fictional Realty",
              },
              {
                at: "2026-10-23T05:02:00+00:00",
                time: "10:32",
                words: "New install e5f6a7b8 logged its first call",
              },
              {
                at: "2026-10-23T07:15:00+00:00",
                time: "12:45",
                words: "Phone reported 4 changes waiting",
              },
              {
                at: "2026-10-23T12:40:00+00:00",
                time: "18:10",
                words: "Phone reported 11 changes waiting",
              },
            ],
          },
          day22,
        ];
  return {
    schema: "ac.admin.seller-timeline/1",
    person,
    window: {
      days: 14,
      since: "2026-10-10T18:30:00+00:00",
      until: "2026-10-24T12:00:00+00:00",
    },
    summary:
      state === "clean"
        ? {
            tone: "good",
            words:
              "No gaps in the last 14 days: 12 calls, 7 results and 3 stage moves reached the server",
          }
        : {
            tone: "bad",
            words:
              "23 Oct: 14 calls, 0 results saved — the phone saved 9 results that never reached the server",
          },
    totals: {
      calls_app: state === "clean" ? 3 : 7,
      calls_logged: state === "clean" ? 9 : 19,
      results: 7,
      notes: 2,
      stage_moves: 3,
      results_saved: state === "clean" ? 7 : 16,
      stage_moves_saved: state === "clean" ? 3 : 5,
      crashes: 0,
      errors: state === "clean" ? 0 : 2,
      days_with_gaps: state === "clean" ? 0 : 1,
    },
    workspaces,
    devices: [
      {
        app: "android",
        device: "phone",
        version: state === "clean" ? "1.0.25" : "1.0.26",
        versions: state === "clean" ? ["1.0.25"] : ["1.0.26", "1.0.25"],
        model: "Fictional phone 8",
        maker: "fictional",
        store: state === "clean" ? "Download link" : "Play",
        android: 13,
        last_seen_at: "2026-10-23T12:40:00+00:00",
      },
      {
        app: "web",
        device: "desktop",
        version: null,
        versions: [],
        model: null,
        maker: null,
        store: null,
        android: null,
        last_seen_at: "2026-10-21T04:30:00+00:00",
      },
    ],
    phones: [
      {
        workspace: "Fictional Realty",
        install: state === "clean" ? "a1b2c3d4" : "e5f6a7b8",
        app_version: state === "clean" ? "1.0.25" : "1.0.26",
        family: "xiaomi",
        reported_at: "2026-10-23T05:00:00+00:00",
        synced_at: "2026-10-23T12:38:00+00:00",
      },
    ],
    installs:
      state === "clean"
        ? [
            {
              install: "a1b2c3d4",
              first_call_at: "2026-10-22T04:00:00+00:00",
              last_call_at: "2026-10-22T11:00:00+00:00",
              calls: 9,
            },
          ]
        : [
            {
              install: "e5f6a7b8",
              first_call_at: "2026-10-23T05:02:00+00:00",
              last_call_at: "2026-10-23T12:30:00+00:00",
              calls: 10,
            },
            {
              install: "a1b2c3d4",
              first_call_at: "2026-10-22T04:00:00+00:00",
              last_call_at: "2026-10-22T11:00:00+00:00",
              calls: 9,
            },
          ],
    consent: {
      terms_version: "2026-10-01",
      terms_at: "2026-09-20T05:02:00+00:00",
    },
    days,
    truncated: [],
  };
}
