// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams("status=completed"),
  usePathname: () => "/analysis/calls",
}));
vi.mock("./profile-menu", () => ({ ProfileMenu: () => null }));

import { CallsLibrary } from "./calls-library";
import { CALLS_LIST_PATH, seededLibraryPage } from "./calls-seed";
import { DisplayDatesProvider } from "./display-clock";
import { dayKey } from "./display-dates";
import { UploadSessionProvider } from "./hooks/upload-session";
import { InitialSessionProvider } from "./initial-session";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const row = (id: string, hasReport: boolean) => ({
  submission_id: id,
  created_at: "2026-09-14T06:30:00Z",
  duration_seconds: 61,
  state: hasReport ? "completed" : "processing",
  has_report: hasReport,
});
const listPage = {
  submissions: [row(firstId, true), row(secondId, false)],
  next_cursor: null,
};
const own = new Intl.DateTimeFormat().resolvedOptions();
const dates = {
  locale: own.locale,
  timeZone: own.timeZone,
  today: dayKey(Date.now(), own.timeZone) as string,
};
const context = {
  personId: "person-1",
  sessionId: "session-1",
  tenantId: "t-1",
};

let fetchMock: ReturnType<typeof vi.fn>;
let root: Root | undefined;

beforeEach(() => {
  // Per-call summaries never answer here: the list is what this is about.
  fetchMock = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  vi.unstubAllGlobals();
});

const page = (
  identity: typeof context | null,
  initial: { status: number; body: unknown } | null,
  served: typeof context = context,
) => (
  <InitialSessionProvider
    value={{
      identity: { person_id: served.personId, session_id: served.sessionId },
      directory: { selected_tenant_id: served.tenantId },
    }}
  >
    <UploadSessionProvider>
      <DisplayDatesProvider value={dates}>
        <WorkspaceAccessProvider
          value={{
            status: "ready",
            authenticated: true,
            context: identity,
            retry: () => {},
          }}
        >
          <CallsLibrary insights initial={initial} />
        </WorkspaceAccessProvider>
      </DisplayDatesProvider>
    </UploadSessionProvider>
  </InitialSessionProvider>
);

const listReads = () =>
  fetchMock.mock.calls.filter(([url]) =>
    String(url).endsWith("/submissions?include_owners=true"),
  ).length;

it("takes only a successful, well-formed server read as the first page", () => {
  expect(
    seededLibraryPage({ status: 200, body: listPage })?.submissions,
  ).toHaveLength(2);
  expect(seededLibraryPage({ status: 401, body: listPage })).toBeNull();
  expect(seededLibraryPage({ status: 200, body: { nope: true } })).toBeNull();
  expect(seededLibraryPage(null)).toBeNull();
  expect(seededLibraryPage(undefined)).toBeNull();
  expect(CALLS_LIST_PATH).toBe(
    "/v1/conversation/acquisition/submissions?include_owners=true",
  );
});

it("arrives whole from the server's read and starts without reading the list again", async () => {
  const initial = { status: 200, body: listPage };
  const host = document.createElement("div");
  document.body.append(host);
  host.innerHTML = renderToString(page(context, initial));
  // The server's HTML already has the rows (the address asks for ready ones).
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(host.textContent).toContain("2 saved calls");
  const recoverable = vi.fn();
  await act(async () => {
    root = hydrateRoot(host, page(context, initial), {
      onRecoverableError: recoverable,
    });
  });
  expect(recoverable).not.toHaveBeenCalled();
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(listReads()).toBe(0);
  host.remove();
});

it("reads the list in the browser without a server read, or for another identity", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  host.innerHTML = renderToString(page(context, null));
  await act(async () => {
    root = hydrateRoot(host, page(context, null));
  });
  expect(listReads()).toBe(1);
  // The server read belongs to the session the page started from only.
  await act(async () =>
    root?.render(
      page({ ...context, tenantId: "t-2" }, { status: 200, body: listPage }),
    ),
  );
  expect(listReads()).toBe(2);
  host.remove();
});

it("never seeds a later session (signed in again in place) with the server's read", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // The document was read for session-0; this mount is session-1.
  await act(async () =>
    root?.render(
      page(
        context,
        { status: 200, body: listPage },
        {
          ...context,
          sessionId: "session-0",
        },
      ),
    ),
  );
  expect(listReads()).toBe(1);
  host.remove();
});
