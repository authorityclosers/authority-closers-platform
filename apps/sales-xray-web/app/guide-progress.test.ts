import { beforeEach, expect, it, vi } from "vitest";
import { GuideProgressStore, guideProgressKey } from "./guide-progress";
import {
  eligibleGuideSteps,
  FIRST_CALL_GUIDE,
  type GuideDefinition,
} from "./guide-registry";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

it("resumes one user's step without sharing dismissal with another user or version", () => {
  const store = new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE);
  store.update({ stepId: "upload", status: "active" });
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .stepId,
  ).toBe("upload");
  store.update({ stepId: "upload", status: "skipped" });
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot()
      .status,
  ).toBe("skipped");
  expect(
    new GuideProgressStore("fictional-b", FIRST_CALL_GUIDE).getSnapshot(),
  ).toEqual({ stepId: "welcome", status: "active" });
  expect(
    new GuideProgressStore("fictional-a", {
      ...FIRST_CALL_GUIDE,
      version: "2",
    }).getSnapshot().status,
  ).toBe("active");
});

it.each([
  "{broken",
  '{"stepId":"missing","status":"active"}',
  '{"stepId":"welcome","status":"paid"}',
  "null",
])("recovers invalid progress: %s", (raw) => {
  localStorage.setItem(guideProgressKey("fictional-a", FIRST_CALL_GUIDE), raw);
  expect(
    new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE).getSnapshot(),
  ).toEqual({ stepId: "welcome", status: "active" });
});

it("works without localStorage and publishes changes to subscribers", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  const store = new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE);
  const listener = vi.fn();
  const unsubscribe = store.subscribe(listener);
  store.update({ stepId: "listen", status: "active" });
  expect(store.getSnapshot().stepId).toBe("listen");
  expect(listener).toHaveBeenCalledOnce();
  unsubscribe();
});

it("synchronises a same-user dismissal from another tab and ignores other users", () => {
  const store = new GuideProgressStore("fictional-a", FIRST_CALL_GUIDE);
  const listener = vi.fn();
  const unsubscribe = store.subscribe(listener);
  const key = store.key;
  localStorage.setItem(
    key,
    JSON.stringify({ stepId: "report", status: "completed" }),
  );
  window.dispatchEvent(new StorageEvent("storage", { key: "another-user" }));
  expect(listener).not.toHaveBeenCalled();
  window.dispatchEvent(new StorageEvent("storage", { key }));
  expect(store.getSnapshot()).toEqual({
    stepId: "report",
    status: "completed",
  });
  unsubscribe();
});

it("hides unavailable screens and only exposes owner steps to an organisation owner", () => {
  const first = FIRST_CALL_GUIDE.steps[0];
  const guide: GuideDefinition = {
    ...FIRST_CALL_GUIDE,
    steps: [
      first,
      { ...first, id: "invite", ownerOnly: true },
      { ...first, id: "policy", available: false, ownerOnly: true },
    ],
  };
  expect(eligibleGuideSteps(guide, false).map((step) => step.id)).toEqual([
    "welcome",
  ]);
  expect(eligibleGuideSteps(guide, true).map((step) => step.id)).toEqual([
    "welcome",
    "invite",
  ]);
  expect(
    FIRST_CALL_GUIDE.steps.some((step) =>
      step.href?.startsWith("/organisation"),
    ),
  ).toBe(false);
});
