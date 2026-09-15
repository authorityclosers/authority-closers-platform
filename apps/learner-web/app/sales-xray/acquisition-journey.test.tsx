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
let accepted: boolean, claimed: boolean, needsClaim: boolean;
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
const mount = async (library = false) => {
  await act(async () => root.render(library ? <CallsPage /> : <Page />));
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
  accepted = needsClaim = false;
  claimed = true;
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
      if (path.endsWith("/source") && init.method === "PUT")
        return json(
          { ...progress, duration_ms: 5000, allowance: remaining },
          202,
        );
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
      if (path.endsWith(`/submissions/${submissionId}`))
        return json({
          ...progress,
          has_report: accepted,
          state: accepted ? "report_ready" : "ready",
        });
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
  await click("Transcript & moments");
  expect(host.textContent).toContain("कल timing discuss करूया.");
  expect(requests.filter(({ init }) => init.method === "PUT")).toHaveLength(1);
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
    expect(host.querySelector('a[href="/login"]')).not.toBeNull();
    expect(host.querySelector('script[src*="turnstile"]')).toBeNull();
    expect(
      host.querySelector<HTMLInputElement>('input[type="file"]')?.disabled ??
        true,
    ).toBe(true);
    expect(mutationRequests()).toHaveLength(0);
    expect(host.querySelector('[aria-label="Sales call report"]')).toBeNull();
  },
);

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

it("opens an account library result in the learner report route without processing it", async () => {
  await mount(true);
  expect(host.querySelectorAll("main")).toHaveLength(1);
  expect(host.querySelector(".studio-header")).toBeNull();
  expect(host.textContent).toContain("Report ready");
  await click("Open call");
  expect(navigate).toHaveBeenCalledWith(`/sales-xray?call=${submissionId}`);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(submissionId);
  expect(mutationRequests()).toHaveLength(0);
});
