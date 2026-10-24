import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import type { StageView } from "./journey/journey-client";
import { StageTabs, stageTabs } from "./stage-tabs";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const stage = (
  label: string,
  kind: StageView["kind"],
  archived = false,
): StageView => ({
  key: label.toLowerCase().replace(/\s+/g, "_"),
  label,
  kind,
  kindWords: "",
  milestone: "",
  meaning: "",
  archived,
  origin: "",
  leads: 0,
});

// Owner, 22 Oct 2026: stage tabs from the organisation's own stages.
it("names the tabs by the business's own stages, with every stage's count", () => {
  const journey = {
    stages: [
      stage("Enquiry", "new"),
      stage("Site visit booked", "interested"),
      stage("Negotiation", "interested"),
      stage("Old step", "follow_up", true),
      stage("Booked", "won"),
    ],
  };
  const tabs = stageTabs(journey, {
    new: 4,
    interested: 3,
    follow_up: 2,
    won: 1,
  });
  expect(tabs).toEqual([
    { key: "open", label: "All leads", count: 9 },
    { key: "new", label: "Enquiry", count: 4 },
    { key: "interested", label: "Interested", count: 3 },
    { key: "won", label: "Booked", count: 1 },
    { key: "lost", label: "Lost", count: 0 },
    // Junk (Lead OS): fake or unusable, kept apart from Lost, always there.
    { key: "junk", label: "Junk", count: 0 },
  ]);
});

it("falls back to the desk's kinds, without counts until they arrive", () => {
  expect(stageTabs(null, null)).toEqual([
    { key: "open", label: "All leads", count: undefined },
    { key: "new", label: "New", count: undefined },
    { key: "not_connected", label: "Couldn't reach", count: undefined },
    { key: "follow_up", label: "Follow up", count: undefined },
    { key: "interested", label: "Interested", count: undefined },
    { key: "won", label: "Won", count: undefined },
    { key: "lost", label: "Lost", count: undefined },
    { key: "junk", label: "Junk", count: undefined },
  ]);
});

it("marks the chosen tab and reports a tap", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <StageTabs
        tabs={[
          { key: "desk", label: "To call", count: 2 },
          { key: "open", label: "All leads", count: 5 },
        ]}
        current="desk"
        onChange={onChange}
      />,
    ),
  );
  const [desk, open] = host.querySelectorAll('[role="tab"]');
  expect(desk.getAttribute("aria-selected")).toBe("true");
  expect(desk.textContent).toBe("To call2");
  await act(async () => (open as HTMLButtonElement).click());
  expect(onChange).toHaveBeenCalledWith("open");
  await act(async () => root.unmount());
  host.remove();
});
