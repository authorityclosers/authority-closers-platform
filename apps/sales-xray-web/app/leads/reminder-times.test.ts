import { describe, expect, it } from "vitest";

import {
  REMINDER_PRESETS,
  isReminderPreset,
  presetTime,
  readLocal,
  reminderWords,
  splitLocal,
  tomorrowMorning,
} from "./reminder-times";

// Owner, 22 Nov 2026: "custom times: any date and time, plus quick presets of
// 1 min, 2 min, 5 min, 15 min, 30 min, 1 h, tomorrow morning".
describe("reminder times", () => {
  const now = new Date(2026, 10, 22, 20, 40, 37, 250);

  it("offers the owner's presets in order", () => {
    expect(REMINDER_PRESETS.map((item) => item.label)).toEqual([
      "In 1 min",
      "In 2 min",
      "In 5 min",
      "In 15 min",
      "In 30 min",
      "In 1 hour",
      "Tomorrow morning",
    ]);
    expect(isReminderPreset("m5")).toBe(true);
    expect(isReminderPreset("evening")).toBe(false);
  });

  it("counts minutes to the second, never rounding to a whole minute", () => {
    for (const [key, minutes] of [
      ["m1", 1],
      ["m2", 2],
      ["m5", 5],
      ["m15", 15],
      ["m30", 30],
      ["hour", 60],
    ] as const) {
      const at = presetTime(key, now);
      expect(at.getTime() - now.getTime()).toBe(minutes * 60_000 - 250);
    }
  });

  it("makes tomorrow morning 10:00, or the team's opening in the team's clock", () => {
    expect(tomorrowMorning(now)).toEqual(new Date(2026, 10, 23, 10, 0));
    const ist = new Date("2026-11-22T23:50:00+05:30");
    expect(
      tomorrowMorning(ist, {
        days: [0, 1, 2, 3, 4, 5],
        start: "09:30",
        timezone: "Asia/Kolkata",
      }).toISOString(),
    ).toBe(new Date("2026-11-23T09:30:00+05:30").toISOString());
    // No working days set: the common 10:00.
    expect(tomorrowMorning(now, { days: [], start: "08:00" })).toEqual(
      new Date(2026, 10, 23, 10, 0),
    );
    // Month end rolls over.
    expect(tomorrowMorning(new Date(2026, 10, 30, 18, 0))).toEqual(
      new Date(2026, 11, 1, 10, 0),
    );
  });

  it("says the exact time: Today 8:42 pm, Tomorrow 10:00 am, or the date", () => {
    const words = (at: Date) => reminderWords(at, now).replace(/\s/g, " ");
    expect(words(presetTime("m2", now))).toBe("Today 8:42 pm");
    expect(words(tomorrowMorning(now))).toBe("Tomorrow 10:00 am");
    expect(words(new Date(2026, 10, 24, 16, 5))).toBe("Tue 24 Nov, 4:05 pm");
  });

  it("splits and reads the phone's date and time fields", () => {
    const at = new Date(2026, 10, 3, 7, 5);
    expect(splitLocal(at)).toEqual({ date: "2026-11-03", time: "07:05" });
    expect(readLocal("2026-11-03T07:05")).toEqual(at);
    expect(readLocal("")).toBeNull();
    expect(readLocal("soon")).toBeNull();
  });
});
