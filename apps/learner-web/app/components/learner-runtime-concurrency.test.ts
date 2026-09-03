import { describe, expect, it } from "vitest";

import {
  createActivityRecoveryHydrationGuard,
  createMembershipCleanupGuard,
  type MembershipCleanupContext,
} from "./learner-runtime";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe("learner runtime concurrency guards", () => {
  it("keeps learner input when delayed recovery hydration completes", async () => {
    const guard = createActivityRecoveryHydrationGuard();
    const recovery = deferred<string>();
    const hydrationGeneration = guard.begin();
    let response = "";

    const hydration = recovery.promise.then((recoveryResponse) => {
      if (guard.canApply(hydrationGeneration)) response = recoveryResponse;
    });

    // This is the user edit that happens while the local recovery read is
    // pending. The delayed completion must not replace it.
    response = "Learner's current answer";
    guard.markLearnerEdit();
    recovery.resolve("Older local recovery answer");
    await hydration;

    expect(response).toBe("Learner's current answer");
    expect(guard.canApply(hydrationGeneration)).toBe(false);
  });

  it("does not publish stale membership cleanup to a newer person generation", async () => {
    const guard = createMembershipCleanupGuard();
    guard.activate();
    const personOne: MembershipCleanupContext = {
      membershipKnown: true,
      membershipAvailable: false,
      personId: "person-1",
    };
    const personTwo: MembershipCleanupContext = {
      membershipKnown: true,
      membershipAvailable: true,
      personId: "person-2",
    };
    const cleanup = deferred<boolean>();
    let status = "idle";
    const firstToken = guard.begin(personOne);
    status = "pending";
    const firstCompletion = cleanup.promise.then((success) => {
      if (guard.canCommit(firstToken, personOne)) {
        status = success ? "success" : "failed";
      }
    });

    const secondToken = guard.begin(personTwo);
    if (guard.canCommit(secondToken, personTwo)) status = "success";
    cleanup.resolve(true);
    await firstCompletion;

    expect(status).toBe("success");
    expect(guard.canCommit(firstToken, personTwo)).toBe(false);
    expect(guard.canCommit(secondToken, personTwo)).toBe(true);
  });
});
