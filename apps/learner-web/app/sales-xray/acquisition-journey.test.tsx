// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigate }),
}));
import Page from "./page";
import CallsPage from "./calls/page";
import {
  allowance,
  entry,
  envelope,
  plan,
  policy,
  progress,
  submissionId,
  transcript,
} from "../../../sales-xray-web/tests/acquisition-fixture";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
// Keep the actual route, workspace gate, upload studio, library and report
// mounted. The surrounding Academy chrome has its own integration coverage.
vi.mock("../components/site-shell", () => ({
  LearnerShell: ({
    children,
    current,
  }: {
    children: ReactNode;
    current: string;
  }) => <div data-learner-current={current}>{children}</div>,
}));

let root: Root, host: HTMLDivElement;
let requests: { path: string; init: RequestInit }[];
let workspaceStatus: number, entryStatus: number, sessionStatus: number;
let profileEligible: boolean;
let accepted: boolean, claimed: boolean, needsClaim: boolean;
let sourcePresent: boolean;
let navigate: ReturnType<typeof vi.spyOn>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const remaining = {
  ...allowance,
  committed_seconds: 5,
  available_seconds: 5995,
};
const flush = async () => {
  await act(async () => {
    for (let n = 0; n < 20; n++) await Promise.resolve();
  });
};
const button = (text: string) => {
  const found = [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(found, text).toBeDefined();
  return found!;
};
const click = async (text: string) => {
  await act(async () => button(text).click());
  await flush();
};
const mount = async (library = false, callId?: string) => {
  if (callId)
    window.history.replaceState(null, "", `/sales-xray?call=${callId}`);
  const page = library ? (
    <CallsPage />
  ) : (
    await Page({
      searchParams: Promise.resolve(callId ? { call: callId } : {}),
    })
  );
  await act(async () => root.render(page));
  await flush();
};
const mutationRequests = () =>
  requests.filter(({ init }) =>
    ["POST", "PUT", "DELETE"].includes(init.method ?? ""),
  );

beforeEach(() => {
  vi.useFakeTimers();
  requests = [];
  workspaceStatus = entryStatus = sessionStatus = 200;
  profileEligible = true;
  accepted = needsClaim = false;
  claimed = true;
  sourcePresent = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  navigate = vi.spyOn(window.location, "assign").mockImplementation(() => {});
  vi.stubGlobal("crypto", {
    randomUUID: () => submissionId,
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      requests.push({ path, init });
      if (path === "/v1/me/sales-xray-profile/write-eligibility")
        return new Response(null, { status: profileEligible ? 204 : 403 });
      if (path === "/v1/me/sales-xray-profile")
        return json({
          name: profileEligible ? "Synthetic Learner" : null,
          email: "learner@example.invalid",
          phone_number_e164: profileEligible ? "+12025550123" : null,
          phone_verified: false,
          profile_complete: profileEligible,
          revision: 1,
        });
      if (path === "/v1/auth/email-code/config?surface=sales_xray")
        return json({
          enabled: true,
          consent_version: "synthetic-consent-v1",
          google_enabled: false,
          expires_in_seconds: 600,
          resend_after_seconds: 60,
        });
      if (path === "/v1/me/workspaces")
        return json(
          {
            person_id: "person-1",
            session_id: "session-1",
            selected_tenant_id: "tenant-1",
            workspaces: [{ tenant_id: "tenant-1", name: "Synthetic Academy" }],
          },
          workspaceStatus,
        );
      if (path.endsWith("/entry"))
        return json(
          {
            ...entry,
            auth_mode: "account",
            site_key: null,
            challenge_action: null,
          },
          entryStatus,
        );
      if (path.endsWith("/upload-policy")) return json(policy);
      if (path.endsWith("/session")) {
        expect(init.method).not.toBe("POST");
        return json(
          {
            state: needsClaim ? "claim_required" : "account",
            allowance: remaining,
          },
          sessionStatus,
        );
      }
      if (path.endsWith("/claim")) {
        needsClaim = false;
        claimed = true;
        return json({ state: "claimed", allowance: remaining });
      }
      if (path.endsWith("/source") && init.method === "PUT") {
        sourcePresent = true;
        return json(
          { ...progress, duration_ms: 5000, allowance: remaining },
          202,
        );
      }
      if (path.endsWith("/plan/quote")) return json(plan, 201);
      if (path.endsWith("/plan")) {
        accepted = true;
        return json(
          { ...plan, accepted: true, state: "active", current_stage: "C2" },
          202,
        );
      }
      if (path.endsWith("/transcript")) return json(transcript);
      if (path.endsWith("/report"))
        return json({
          ...envelope,
          report: {
            ...envelope.report,
            access: claimed ? "claimed_account" : "guest_preview",
          },
        });
      if (path.endsWith(`/submissions/${submissionId}`)) {
        if (!sourcePresent) return json({ detail: "Not found" }, 404);
        return json({
          ...progress,
          has_report: accepted,
          state: accepted ? "report_ready" : "ready",
        });
      }
      if (path.endsWith("/submissions"))
        return json({
          submissions: [
            {
              submission_id: submissionId,
              created_at: "2026-09-14T06:30:00Z",
              duration_seconds: 5,
              state: "report_ready",
              has_report: true,
            },
          ],
          next_cursor: null,
        });
      throw new Error("Unexpected learner journey request");
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("runs the actual learner upload and report journey under one Academy main and shared allowance", async () => {
  sourcePresent = false;
  await mount();
  expect(host.querySelectorAll("main")).toHaveLength(1);
  expect(
    host.querySelector('[data-learner-current="sales-xray"]'),
  ).not.toBeNull();
  expect(host.querySelector(".studio-header")).toBeNull();
  expect(
    host.querySelector('[aria-label="Sales Xray account navigation"]'),
  ).toBeNull();
  expect(host.textContent).toContain("Remaining analysis time · 99m 55s");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["synthetic"], "Learner call.wav", {
    type: "audio/wav",
  });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new ArrayBuffer(10),
  });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  await flush();
  expect(button("Analyse my call").disabled).toBe(true);
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await flush();
  expect(button("Analyse my call").disabled).toBe(false);
  expect(host.querySelector('script[src*="turnstile"]')).toBeNull();
  await click("Analyse my call");
  expect(host.querySelector('input[type="checkbox"]')).toBeNull();
  expect(host.textContent).not.toContain("Maximum processing cost");
  expect(host.textContent).not.toContain("synthetic-provider");
  expect(host.querySelector('[aria-label="Sales call report"]')).not.toBeNull();
  expect(host.textContent).toContain(envelope.report.content.summary);
  expect(host.textContent).not.toContain("Sign in to save this call");
  expect(host.textContent).toContain("Remaining analysis time · 99m 55s");
  expect(host.querySelector("audio")?.getAttribute("src")).toBe(
    `/v1/conversation/acquisition/submissions/${submissionId}/source`,
  );
  expect(button("Reading view").getAttribute("aria-pressed")).toBe("true");
  await click("Tabbed view");
  await click("Moments");
  expect(host.textContent).toContain("कल timing discuss करूया.");
  expect(requests.filter(({ init }) => init.method === "PUT")).toHaveLength(1);
  const sourceUploadIndex = requests.findIndex(
    ({ init }) => init.method === "PUT",
  );
  expect(
    requests
      .slice(0, sourceUploadIndex)
      .some(({ path }) => path.endsWith(`/submissions/${submissionId}`)),
  ).toBe(true);
  expect(requests.filter(({ path }) => path.endsWith("/plan"))).toHaveLength(1);
  expect(requests.filter(({ path }) => path.endsWith("/session"))).toHaveLength(
    1,
  );
  for (const { path, init } of requests) {
    expect(path).toMatch(/^\/v1\//);
    expect(init.credentials).toBe("same-origin");
    expect(init.redirect).toBe("error");
  }
  await act(async () => root.unmount());
  root = createRoot(host);
  const before = mutationRequests().length;
  await mount();
  expect(host.querySelector('[aria-label="Sales call report"]')).not.toBeNull();
  expect(mutationRequests()).toHaveLength(before);
  expect(host.textContent).toContain("Remaining analysis time · 99m 55s");
});

it.each(["workspace", "entry", "session"])(
  "requires AC sign-in after %s 401 without minting a guest or loading Turnstile",
  async (boundary) => {
    if (boundary === "workspace") workspaceStatus = 401;
    if (boundary === "entry") entryStatus = 401;
    if (boundary === "session") sessionStatus = 401;
    await mount();
    expect(host.textContent).toContain("Sign in");
    if (boundary === "workspace") {
      await click("Sign in");
      expect(host.querySelector("#account-auth-heading")).not.toBeNull();
      expect(host.querySelector("#account-email")).not.toBeNull();
    } else {
      expect(host.querySelector('a[href="/login"]')).not.toBeNull();
    }
    expect(host.querySelector('script[src*="turnstile"]')).toBeNull();
    expect(
      host.querySelector<HTMLInputElement>('input[type="file"]')?.disabled ??
        true,
    ).toBe(true);
    expect(mutationRequests()).toHaveLength(0);
    expect(host.querySelector('[aria-label="Sales call report"]')).toBeNull();
  },
);

it("keeps learner audio local when the canonical profile is incomplete", async () => {
  profileEligible = false;
  await mount();
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["synthetic"], "Pending learner call.wav", {
    type: "audio/wav",
  });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new ArrayBuffer(10),
  });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () =>
    input.dispatchEvent(new Event("change", { bubbles: true })),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await click("Analyse my call");
  expect(host.querySelector("#account-profile-heading")).not.toBeNull();
  expect(host.textContent).toContain(file.name);
  expect(mutationRequests()).toHaveLength(0);
  expect(host.querySelector('[aria-label="Sales call report"]')).toBeNull();
});

