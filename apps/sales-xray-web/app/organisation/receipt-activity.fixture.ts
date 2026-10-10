/**
 * The complete tested fictional response for
 * `GET /v1/conversation/acquisition/organisation/activity` (AUT-1392, attached
 * to AUT-1616). Fictional people and dates only; no fixture is used in the app.
 */
const active: Record<string, [number, number]> = {
  "2026-08-31": [1, 45],
  "2026-09-27": [1, 90],
  "2026-09-28": [1, 120],
  "2026-09-29": [3, 65],
};

export function receiptFixture() {
  const first = Date.UTC(2026, 7, 31);
  return {
    timezone: "Asia/Kolkata",
    days: Array.from({ length: 30 }, (_, index) => {
      const date = new Date(first + index * 86_400_000)
        .toISOString()
        .slice(0, 10);
      const [analysed, seconds] = active[date] ?? [0, 0];
      return { date, analysed, analysed_seconds: seconds };
    }),
    analysed_last_30_days: 6,
    analysed_previous_30_days: 4,
    people: [
      {
        person_id: "024f088d-0a56-4a14-9b20-8030bca6df9a",
        name: "Alex",
        analysed_last_30_days: 1,
        analysed_seconds_last_30_days: 15,
        analysed_previous_30_days: 0,
      },
      {
        person_id: "86d585ee-3ff7-4761-b7eb-fbb425a7bef3",
        name: "Alex",
        analysed_last_30_days: 0,
        analysed_seconds_last_30_days: 0,
        analysed_previous_30_days: 1,
      },
      {
        person_id: "017e41d8-11bc-4e5e-8fb0-9f054b6faded",
        name: "Zoe",
        analysed_last_30_days: 5,
        analysed_seconds_last_30_days: 305,
        analysed_previous_30_days: 2,
      },
      {
        person_id: "38c9fb71-e1a5-4c8b-9201-3c7a6dbef259",
        name: "m***@example.test",
        analysed_last_30_days: 0,
        analysed_seconds_last_30_days: 0,
        analysed_previous_30_days: 1,
      },
    ],
  };
}
