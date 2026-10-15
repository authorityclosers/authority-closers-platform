import { expect, it } from "vitest";

import { reportStoryModel } from "../../../report-story-model";
import { v8Report } from "./v8-report";

it("reads H's fictional v8 projection through the real codec into the six pillars", () => {
  const { report, transcript } = v8Report();
  expect(report.pillars?.version).toBe("report-pillars/1");
  const model = reportStoryModel(report, transcript, {
    roles: { seller: "speaker_0", prospect: "speaker_1" },
  });
  expect(model.picture.outcome).toMatchObject({
    status: "Follow-up Set",
    origin: "call",
  });
  expect(model.flow.phases?.map((phase) => phase.label)).toContain(
    "Work context",
  );
  expect(model.end.strongest).toBe("Specific next conversation");
  expect(model.deal.nextEvent?.text).toBeTruthy();
  expect(model.missing[0]).toEqual([]);
});
