// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";

import { InitialSessionProvider, useInitialSession } from "./initial-session";

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
  expect(await seen("/organisation")).toBe("browser");
  expect(await seen(null)).toBe("browser");
  await act(async () => root.unmount());
});
