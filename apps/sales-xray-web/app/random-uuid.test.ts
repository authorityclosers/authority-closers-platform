import { expect, it } from "vitest";

import { uuidInitScript } from "./random-uuid";

// v1.94 (the real-iPhone check): over plain http Safari has no
// crypto.randomUUID, and opening a lead crashed. The init script adds one.
it("adds a version 4 randomUUID where the browser has none", () => {
  const crypto = {
    getRandomValues: (bytes: Uint8Array) => {
      for (let at = 0; at < bytes.length; at += 1) bytes[at] = (at * 37) % 256;
      return bytes;
    },
  } as {
    getRandomValues: (b: Uint8Array) => Uint8Array;
    randomUUID?: () => string;
  };
  new Function("self", "crypto", uuidInitScript())({ crypto }, crypto);
  const id = crypto.randomUUID?.();
  expect(id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
});

it("leaves the browser's own randomUUID alone", () => {
  const own = () => "own";
  const crypto = { getRandomValues: () => undefined, randomUUID: own };
  new Function("self", "crypto", uuidInitScript())({ crypto }, crypto);
  expect(crypto.randomUUID).toBe(own);
});
