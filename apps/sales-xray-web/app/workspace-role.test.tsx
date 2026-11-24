// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const access = vi.hoisted(() => ({ value: null as unknown }));
vi.mock("./workspace-access", () => ({
  useWorkspaceAccess: () => access.value,
}));

import { LAST_ROLE_KEY, useCanHere } from "./workspace-role";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function Probe() {
  const answer = useCanHere()("leads.manage");
  return <p>{String(answer)}</p>;
}

const loading = { status: "loading", workspaces: undefined, context: null };
const ready = (role: string) => ({
  status: "ready",
  context: { tenantId: "t1" },
  workspaces: [{ tenant_id: "t1", kind: "organisation", role }],
});

// v1.96 device polish, lane P: on slow 3G a seller saw the owner's Settings
// for 30 s; the last role seen here answers while the real one loads.
it("answers from the last role this browser saw while the role loads, and stores the role only", async () => {
  access.value = loading;
  await act(async () => root.render(<Probe />));
  expect(host.textContent).toBe("null");

  access.value = ready("member");
  await act(async () => root.render(<Probe key="seller" />));
  expect(host.textContent).toBe("false");
  expect(localStorage.getItem(LAST_ROLE_KEY)).toBe("member");

  access.value = loading;
  await act(async () => root.render(<Probe key="cold" />));
  expect(host.textContent).toBe("false");

  access.value = ready("owner");
  await act(async () => root.render(<Probe key="owner" />));
  expect(host.textContent).toBe("true");
  expect(localStorage.getItem(LAST_ROLE_KEY)).toBe("owner");
});
