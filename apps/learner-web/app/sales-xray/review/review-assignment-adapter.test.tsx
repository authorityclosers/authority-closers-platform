// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewAssignmentAdapter } from "./review-assignment-adapter";
import {
  assignmentResponse,
  ids,
  submissionResponse,
} from "./review-assignment-fixture";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
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
  vi.unstubAllGlobals();
});
const flush = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};
function button(label: string) {
  return [...container.querySelectorAll("button")].find(
    (item) => item.textContent === label,
  )!;
}
function fill() {
  const textarea = container.querySelector("textarea")!;
  Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )!.set!.call(textarea, "Saved browser feedback.");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  const select = container.querySelector("select")!;
  select.value = "high";
  select.dispatchEvent(new Event("change", { bubbles: true }));
}
describe("mounted Academy review route adapter", () => {
  it("loads the actual DTO, saves feedback and reads it again after remount", async () => {
    let saved: ReturnType<typeof submissionResponse>[] = [];
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(_input);
        if (url.endsWith("/submissions") && init?.method === "POST") {
          const body = JSON.parse(String(init.body));
          const item = submissionResponse(body);
          saved = [item];
          return Response.json(item, { status: 201 });
        }
        if (url.endsWith("/submissions"))
          return Response.json({ items: saved });
        return Response.json(assignmentResponse());
      },
    );
    vi.stubGlobal("fetch", fetcher);
    await act(async () => {
      root.render(<ReviewAssignmentAdapter assignmentId={ids.assignment} />);
      await flush();
    });
    expect(container.querySelector("main.learner-main")).not.toBeNull();
    expect(container.textContent).toContain("No feedback has been saved");
    await act(async () => fill());
    await act(async () => {
      button("Save feedback").click();
      await flush();
    });
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Feedback saved.",
    );
    expect(container.textContent).toContain("Saved browser feedback.");
    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => {
      root.render(<ReviewAssignmentAdapter assignmentId={ids.assignment} />);
      await flush();
    });
    expect(container.textContent).toContain("Saved browser feedback.");
    expect(container.textContent).toContain(ids.submission);
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith("/submissions") && init?.method !== "POST",
      ),
    ).toHaveLength(2);
  });

  it("preserves the form and confirmed save when history refresh fails", async () => {
    let failHistory = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST")
          return Response.json(
            submissionResponse(JSON.parse(String(init.body))),
          );
        if (String(input).endsWith("/submissions")) {
          if (failHistory) throw new Error("History temporarily unavailable");
          return Response.json({ items: [] });
        }
        return Response.json(assignmentResponse());
      }),
    );
    await act(async () => {
      root.render(<ReviewAssignmentAdapter assignmentId={ids.assignment} />);
      await flush();
    });
    await act(async () => fill());
    await act(async () => {
      button("Save feedback").click();
      await flush();
    });
    failHistory = true;
    await act(async () => {
      button("Refresh history").click();
      await flush();
    });
    expect(container.textContent).toContain("History temporarily unavailable");
    expect(container.textContent).toContain("Saved browser feedback.");
    expect(container.querySelector("textarea")?.value).toBe(
      "Saved browser feedback.",
    );
  });

  it("shows permission failure and successfully retries without inventing a report", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          Response.json({ message: "unavailable" }, { status: 403 }),
        )
        .mockResolvedValueOnce(Response.json(assignmentResponse()))
        .mockResolvedValueOnce(Response.json({ items: [] })),
    );
    await act(async () => {
      root.render(<ReviewAssignmentAdapter assignmentId={ids.assignment} />);
      await flush();
    });
    expect(container.textContent).toContain("expired or been revoked");
    expect(container.querySelector("audio")).toBeNull();
    await act(async () => {
      button("Retry assignment").click();
      await flush();
    });
    expect(container.textContent).toContain("Synthetic conversation review");
    expect(container.querySelector("audio")?.getAttribute("src")).toContain(
      ids.assignment,
    );
  });
});
