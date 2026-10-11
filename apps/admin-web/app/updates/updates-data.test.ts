import { describe, expect, it } from "vitest";

import { normalizeNotes } from "./updates-data";

describe("product notes", () => {
  it("normalizes notes with defaults", () => {
    const notes = normalizeNotes({
      notes: [
        {
          key: "k1",
          title: "Faster reports",
          items: ["Two minutes faster", 3],
        },
      ],
    });
    expect(notes[0]).toMatchObject({
      key: "k1",
      version: 1,
      status: "draft",
      audience: "everyone",
      items: ["Two minutes faster"],
    });
    expect(normalizeNotes({})).toEqual([]);
  });
});