it("keeps a pending ownership claim explicit and restores its report without re-uploading", async () => {
  needsClaim = true;
  claimed = false;
  accepted = true;
  localStorage.setItem("ac.xray.submission.v1", submissionId);
  await mount();
  expect(host.textContent).toContain("Keep this call with your AC account");
  expect(host.querySelector('[aria-label="Sales call report"]')).toBeNull();
  expect(mutationRequests()).toHaveLength(0);
  await click("Save to my account");
  expect(host.querySelector('[aria-label="Sales call report"]')).not.toBeNull();
  expect(mutationRequests().map(({ path }) => path)).toEqual([
    "/v1/conversation/acquisition/claim",
  ]);
  expect(host.textContent).toContain("Remaining analysis time · 99m 55s");
});

it("shows a neutral opening state while a learner deep link is checked, then opens the saved report", async () => {
  accepted = claimed = true;
  let releaseSavedRead!: () => void;
  const savedReadGate = new Promise<void>((resolve) => {
    releaseSavedRead = resolve;
  });
  const originalFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (...args) => {
    const [path, init] = args;
    if (
      String(path).endsWith(`/submissions/${submissionId}`) &&
      init?.method !== "DELETE"
    )
      await savedReadGate;
    return originalFetch(...args);
  });

  await mount(false, submissionId);
  expect(host.querySelector('[data-stage="opening"]')).not.toBeNull();
  expect(host.textContent).toContain("Opening your saved call");
  expect(host.textContent).not.toContain("Add a call to review");
  expect(host.querySelector('input[type="file"]')).toBeNull();
  expect(mutationRequests()).toHaveLength(0);

  await act(async () => releaseSavedRead());
  await flush();
  expect(host.querySelector('[aria-label="Sales call report"]')).not.toBeNull();
  expect(host.querySelector('[data-stage="opening"]')).toBeNull();
  expect(mutationRequests()).toHaveLength(0);
});

