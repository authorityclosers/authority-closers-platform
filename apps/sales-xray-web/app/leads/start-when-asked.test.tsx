import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StartWhenAsked } from "./start-when-asked";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Start calling from the command palette or a nudge starts Call Next's round,
// once per ask, even when the list mounts again (orchestrator, 9 Nov 2026).
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

function Owner({ onStart }: { onStart: () => void }) {
  const [asked, setAsked] = useState(0);
  const [served, setServed] = useState(0);
  const [list, setList] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setAsked((n) => n + 1)}>
        Ask
      </button>
      <button type="button" onClick={() => setList((on) => !on)}>
        List
      </button>
      {list ? (
        <StartWhenAsked
          asked={asked}
          served={served}
          onServed={setServed}
          onStart={onStart}
        />
      ) : null}
    </>
  );
}

const press = async (name: string) => {
  const button = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === name,
  );
  await act(async () => button?.click());
};

it("starts the round once for each ask, and not again when the list mounts again", async () => {
  const start = vi.fn();
  await act(async () => root.render(<Owner onStart={start} />));
  expect(start).not.toHaveBeenCalled();
  await press("Ask");
  expect(start).toHaveBeenCalledTimes(1);
  // The list goes (a refresh) and comes back: nothing new was asked.
  await press("List");
  await press("List");
  expect(start).toHaveBeenCalledTimes(1);
  // Asked while the list is away (a nudge before it loaded): it starts once
  // the list is there.
  await press("List");
  await press("Ask");
  expect(start).toHaveBeenCalledTimes(1);
  await press("List");
  expect(start).toHaveBeenCalledTimes(2);
});
