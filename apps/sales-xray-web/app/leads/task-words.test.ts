import { describe, expect, it } from "vitest";

import {
  BUCKETS,
  bucketLabel,
  daysFrom,
  dueWords,
  kindOf,
  localInput,
  quickTimes,
} from "./task-words";

// Local times: the phone's own clock, whatever zone the test runs in.
const at = (day: number, hour: number, minute = 0) =>
  new Date(2026, 9, day, hour, minute);

describe("task words", () => {
  it("names every kind, and Other for one it doesn't know", () => {
    expect(kindOf("call_back").label).toBe("Call back");
    expect(kindOf("send_file").label).toBe("Send file");
    expect(kindOf("nope" as never).label).toBe("Other");
  });

  it("counts days between calendar days, not 24-hour spans", () => {
    const now = at(24, 23, 30);
    expect(daysFrom(at(25, 0, 15), now)).toBe(1);
    expect(daysFrom(at(24, 0, 5), now)).toBe(0);
    expect(daysFrom(at(23, 23, 59), now)).toBe(-1);
  });

  it("says a due the way a seller reads it", () => {
    const now = at(24, 11);
    const today = dueWords({ starts_at: at(24, 17, 30).toISOString() }, now);
    expect(today).not.toMatch(/Tomorrow|Yesterday/);
    expect(today).toMatch(/30/);
    expect(dueWords({ starts_at: at(25, 10).toISOString() }, now)).toMatch(
      /^Tomorrow, /,
    );
    expect(dueWords({ starts_at: at(23, 10).toISOString() }, now)).toMatch(
      /^Yesterday, /,
    );
    expect(dueWords({ starts_at: at(28, 10).toISOString() }, now)).toMatch(
      /28/,
    );
  });

  it("puts a count beside a bucket only when there is one", () => {
    const [overdue, today] = BUCKETS;
    expect(bucketLabel(overdue, { overdue: 3 })).toBe("Overdue 3");
    expect(bucketLabel(today, { overdue: 3 })).toBe("Today");
    expect(bucketLabel(today, null)).toBe("Today");
  });

  it("offers this evening only before 5 PM, and rounds an hour to 5 minutes", () => {
    const morning = quickTimes(at(24, 9, 2));
    expect(morning.map((time) => time.key)).toEqual([
      "hour",
      "evening",
      "tomorrow",
    ]);
    expect(morning[0].at.getHours()).toBe(10);
    expect(morning[0].at.getMinutes()).toBe(5);
    expect(morning[1].at.getHours()).toBe(18);
    expect(morning[2].at.getDate()).toBe(25);
    expect(morning[2].at.getHours()).toBe(10);
    const late = quickTimes(at(24, 17, 10));
    expect(late.map((time) => time.key)).toEqual(["hour", "tomorrow"]);
  });

  it("keeps an hour that rounds up into the next hour whole", () => {
    const [hour] = quickTimes(at(24, 9, 58));
    expect(hour.at.getHours()).toBe(11);
    expect(hour.at.getMinutes()).toBe(0);
  });

  it("writes a datetime-local value in the phone's own time", () => {
    expect(localInput(at(5, 7, 4))).toBe("2026-10-05T07:04");
  });
});
