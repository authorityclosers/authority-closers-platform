// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import {
  InitialSessionProvider,
  serverIdentityKey,
  useInitialSession,
  useServerSeedAllowed,
} from "./initial-session";

const session = { identity: { person_id: "p" }, directory: { workspaces: [] } };

function Probe({ path }: { path: string | null }) {
  return <output>{useInitialSession(path) ? "seeded" : "browser"}</output>;
}

it("hands the server's session only to pages that render on the server", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const seen = async (path: string | null, value = session) => {
    await act(async () =>
      root.render(
        <InitialSessionProvider value={value}>
          <Probe path={path} />
        </InitialSessionProvider>,
      ),
    );
    return host.textContent;
  };
  expect(await seen("/dashboard")).toBe("seeded");
  expect(await seen("/dashboard/")).toBe("seeded");
  expect(await seen("/analysis/calls")).toBe("seeded");
  expect(await seen("/analysis/new")).toBe("browser");
  expect(await seen("/organisation")).toBe("seeded");
  expect(await seen("/coaching")).toBe("seeded");
  expect(await seen(null)).toBe("browser");
  await act(async () => root.unmount());
});

it("names who the server read the document for", () => {
  expect(
    serverIdentityKey({
      identity: { person_id: "p", session_id: "s" },
      directory: { selected_tenant_id: "t" },
    }),
  ).toBe(JSON.stringify(["p", "s", "t"]));
  expect(serverIdentityKey(null)).toBeNull();
  expect(
    serverIdentityKey({
      identity: { person_id: "p", session_id: "s" },
      directory: { selected_tenant_id: null },
    }),
  ).toBeNull();
});

function SeedProbe({ identity }: { identity: string | null }) {
  return <output>{useServerSeedAllowed(identity) ? "seed" : "read"}</output>;
}

it("lets server data seed only the identity it was read for, while the document is new", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const served = {
    identity: { person_id: "p", session_id: "s" },
    directory: { selected_tenant_id: "t" },
  };
  const seen = async (identity: string | null, mount = String(identity)) => {
    await act(async () =>
      root.render(
        <InitialSessionProvider value={served}>
          <SeedProbe key={mount} identity={identity} />
        </InitialSessionProvider>,
      ),
    );
    return host.textContent;
  };
  expect(await seen(JSON.stringify(["p", "s", "t"]))).toBe("seed");
  expect(await seen(JSON.stringify(["p", "s2", "t"]))).toBe("read");
  expect(await seen(JSON.stringify(["p2", "s", "t"]))).toBe("read");
  expect(await seen(null)).toBe("read");
  // Later in the document's life (a page mounting again): the browser reads.
  vi.useFakeTimers({ now: Date.now() + 61_000, toFake: ["Date"] });
  expect(await seen(JSON.stringify(["p", "s", "t"]), "again")).toBe("read");
  vi.useRealTimers();
  await act(async () => root.unmount());
});
