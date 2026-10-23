// @vitest-environment happy-dom
import { beforeEach, expect, it } from "vitest";

import {
  fixtureBilling,
  fixtureRecording,
  resetFixtureBilling,
  seedFixtureBilling,
  setFixtureRecording,
} from "./fixture-billing";

beforeEach(() => {
  resetFixtureBilling();
  setFixtureRecording(false);
});

it("starts the journey on the trial with no order", async () => {
  expect(await seedFixtureBilling("trial")).toBeNull();
  const { current } = await fixtureBilling.readSubscriptions("personal");
  expect(current).toBeNull();
});

it("leaves an order waiting on the test payment page", async () => {
  const orderId = await seedFixtureBilling("pending");
  const order = await fixtureBilling.readOrder(orderId!);
  expect(order.status).not.toBe("paid");
});

it("pays a Personal month, which can still be refunded", async () => {
  const orderId = await seedFixtureBilling("paid");
  const order = await fixtureBilling.readOrder(orderId!);
  expect(order.status).toBe("paid");
  expect(order.refund?.state).toBe("available");
  const { current } = await fixtureBilling.readSubscriptions("personal");
  expect(current?.status).toBe("active");
});

it("refunds it, taking the minutes back and ending the plan", async () => {
  const before = (await fixtureBilling.readUsage()).allowance;
  const orderId = await seedFixtureBilling("refunded");
  const order = await fixtureBilling.readOrder(orderId!);
  expect(order.refund?.state).toBe("refunded");
  const { current } = await fixtureBilling.readSubscriptions("personal");
  expect(current).toBeNull();
  expect((await fixtureBilling.readUsage()).allowance.availableSeconds).toBe(
    before.availableSeconds,
  );
});

it("cancels the renewal, keeping access to the end of the period", async () => {
  await seedFixtureBilling("cancelled");
  const { current } = await fixtureBilling.readSubscriptions("personal");
  expect(current?.cancelAtPeriodEnd).toBe(true);
});

it("remembers recording mode for the tab", () => {
  expect(fixtureRecording()).toBe(false);
  setFixtureRecording(true);
  expect(fixtureRecording()).toBe(true);
  setFixtureRecording(false);
  expect(fixtureRecording()).toBe(false);
});
