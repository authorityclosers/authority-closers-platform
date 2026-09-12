// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as sessionApi from "@ac/operations-web/api";
import { AdminSessionProvider } from "../lib/admin-session";
import { AdminShell } from "./admin-shell";
import {
  AdminApiProblem,
  type AdminLearnerLookup,
  type AdminSession,
} from "../lib/admin-api";
import { PeopleRuntime, PEOPLE_READ_TIMEOUT_MS } from "./people-runtime";
import {
  account,
  diagnosis,
  lookup,
  otherId,
  personId,
  tenantId,
} from "../../test-fixtures/people";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const api = {
  lookup: vi.fn<typeof sessionApi.lookupAdminLearners>(),
  diagnose: vi.fn<typeof sessionApi.loadAdminLearnerDiagnosis>(),
};
let host: HTMLDivElement;
let root: Root;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
async function render(refreshKey = "people") {
  await act(async () =>
    root.render(
      <AdminSessionProvider refreshKey={refreshKey}>
        <PeopleRuntime api={api} />
      </AdminSessionProvider>,
    ),
  );
}
async function renderShell() {
  await act(async () =>
    root.render(
      <AdminShell
        active="people"
        eyebrow="People"
        title="Learner records"
        description="Review a learner record"
        surface="people"
      >
        <PeopleRuntime api={api} />
      </AdminShell>,
    ),
  );
}
function button(text: string) {
  const match = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === text,
  );
  if (!match) throw new Error(`Missing button: ${text}`);
  return match;
}
async function choosePurpose(value = "learner_support") {
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function enterQuery(value = "synthetic_learner") {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>("input[type=search]")!;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}
async function search() {
  await choosePurpose();
  await enterQuery();
  await submit();
}
async function selectAndConfirm() {
  await act(async () => button("Select learner").click());
  await act(async () =>
    host.querySelector<HTMLInputElement>("input[type=checkbox]")!.click(),
  );
}
async function openDiagnosis() {
  await search();
  await selectAndConfirm();
  await act(async () => button("Open learner diagnosis").click());
}

beforeEach(() => {
  vi.spyOn(sessionApi, "loadAdminSession").mockResolvedValue(account);
  api.lookup.mockResolvedValue(structuredClone(lookup));
  api.diagnose.mockResolvedValue(structuredClone(diagnosis));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
});

it("waits for verified access and never searches automatically", async () => {
  const pending = deferred<AdminSession>();
  vi.mocked(sessionApi.loadAdminSession).mockReturnValueOnce(pending.promise);
  await render();
  expect(host.textContent).toContain("Checking your account");
  expect(host.querySelector("form")).toBeNull();
  await act(async () => pending.resolve(account));
  expect(button("Find learner").disabled).toBe(true);
  const purposeLabel = host
    .querySelector("select")
    ?.getAttribute("aria-labelledby");
  expect(purposeLabel).toBeTruthy();
  expect(document.getElementById(purposeLabel!)?.textContent).toBe(
    "Review purpose",
  );
  expect(api.lookup).not.toHaveBeenCalled();
  await enterQuery();
  await submit();
  expect(api.lookup).not.toHaveBeenCalled();
});

it("requires both admin surface and learner diagnosis permission", async () => {
  vi.mocked(sessionApi.loadAdminSession).mockResolvedValue({
    ...account,
    permissions: ["learner_diagnose"],
  });
  await render();
  expect(host.textContent).toContain("Learner records are unavailable");
  expect(host.querySelector("form")).toBeNull();
  expect(api.lookup).not.toHaveBeenCalled();
});

it("requires an explicit target and confirmation before returning canonical progress", async () => {
  await render();
  await search();
  expect(api.lookup).toHaveBeenCalledWith(
    expect.objectContaining({
      tenantId,
      purpose: "learner_support",
      query: "synthetic_learner",
    }),
  );
  expect(api.diagnose).not.toHaveBeenCalled();
  expect(host.textContent).toContain("s***@example.test");
  await act(async () => button("Select learner").click());
  expect(button("Open learner diagnosis").disabled).toBe(true);
  await act(async () =>
    host.querySelector<HTMLInputElement>("input[type=checkbox]")!.click(),
  );
  await act(async () => button("Open learner diagnosis").click());
  expect(api.diagnose).toHaveBeenCalledWith(
    expect.objectContaining({ personId, tenantId, purpose: "learner_support" }),
  );
  expect(host.textContent).toContain("1 of 5");
  expect(host.textContent).toContain("revision 3");
  expect(host.textContent).toContain("Prepare your opening");
  expect(host.textContent).not.toContain(personId);
  expect(document.activeElement?.id).toBe("people-diagnosis-title");
});

it("clears selected private records when purpose or search changes", async () => {
  await render();
  await openDiagnosis();
  await choosePurpose("accessibility_review");
  expect(host.textContent).not.toContain("Synthetic Learner");
  expect(host.querySelector("input[type=checkbox]")).toBeNull();
  await submit();
  await selectAndConfirm();
  await act(async () => button("Open learner diagnosis").click());
  await enterQuery("different_learner");
  expect(host.textContent).not.toContain("Practice course");
});

it("treats an empty successful lookup as an empty result", async () => {
  api.lookup.mockResolvedValue({ ...lookup, candidates: [] });
  await render();
  await search();
  expect(host.textContent).toContain("No matching active learner");
  expect(api.diagnose).not.toHaveBeenCalled();
});

it("suppresses same-tick duplicate searches", async () => {
  const pending = deferred<AdminLearnerLookup>();
  api.lookup.mockReturnValue(pending.promise);
  await render();
  await choosePurpose();
  await enterQuery();
  await act(async () => {
    const form = host.querySelector("form")!;
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  expect(api.lookup).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(lookup));
});

it("aborts timed-out reads, offers retry, and ignores a late response", async () => {
  vi.useFakeTimers();
  const pending = deferred<AdminLearnerLookup>();
  api.lookup.mockReturnValueOnce(pending.promise);
  await render();
  await search();
  const signal = api.lookup.mock.calls[0][0].signal!;
  await act(async () => vi.advanceTimersByTime(PEOPLE_READ_TIMEOUT_MS));
  expect(signal.aborted).toBe(true);
  expect(host.textContent).toContain("took too long");
  await act(async () => pending.resolve(lookup));
  expect(host.textContent).not.toContain("Synthetic Learner");
  await submit();
  expect(host.textContent).toContain("Synthetic Learner");
});

it.each([401, 403])(
  "removes private data and search input after access failure %s",
  async (status) => {
    api.diagnose.mockRejectedValue(
      new AdminApiProblem({
        status,
        code: "denied",
        title: "Denied",
        detail: "Private server context must not appear",
        requestId: null,
      }),
    );
    await render();
    await openDiagnosis();
    expect(host.textContent).toContain("Sign in again");
    expect(host.textContent).not.toContain("Synthetic Learner");
    expect(host.textContent).not.toContain("Private server context");
    expect(host.querySelector("input")).toBeNull();
  },
);

it.each([401, 403])(
  "invalidates the shared admin shell after People access failure %s",
  async (status) => {
    api.diagnose.mockRejectedValueOnce(
      new AdminApiProblem({
        status,
        code: "denied",
        title: "Denied",
        detail: "Private server context must not appear",
        requestId: null,
      }),
    );
    await renderShell();
    await openDiagnosis();
    expect(
      host.querySelector('[aria-label="Product admin session denied"]'),
    ).not.toBeNull();
    expect(host.textContent).toContain("No verified tenant context");
    expect(host.textContent).toContain("Sign in");
    expect(host.textContent).not.toContain("Session verified");
    expect(host.textContent).not.toContain("Synthetic Learner");
    expect(host.querySelector("input")).toBeNull();
  },
);

it("clears records when the verified academy changes and ignores abandoned reads", async () => {
  const pending = deferred<AdminLearnerLookup>();
  api.lookup.mockReturnValueOnce(pending.promise);
  await render();
  await search();
  const signal = api.lookup.mock.calls[0][0].signal!;
  vi.mocked(sessionApi.loadAdminSession).mockResolvedValue({
    ...account,
    tenantId: otherId,
  });
  await render("new-academy");
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve(lookup));
  expect(host.textContent).not.toContain("Synthetic Learner");
  expect(
    host.querySelector<HTMLInputElement>("input[type=search]")?.value,
  ).toBe("");
});

it("keeps unavailable progress and truncated records explicit without inferring completion", async () => {
  api.diagnose.mockResolvedValue({
    ...diagnosis,
    truncated: true,
    enrollments: [
      { ...diagnosis.enrollments[0], progress: null, truncated: true },
    ],
  });
  await render();
  await openDiagnosis();
  expect(host.textContent).toContain("Current progress is unavailable");
  expect(host.textContent).toContain("Other enrollments may be present");
  expect(host.textContent).not.toContain("1 of 5");
});

it("does not send a raw UUID lookup", async () => {
  await render();
  await choosePurpose();
  await enterQuery(personId);
  await submit();
  expect(api.lookup).not.toHaveBeenCalled();
  expect(host.textContent).toContain("full email address or public username");
});

it.each([
  {
    drafts: true,
    evidence: false,
    draftText: "No saved draft included in this view.",
    evidenceText: "No evidence returned.",
  },
  {
    drafts: false,
    evidence: true,
    draftText: "No saved draft returned.",
    evidenceText: "No evidence included in this view.",
  },
])(
  "distinguishes independently truncated draft and evidence collections",
  async (item) => {
    api.diagnose.mockResolvedValue({
      ...diagnosis,
      enrollments: [
        {
          ...diagnosis.enrollments[0],
          truncated: true,
          drafts: [],
          evidence: [],
          drafts_truncated: item.drafts,
          evidence_truncated: item.evidence,
        },
      ],
    });
    await render();
    await openDiagnosis();
    expect(host.textContent).toContain(item.draftText);
    expect(host.textContent).toContain(item.evidenceText);
  },
);
