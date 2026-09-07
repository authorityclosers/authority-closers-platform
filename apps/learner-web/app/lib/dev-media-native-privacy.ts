import { debuglog } from "node:util";

/** Match Node's debuglog mask semantics, including case and wildcard handling. */
export function nativeHttpDiagnosticsEnabled(
  mask: string | undefined,
): boolean {
  if (!mask) return false;
  const pattern = mask
    .replace(/[|\\{}()[\]^$+?.]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/,/g, "$|^");
  const enabled = new RegExp(`^${pattern}$`, "i");
  return enabled.test("HTTP") || enabled.test("HTTPS");
}

// Node captures debug settings before user code. A later environment change
// cannot safely disable an already initialized native logger. The launcher
// removes NODE_DEBUG in the learner child before its process starts; direct
// startup and subsequent media calls also fail closed here.
const initialNativeHttpDiagnostics =
  debuglog("http").enabled || debuglog("https").enabled;

export function assertDevelopmentMediaNativePrivacy(): void {
  if (
    initialNativeHttpDiagnostics ||
    nativeHttpDiagnosticsEnabled(process.env.NODE_DEBUG)
  ) {
    throw new Error(
      "Local staging media requires native HTTP diagnostics to be disabled before startup. Use scripts/Start-LocalStagingBridge.ps1.",
    );
  }
}
