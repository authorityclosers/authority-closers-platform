import { expect, it, vi } from "vitest";

import { shakeDetector } from "./shake";

// Readings as the phone gives them (acceleration with gravity, about 60 a second),
// the phone flat with gravity on z. A swing is a few readings the same way.
function phone() {
  let time = 0;
  const near = vi.fn();
  const shaken = shakeDetector(() => time, near);
  const step = (x: number, y: number, z: number) => {
    time += 16;
    return shaken(x, y, z);
  };
  return {
    shaken,
    near,
    rest(ms: number): boolean[] {
      return Array.from({ length: Math.ceil(ms / 16) }, () => step(0, 0, 9.81));
    },
    swing(axis: 0 | 1 | 2, force: number, readings = 6): boolean[] {
      return Array.from({ length: readings }, () => {
        const reading = [0, 0, 9.81];
        reading[axis] += force;
        return step(reading[0], reading[1], reading[2]);
      });
    },
  };
}

// Owner, 26 Oct 2026 (v0.93 would not open on a normal shake): a pick-up, one or
// two jolts, never opens it; three swings, each the other way, at 14-18 m/s² do.
it("a pick-up never opens it: a lift and its stop are two jolts", () => {
  const p = phone();
  const seen = [
    ...p.rest(500),
    ...p.swing(2, 16), // the lift
    ...p.rest(300),
    ...p.swing(2, -14), // the stop
    ...p.rest(1500),
  ];
  expect(seen).not.toContain(true);
  // A near miss is told (to tune from real phones), with its force.
  expect(p.near).toHaveBeenCalledTimes(1);
  expect(p.near.mock.calls[0][1]).toBe(2);
});

it("one jolt, bumps the same way, or a gentle wave never open it", () => {
  const p = phone();
  const seen = [
    ...p.rest(300),
    ...p.swing(0, 25, 3), // one hard jolt
    ...p.rest(400),
    ...p.swing(1, 16),
    ...p.rest(200),
    ...p.swing(1, 16), // the same way again: no turn
    ...p.rest(200),
    ...p.swing(1, 16),
    ...p.rest(1500),
    ...p.swing(0, 6),
    ...p.swing(0, -6),
    ...p.swing(0, 6), // gentle
  ];
  expect(seen).not.toContain(true);
});

it("a deliberate three-swing shake at 14-18 m/s² opens it once", () => {
  const p = phone();
  p.rest(300);
  const shake = [...p.swing(0, 15), ...p.swing(0, -17), ...p.swing(0, 14)];
  expect(shake.filter(Boolean)).toHaveLength(1);
  expect(shake).toContain(true);
  expect(p.shaken.swings()).toBe(3);
  expect(p.shaken.peak()).toBeGreaterThanOrEqual(14);
  // Not again within five seconds; again after.
  expect([
    ...p.swing(0, -16),
    ...p.swing(0, 16),
    ...p.swing(0, -16),
  ]).not.toContain(true);
  p.rest(5000);
  expect([...p.swing(1, 16), ...p.swing(1, -16), ...p.swing(1, 16)]).toContain(
    true,
  );
});

it("a sideways shake counts as much as an up-and-down one", () => {
  // |reading| - g, which v0.93 used, gives a 15 m/s² sideways swing only about 8.
  const sideways = phone();
  sideways.rest(300);
  expect([
    ...sideways.swing(0, 15),
    ...sideways.swing(0, -15),
    ...sideways.swing(0, 15),
  ]).toContain(true);
  const upAndDown = phone();
  upAndDown.rest(300);
  expect([
    ...upAndDown.swing(2, 15),
    ...upAndDown.swing(2, -15),
    ...upAndDown.swing(2, 15),
  ]).toContain(true);
});
