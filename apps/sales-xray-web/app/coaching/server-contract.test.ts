import { describe, expect, it } from "vitest";
import { parseCoaching } from "./coaching-client";
import { parseCallCoaching } from "./coaching-read";
import contract from "./server-contract.json";
import { parseTeamCoaching } from "./team-contract";

// The Coaching API's own serialized output for fictional call, My and Team
// views (`tests/unit/coaching/test_web_contract.py` writes and checks it).
describe("server contract", () => {
  it("reads one call's coaching with its strength and suggestion count", () => {
    const call = parseCallCoaching(contract.call, contract.call.submission_id);
    expect(call?.state).toBe("ready");
    expect(call?.mission?.origin_submission_id).toBe(
      contract.call.submission_id,
    );
    expect(call?.strength?.title).toBe("Curious follow-up");
    expect(call?.strength?.evidence[0].quote).toBe("Tell me more.");
    expect(call?.other_suggestions).toBe(1);
  });
  it("reads My coaching with its calls and strength", () => {
    const mine = parseCoaching(contract.me);
    expect(mine.focus?.skill_id).toBe(contract.me.focus.skill_id);
    expect(mine.calls).toHaveLength(1);
    expect(mine.strength?.title).toBe("Curious follow-up");
  });
  it("reads anonymous Team coaching", () => {
    const team = parseTeamCoaching(contract.team);
    expect(team?.analysed_calls).toBe(1);
    expect(team?.suggestions.length).toBeGreaterThan(0);
  });
});
