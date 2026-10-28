import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OrganisationRules } from "./rules";
import { readTeam, saveSettings } from "../../leads/leads-client";
vi.mock("../../leads/routing-rules", () => ({
  RoutingRules: () => (
    <section>
      <header>
        <h2>Match lead rules</h2>
      </header>
      <button>Try a lead</button>
    </section>
  ),
}));
vi.mock("../../leads/seller-sheet", () => ({
  SellerSheet: ({ rep }: { rep: { name: string } | null }) =>
    rep ? (
      <div role="dialog">Areas, languages and products for {rep.name}</div>
    ) : null,
}));
vi.mock("../../leads/team-view", () => ({
  WorkHoursPanel: () => <div>Work hours</div>,
  TeamView: () => <div>More settings</div>,
}));
vi.mock("../../call-ai/call-ai-client", () => ({
  readCallAi: () => Promise.resolve(null),
}));
vi.mock("../../leads/leads-client", () => ({
  readTeam: vi.fn(),
  saveSettings: vi.fn(),
}));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const team = {
  reps: [
    {
      person_id: "sample",
      name: "Mira Fictional",
      available: true,
      max_open: 25,
    },
  ],
  settings: { revision: 7, auto_reassign: false, reassign_minutes: 35 },
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readTeam).mockResolvedValue(
    team as Awaited<ReturnType<typeof readTeam>>,
  );
  vi.mocked(saveSettings).mockResolvedValue({
    ...team,
    settings: { ...team.settings, revision: 8, auto_reassign: true },
  } as Awaited<ReturnType<typeof readTeam>>);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
async function tap(text: string) {
  const item = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(text),
  );
  expect(item).toBeDefined();
  await act(async () => item!.click());
}
it("opens rule setup instead of a team dashboard", async () => {
  await act(async () => root.render(<OrganisationRules />));
  expect(host.textContent).toContain("Try a lead");
  expect(host.textContent).not.toContain("All leads");
  await tap("Seller rules");
  await tap("Mira Fictional");
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
    "Areas, languages",
  );
  expect(saveSettings).not.toHaveBeenCalled();
});
it("preserves saved wait time and uses its revision for an explicit toggle", async () => {
  await act(async () => root.render(<OrganisationRules />));
  await tap("Limits");
  expect(
    host.querySelector<HTMLInputElement>('[aria-label="Wait in minutes"]')
      ?.value,
  ).toBe("35");
  expect(saveSettings).not.toHaveBeenCalled();
  await tap("Off");
  expect(saveSettings).toHaveBeenCalledWith(7, {
    auto_reassign: true,
    reassign_minutes: 35,
  });
});
