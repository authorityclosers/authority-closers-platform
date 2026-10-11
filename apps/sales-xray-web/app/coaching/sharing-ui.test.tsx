import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fictionalCoaching } from "./coaching.fixture";
import { FocusFeedback, SharePanel } from "./sharing-ui";

let root: Root, host: HTMLDivElement;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    b.textContent?.includes(name),
  )!;
const flush = () => act(async () => new Promise((r) => setTimeout(r, 0)));
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("Sharing my coaching", () => {
  it("is private by default and one tap shares with the named admins", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        json({
          available: true,
          shared: false,
          revision: 0,
          reaches: [{ name: "Asha Rao", why: "admin" }],
        }),
      )
      .mockResolvedValueOnce(
        json({
          available: true,
          shared: true,
          revision: 1,
          reaches: [{ name: "Asha Rao", why: "admin" }],
        }),
      );
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<SharePanel />));
    await flush();
    expect(host.textContent).toContain("Private");
    expect(host.textContent).toContain("Only you can see it");
    expect(host.textContent).toContain("Asha Rao");
    await act(async () => button("Share with your admins").click());
    await flush();
    const [path, init] = fetch.mock.calls[1];
    expect(path).toBe("/v1/me/coaching/sharing");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({
      shared: true,
      expected_revision: 0,
    });
    expect(host.textContent).toContain("Stop sharing");
    expect(host.textContent).toContain("Shared");
  });
  it("says a Personal workspace has nobody to share with", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json({ available: false, shared: false, revision: 0, reaches: [] }),
        ),
    );
    await act(async () => root.render(<SharePanel />));
    await flush();
    expect(host.textContent).toContain("only you can see this coaching");
    expect(host.querySelector("button")).toBeNull();
  });
  it("keeps the old state and reloads after a conflicting change", async () => {
    const view = { available: true, shared: false, revision: 0, reaches: [] };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(view))
      .mockResolvedValueOnce(json({}, 409))
      .mockResolvedValueOnce(json({ ...view, shared: true, revision: 1 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<SharePanel />));
    await flush();
    await act(async () => button("Share with your admins").click());
    await flush();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(host.textContent).toContain("Stop sharing");
  });
});

describe("Focus feedback", () => {
  it("records agreement once with the visible focus and mission", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <FocusFeedback
          focusSkillId="problem_impact_desire"
          originSubmissionId={fictionalCoaching.mission!.origin_submission_id}
        />,
      ),
    );
    await act(async () => button("Agree").click());
    await flush();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body).toMatchObject({
      agreement: "agree",
      focus_skill_id: "problem_impact_desire",
      mission_origin_submission_id:
        fictionalCoaching.mission!.origin_submission_id,
    });
    expect(body.command_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(host.textContent).toContain("Recorded.");
    expect(button("Not completely").disabled).toBe(true);
  });
  it("answers the reflection question with one tap, kept as context", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <FocusFeedback
          focusSkillId="problem_impact_desire"
          originSubmissionId={fictionalCoaching.mission!.origin_submission_id}
          question="What made you respond that way in this moment?"
        />,
      ),
    );
    expect(host.textContent).toContain(
      "What made you respond that way in this moment?",
    );
    await act(async () => button("I noticed it later").click());
    await flush();
    const first = JSON.parse(fetch.mock.calls[0][1].body);
    expect(fetch.mock.calls[0][0]).toBe("/v1/me/coaching/context");
    expect(first).toMatchObject({
      context: "I noticed it later",
      focus_skill_id: "problem_impact_desire",
    });
    expect(button("I noticed it later").getAttribute("aria-pressed")).toBe(
      "false",
    );
    // A retry of the same answer repeats its command; it then shows chosen.
    await act(async () => button("I noticed it later").click());
    await flush();
    const retry = JSON.parse(fetch.mock.calls[1][1].body);
    expect(retry.command_id).toBe(first.command_id);
    expect(button("I noticed it later").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(host.textContent).toContain("Saved as your context.");
    // A different answer is a new note, never a repeat of the first.
    await act(async () => button("I forgot in the moment").click());
    await flush();
    const other = JSON.parse(fetch.mock.calls[2][1].body);
    expect(other.command_id).not.toBe(first.command_id);
    expect(other.context).toBe("I forgot in the moment");
  });
  it("keeps the learner's own context, trimmed, and shows it back", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <FocusFeedback
          focusSkillId="problem_impact_desire"
          originSubmissionId={fictionalCoaching.mission!.origin_submission_id}
        />,
      ),
    );
    await act(async () => button("Add context").click());
    const area = host.querySelector("textarea")!;
    expect(area.maxLength).toBe(1000);
    expect(button("Save").disabled).toBe(true);
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )!.set!;
      setter.call(area, "  ग्राहक was in a hurry  ");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button("Save").click());
    await flush();
    expect(fetch.mock.calls[0][0]).toBe("/v1/me/coaching/context");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body).toMatchObject({
      context: "ग्राहक was in a hurry",
      focus_skill_id: "problem_impact_desire",
    });
    expect(host.textContent).toContain("Saved: “ग्राहक was in a hurry”");
    expect(host.querySelector("textarea")).toBeNull();
  });
  it("a different choice after a failed try is a new answer, not a conflict", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await act(async () =>
      root.render(
        <FocusFeedback
          focusSkillId="problem_impact_desire"
          originSubmissionId={fictionalCoaching.mission!.origin_submission_id}
        />,
      ),
    );
    await act(async () => button("Agree").click());
    await flush();
    await act(async () => button("Not completely").click());
    await flush();
    const [first, second] = fetch.mock.calls.map(
      (call) => JSON.parse(call[1].body).command_id,
    );
    expect(first).not.toBe(second);
    expect(host.textContent).toContain("Recorded.");
  });
});

describe("Sharing failures", () => {
  it("keeps a failed tap's message after the panel reloads", async () => {
    const view = {
      available: true,
      shared: false,
      revision: 0,
      reaches: [{ name: "Priya Shah", why: "admin" }],
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(view))
      .mockResolvedValueOnce(json({}, 500))
      .mockResolvedValueOnce(json(view));
    vi.stubGlobal("fetch", fetch);
    await act(async () => root.render(<SharePanel />));
    await flush();
    await act(async () => button("Share with your admins").click());
    await flush();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(host.textContent).toContain("Not saved. Try again.");
    expect(host.textContent).toContain("Share with your admins");
  });
});
