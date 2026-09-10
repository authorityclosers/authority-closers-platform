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
  return ["HTTP", "HTTPS", "NET", "TLS"].some((name) => enabled.test(name));
}

// Node captures debug settings before user code. A later environment change
// cannot safely disable an already initialized native logger. The launcher
// removes NODE_DEBUG in the learner child before its process starts; direct
// startup and subsequent media calls also fail closed here.
const initialNativeHttpDiagnostics = ["http", "https", "net", "tls"].some(
  (name) => debuglog(name).enabled,
);

export function assertDevelopmentMediaNativePrivacy(): void {
  if (
    initialNativeHttpDiagnostics ||
    nativeHttpDiagnosticsEnabled(process.env.NODE_DEBUG)
  ) {
    throw new Error(
      "Local media requires native network diagnostics to be disabled before startup. Use the managed local launcher.",
    );
  }
}
