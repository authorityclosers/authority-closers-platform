import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import * as prospectsClient from "../prospects-client";
import { ProspectsListView } from "./prospects-list-view";
import { ProspectDetailView } from "./prospect-detail-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href} data-next-client-link="true">
      {children}
    </a>
  ),
}));

let root: Root;
let host: HTMLDivElement;

const mockAccess: WorkspaceAccessValue = {
  status: "ready",
  authenticated: true,
  context: {
    personId: "22222222-2222-4222-8222-222222222222",
    sessionId: "33333333-3333-4333-8333-333333333333",
    tenantId: "44444444-4444-4444-8444-444444444444",
  },
  retry: vi.fn(),
};

const mockProspectSummary: prospectsClient.ProspectSummary = {
  prospect_id: "11111111-1111-4111-8111-111111111111",
  name: "Acme Corp Prospect",
  revision: 2,
  owner_person_id: "22222222-2222-4222-8222-222222222222",
  stage: null,
  tags: [],
  photo_url: null,
  contact: null,
  fields: [],
  buyer_intent: null,
  next_step: null,
  last_promise: null,
  call_count: 2,
  last_call: "2026-10-05T00:00:00+00:00",
};

const mockCall: prospectsClient.ProspectCall = {
  submission_id: "33333333-3333-4333-8333-333333333333",
  recording_id: "44444444-4444-4444-8444-444444444444",
  created_at: "2026-10-05T00:00:00+00:00",
  duration_seconds: 180,
  display_name: "Follow-up Discussion",
  state: "report_ready",
  has_report: true,
  score: null,
  call_url: "/analysis/calls/33333333-3333-4333-8333-333333333333",
  report_url: "/analysis/calls/33333333-3333-4333-8333-333333333333",
  snapshot: {
    snapshot_id: "55555555-5555-4555-8555-555555555555",
    snapshot_kind: "c5_checkpoint",
    source_revision: 1,
    source_sha256:
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    run_id: null,
    transcript_revision: "scribe-response-r1",
    review_status: "draft_not_dipak_adjudicated",
    interpretations: [
      {
        source: {
          text: "The buyer asks about pricing and implementation timeline.",
          evidence: [
            {
              segment_id: "s1",
              quote:
                "how fast can we get started and what are the license tiers?",
              start_ms: 12000,
              end_ms: 18500,
            },
          ],
        },
        possible_concern:
          "Buyer is evaluating near-term onboarding feasibility.",
        interpretation_kind: "inference",
      },
    ],
  },
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

describe("ProspectsListView", () => {
  it("renders empty state when no prospects exist", async () => {
    vi.spyOn(prospectsClient, "fetchProspectsList").mockResolvedValueOnce({
      schema: "ac.sales-xray.prospects/1",
      prospects: [],
      total: 0,
      stage_filters: [],
      next_offset: null,
    });

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectsListView />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(
      host.querySelector('[data-testid="empty-prospects"]'),
    ).not.toBeNull();
    expect(host.textContent).toContain("No prospects recorded yet");
  });

  it("renders prospects list with initials and missing stage badge", async () => {
    vi.spyOn(prospectsClient, "fetchProspectsList").mockResolvedValueOnce({
      schema: "ac.sales-xray.prospects/1",
      prospects: [mockProspectSummary],
      total: 1,
      stage_filters: [],
      next_offset: null,
    });

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectsListView />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(host.textContent).toContain("Acme Corp Prospect");
    expect(host.textContent).toContain("2 calls");
    expect(host.textContent).toContain("Missing stage");
    // Initials for Acme Corp Prospect
    expect(host.textContent).toContain("AC");
  });

  it("shows hover summary card with UUID identity and metadata on mouse enter", async () => {
    vi.spyOn(prospectsClient, "fetchProspectsList").mockResolvedValueOnce({
      schema: "ac.sales-xray.prospects/1",
      prospects: [mockProspectSummary],
      total: 1,
      stage_filters: [],
      next_offset: null,
    });

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectsListView />
        </WorkspaceAccessContext.Provider>,
      );
    });

    const hoverBtn = host.querySelector<HTMLButtonElement>(
      `button[aria-label="Hover summary for ${mockProspectSummary.name}"]`,
    );
    expect(hoverBtn).not.toBeNull();

    await act(async () => {
      hoverBtn!.focus();
    });

    const hoverCard = host.querySelector(
      `[data-testid="hover-card-${mockProspectSummary.prospect_id}"]`,
    );
    expect(hoverCard).not.toBeNull();
    expect(hoverCard?.textContent).toContain(mockProspectSummary.prospect_id);
    expect(hoverCard?.textContent).toContain("2");
    expect(hoverCard?.textContent).toContain("None recorded");
  });

  it("handles missing stage filter toggle", async () => {
    const listSpy = vi
      .spyOn(prospectsClient, "fetchProspectsList")
      .mockResolvedValue({
        schema: "ac.sales-xray.prospects/1",
        prospects: [],
        total: 0,
        stage_filters: [],
        next_offset: null,
      });

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectsListView />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ stage: null }),
    );

    const missingBtn = Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "Missing stage",
    );
    expect(missingBtn).toBeDefined();

    await act(async () => {
      missingBtn!.click();
    });

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ stage: "__missing__" }),
    );
  });

  it("renders error state with retry button on fetch failure", async () => {
    vi.spyOn(prospectsClient, "fetchProspectsList").mockRejectedValueOnce(
      new Error("Saved prospects could not be loaded."),
    );

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectsListView />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(host.textContent).toContain("Saved prospects could not be loaded.");
    expect(host.querySelector('[role="alert"] button')?.textContent).toContain(
      "Try again",
    );
  });
});

