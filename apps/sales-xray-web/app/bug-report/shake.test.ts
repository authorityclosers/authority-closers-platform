import { expect, it } from "vitest";

import { shakeDetector } from "./shake";

// 26 Oct 2026: picking the phone up opened the reporter. It now takes a deliberate
// double shake: four separate hard swings within 1.5 seconds.
function detector() {
  let time = 0;
  const shaken = shakeDetector(() => time);
  return {
    at(ms: number, force: number): boolean {
      time = ms;
      return shaken(0, 0, 9.81 + force);
    },
  };
}

it("a pick-up or one jolt never opens it, however many readings it gives", () => {
  const phone = detector();
  // One jolt: strong readings 16 ms apart.
  const jolt = [0, 16, 32, 48, 64, 80].map((ms) => phone.at(ms, 25));
  // Lifting and stopping: two swings.
  const lift = [600, 616, 900, 916].map((ms) => phone.at(ms, 25));
  expect([...jolt, ...lift]).not.toContain(true);
});

it("a gentle wave never opens it", () => {
  const phone = detector();
  expect([0, 200, 400, 600, 800].map((ms) => phone.at(ms, 15))).not.toContain(
    true,
  );
});

it("a deliberate double shake opens it once", () => {
  const phone = detector();
  const shake = [0, 16, 250, 266, 500, 516, 750].map((ms) => phone.at(ms, 25));
  expect(shake.filter(Boolean)).toHaveLength(1);
  expect(shake.at(-1)).toBe(true);
  // Not again within five seconds.
  expect([1000, 1250, 1500, 1750].map((ms) => phone.at(ms, 25))).not.toContain(
    true,
  );
});