it("shows a restored pending call as processing without returning to upload or accepting work", async () => {
  await mount(false, submissionId);
  expect(host.querySelector('[data-stage="processing"]')).not.toBeNull();
  expect(host.querySelector('[aria-label="Sales call report"]')).toBeNull();
  expect(
    host.querySelector<HTMLInputElement>('input[type="file"]')?.disabled,
  ).toBe(true);
  expect(host.textContent).not.toContain("Start with your sales call");
  expect(mutationRequests()).toHaveLength(0);
});

it("opens an authorized saved report when upload setup reads are unavailable", async () => {
  accepted = claimed = true;
  entryStatus = sessionStatus = 503;
  await mount(false, submissionId);
  expect(host.querySelector('[aria-label="Sales call report"]')).not.toBeNull();
  expect(host.textContent).toContain(envelope.report.content.summary);
  expect(requests.some(({ path }) => path.endsWith("/upload-policy"))).toBe(
    false,
  );
  expect(mutationRequests()).toHaveLength(0);
});

it("opens an account library result in the learner report route without processing it", async () => {
  await mount(true);
  expect(host.querySelectorAll("main")).toHaveLength(1);
  expect(host.querySelector(".studio-header")).toBeNull();
  expect(host.textContent).toContain("Report ready");
  const savedCall = host.querySelector<HTMLButtonElement>(
    `button[data-submission-id="${submissionId}"]`,
  );
  expect(savedCall).not.toBeNull();
  await act(async () => savedCall!.click());
  await flush();
  expect(navigate).toHaveBeenCalledWith(`/sales-xray?call=${submissionId}`);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
  expect(mutationRequests()).toHaveLength(0);
});
