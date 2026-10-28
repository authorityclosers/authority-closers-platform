// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import { forgetPipelines, usePipelines } from "./use-pipelines";
import { readPipelines, type PipelinesView } from "./journey/journey-client";

vi.mock("./journey/journey-client", () => ({ readPipelines: vi.fn() }));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  forgetPipelines();
  vi.mocked(readPipelines).mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const workspace = (tenantId: string): WorkspaceAccessValue => ({
  status: "ready",
  authenticated: true,
  context: {
    personId: "fictional-seller",
    sessionId: "fictional-session",
    tenantId,
  },
  retry: () => undefined,
});
const pipes = (key: string): PipelinesView => ({
  pipelines: [
    {
      key,
      name: key,
      position: 0,
      main: true,
      sources: [],
      industry: null,
      leads: 0,
    },
  ],
  sources: {},
  canEdit: true,
});
function Reader() {
  const view = usePipelines();
  return <output>{view?.pipelines[0]?.key ?? "Loading"}</output>;
}
const render = (tenant: string, children: ReactNode = <Reader />) =>
  act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider value={workspace(tenant)}>
        {children}
      </WorkspaceAccessContext.Provider>,
    ),
  );

it("reads the new workspace instead of reusing the previous workspace's fresh pipelines", async () => {
  vi.mocked(readPipelines).mockResolvedValueOnce(pipes("cedar-pipeline"));
  await render("cedar");
  expect(host.textContent).toBe("cedar-pipeline");
  let finish!: (value: PipelinesView) => void;
  vi.mocked(readPipelines).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  await render("maple");
  expect(host.textContent).toBe("Loading");
  expect(readPipelines).toHaveBeenCalledTimes(2);
  await act(async () => finish(pipes("maple-pipeline")));
  expect(host.textContent).toBe("maple-pipeline");
});

it("does not let an old in-flight workspace read populate the new workspace", async () => {
  let finish!: (value: PipelinesView) => void;
  vi.mocked(readPipelines).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  await render("cedar");
  vi.mocked(readPipelines).mockResolvedValueOnce(pipes("maple-pipeline"));
  await render("maple");
  await act(async () => finish(pipes("cedar-pipeline")));
  expect(host.textContent).toBe("maple-pipeline");
});
