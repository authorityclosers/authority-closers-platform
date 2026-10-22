import { act, useMemo } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Command } from "./command-bar";
import {
  addCommandSource,
  useCommandSource,
  useRegisteredCommands,
} from "./command-registry";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const command = (label: string): Command => ({
  id: label,
  group: "Actions",
  label,
  icon: null,
  run: vi.fn(),
});

function Screen({ label }: { label: string }) {
  const source = useMemo(
    () => ({
      commands: [command(label)],
      search: async () => [command(`Found by ${label}`)],
    }),
    [label],
  );
  useCommandSource(label, source);
  return null;
}

function Shell() {
  const { commands, searches } = useRegisteredCommands();
  return (
    <p>
      {commands.map((c) => c.label).join(",")}|{searches.length}
    </p>
  );
}

it("lists a screen's commands and search while it is mounted", async () => {
  await act(async () =>
    root.render(
      <>
        <Shell />
        <Screen label="Start calling" />
      </>,
    ),
  );
  expect(host.textContent).toBe("Start calling|1");
  await act(async () => root.render(<Shell />));
  expect(host.textContent).toBe("|0");
});

it("keeps the newest source for a key, and a stale removal changes nothing", () => {
  const first = addCommandSource("lead", { commands: [command("Call Asha")] });
  const removeSecond = addCommandSource("lead", {
    commands: [command("Call Ravi")],
  });
  // The first one's removal comes late: Ravi stays.
  first();
  act(() => root.render(<Shell />));
  expect(host.textContent).toBe("Call Ravi|0");
  act(() => removeSecond());
  expect(host.textContent).toBe("|0");
});
