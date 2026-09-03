import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/dev-api-proxy", () => ({
  isStagingAuthenticatedBridge: vi.fn(),
}));

import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { DevStagingBridgeNotice } from "./dev-staging-bridge-notice";

describe("DevStagingBridgeNotice", () => {
  beforeEach(() => {
    vi.mocked(isStagingAuthenticatedBridge).mockReset();
  });

  it("stays out of production when the authenticated bridge is disabled", () => {
    vi.mocked(isStagingAuthenticatedBridge).mockReturnValue(false);

    expect(renderToStaticMarkup(createElement(DevStagingBridgeNotice))).toBe(
      "",
    );
  });

  it("renders a collapsed, non-layout-blocking disclosure in local bridge mode", () => {
    vi.mocked(isStagingAuthenticatedBridge).mockReturnValue(true);

    const html = renderToStaticMarkup(createElement(DevStagingBridgeNotice));

    expect(html).toContain("<details");
    expect(html).toContain("Dev · staging data");
    expect(html).not.toContain(' open="');
    expect(html).toContain("real staging learner account");
  });
});