describe("ProspectDetailView", () => {
  const detailData: prospectsClient.ProspectDetail = {
    schema: "ac.sales-xray.prospects/1",
    prospect: mockProspectSummary,
    calls: [mockCall],
    next_offset: null,
    promises: [],
    next_steps: [],
    buyer_intent_history: [],
  };

  it("renders prospect header with name, initials and visibly missing fields", async () => {
    vi.spyOn(prospectsClient, "fetchProspectDetail").mockResolvedValueOnce(
      detailData,
    );

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectDetailView prospectId="11111111-1111-4111-8111-111111111111" />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(host.textContent).toContain("Acme Corp Prospect");
    expect(host.textContent).toContain(
      "ID: 11111111-1111-4111-8111-111111111111",
    );
    expect(host.textContent).toContain("Revision 2");
    expect(host.textContent).toContain("Missing (using initials)");
    expect(host.textContent).toContain("No contact details");
    expect(host.textContent).toContain("No confirmed profile fields");
    expect(host.textContent).toContain("Unassigned");
    expect(host.textContent).toContain("No tags");
    expect(host.textContent).toContain("Not scored");
    expect(host.textContent).toContain("None recorded");
  });

  it("renders authorized calls with status, duration, call links, and null score", async () => {
    vi.spyOn(prospectsClient, "fetchProspectDetail").mockResolvedValueOnce(
      detailData,
    );

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectDetailView prospectId="11111111-1111-4111-8111-111111111111" />
        </WorkspaceAccessContext.Provider>,
      );
    });

    expect(host.textContent).toContain("Authorized Calls (2)");
    expect(host.textContent).toContain("Follow-up Discussion");
    expect(host.textContent).toContain("3m 0s");
    expect(host.textContent).toContain("State: report_ready");
    expect(host.textContent).toContain("Score: —");

    const callLink = host.querySelector<HTMLAnchorElement>(
      'a[aria-label="View call 33333333-3333-4333-8333-333333333333"]',
    );
    expect(callLink?.getAttribute("href")).toBe(
      "/analysis/calls/33333333-3333-4333-8333-333333333333",
    );

    const reportLink = host.querySelector<HTMLAnchorElement>(
      'a[aria-label="Open report for call 33333333-3333-4333-8333-333333333333"]',
    );
    expect(reportLink?.getAttribute("href")).toBe(
      "/analysis/calls/33333333-3333-4333-8333-333333333333",
    );
  });

  it("renders per-call hypothesis snapshot with provenance, interpretations and evidence quotes", async () => {
    vi.spyOn(prospectsClient, "fetchProspectDetail").mockResolvedValueOnce(
      detailData,
    );

    await act(async () => {
      root.render(
        <WorkspaceAccessContext.Provider value={mockAccess}>
          <ProspectDetailView prospectId="11111111-1111-4111-8111-111111111111" />
        </WorkspaceAccessContext.Provider>,
      );
    });

    const snapshotEl = host.querySelector(
      '[data-testid="call-snapshot-55555555-5555-4555-8555-555555555555"]',
    );
    expect(snapshotEl).not.toBeNull();
    expect(snapshotEl?.textContent).toContain(
      "Per-call hypothesis (c5_checkpoint)",
    );
    expect(snapshotEl?.textContent).toContain("rev 1");
    expect(snapshotEl?.textContent).toContain("scribe-response-r1");
    expect(snapshotEl?.textContent).toContain("inference");
    expect(snapshotEl?.textContent).toContain(
      "The buyer asks about pricing and implementation timeline.",
    );
    expect(snapshotEl?.textContent).toContain(
      "how fast can we get started and what are the license tiers?",
    );
    expect(snapshotEl?.textContent).toContain("00:12 – 00:18");
  });
});
