import { expect, it } from "vitest";
import {
  fixtureFrame,
  fixtureStateId,
  fixtureStateIds,
  fixtureUrl,
} from "./fixture-review-states";

it("accepts only exact, allowlisted local fixture addresses", () => {
  for (const id of fixtureStateIds) {
    expect(fixtureStateId(new URL(fixtureUrl(id), "http://local.test").search)).toBe(
      id,
    );
  }
  for (const invalid of [
    "?new=1&sx-fixture=processing.unknown",
    "?new=1&sx-fixture=upload.empty&sx-fixture=upload.selected",
    "?new=1&sx-fixture=upload.empty&call=00000000-0000-4000-8000-000000000001",
    "?new=0&sx-fixture=upload.empty",
    "?sx-fixture=upload.empty",
  ])
    expect(fixtureStateId(invalid)).toBeNull();
});

it("keeps fixture frames static, synthetic, and navigable without a report", () => {
  const stages = fixtureStateIds.map((id) => fixtureFrame(id));
  expect(stages[0].kind).toBe("auth");
  expect(stages[3].kind).toBe("profile");
  expect(stages[6].observation?.file_name).toBeNull();
  expect(stages[7].observation?.file_name).toBe("Example call.wav");
  expect(stages[9].kind).toBe("processing");
  expect(fixtureFrame("processing.paused").progress?.stages).toEqual([
    { stage: "C2", state: "completed" },
    { stage: "C4", state: "completed" },
    { stage: "C5", state: "uncertain" },
  ]);
  for (const [index, stage] of stages.entries()) {
    expect(stage.navigation.position).toBe(index + 1);
    expect(stage.navigation.total).toBe(stages.length);
    expect(stage.navigation.previousUrl).toBe(
      index ? fixtureUrl(fixtureStateIds[index - 1]) : null,
    );
    expect(stage.navigation.nextUrl).toBe(
      index + 1 < stages.length
        ? fixtureUrl(fixtureStateIds[index + 1])
        : null,
    );
    expect(stage.progress?.has_report).not.toBe(true);
    if (stage.progress) expect(stage.progress.failure_code).toBeNull();
    if (stage.submission) {
      expect(stage.submission.id).toBe("00000000-0000-4000-8000-000000000001");
      expect(stage.submission.sha).toBe("0".repeat(64));
    }
  }
});
