import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/** This page's origin in the browser; empty on the server, so both draw the same. */
export function useOrigin(): string {
  return useSyncExternalStore(
    noSubscription,
    () => window.location.origin,
    () => "",
  );
}

// The customer domain's app sends developers to its own API and MCP hosts (salesxray.in,
// 2 Nov 2026). Every other address serves both itself, as the old one always has and will.
const OWN_HOSTS: Record<string, { api: string; mcp: string }> = {
  "https://app.salesxray.in": {
    api: "https://api.salesxray.in",
    mcp: "https://mcp.salesxray.in",
  },
};

/** Where this page's API and MCP server are: their own hosts on salesxray.in, else here. */
export function addressesFor(origin: string): { api: string; mcp: string } {
  return OWN_HOSTS[origin] ?? { api: origin, mcp: origin };
}
