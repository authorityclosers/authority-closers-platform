// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ReviewAssignmentAdapter } from "./review-assignment-adapter";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Academy assigned-review adapter", () => {
  it("keeps the assignment-specific route truthful before the server DTO arrives", async () => {
    await act(async () =>
      root.render(<ReviewAssignmentAdapter assignmentId="assignment-7" />),
    );

    expect(container.textContent).toContain(
      "Your review is waiting for a server assignment.",
    );
    expect(container.textContent).toContain("assignment-7");
    expect(container.textContent).toContain(
      "No report, identity, playback URL, or save result is asserted",
    );
  });
});
