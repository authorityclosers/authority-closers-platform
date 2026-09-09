import { request as httpRequest } from "node:http";
import { debuglog } from "node:util";

const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
const initialHttpDiagnostics = ["http", "https", "net", "tls"].some(
  (name) => debuglog(name).enabled,
);

export function assertLocalAdminNativePrivacy(): void {
  const mask = process.env.NODE_DEBUG ?? "";
  const pattern = mask
    .replace(/[|\\{}()[\]^$+?.]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/,/g, "$|^");
  const enabled = new RegExp(`^${pattern}$`, "i");
  if (
    initialHttpDiagnostics ||
    ["HTTP", "HTTPS", "NET", "TLS"].some((name) => enabled.test(name))
  ) {
    throw new Error(
      "Local admin requires native HTTP diagnostics disabled before startup. Use scripts/Start-LocalPlatform.ps1.",
    );
  }
}

/** Development-only caller supplies a fixed loopback destination and trusted Host.
 * Native fetch deliberately does not preserve Host overrides on supported Node 24.
 * This narrow wire adapter does; it neither resolves remote DNS nor follows redirects.
 */
export async function fetchLocalAdminWire(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  assertLocalAdminNativePrivacy();
  const url = new URL(String(input));
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    url.username ||
    url.password
  ) {
    throw new Error(
      "Local admin transport requires an uncredentialed numeric HTTP loopback URL.",
    );
  }
  if (init?.body != null && !(init.body instanceof ArrayBuffer)) {
    throw new Error(
      "Local admin transport accepts only a bounded ArrayBuffer body.",
    );
  }
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      url,
      {
        method: init?.method ?? "GET",
        headers: Object.fromEntries(new Headers(init?.headers)),
        signal: init?.signal ?? undefined,
      },
      (incoming) => {
        const chunks: Buffer[] = [];
        let size = 0;
        incoming.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) {
            incoming.destroy(
              new Error(
                "Local admin response exceeded the bounded response limit.",
              ),
            );
            return;
          }
          chunks.push(chunk);
        });
        incoming.on("error", reject);
        incoming.on("end", () => {
          const headers = new Headers();
          for (let index = 0; index < incoming.rawHeaders.length; index += 2) {
            const name = incoming.rawHeaders[index];
            if (
              ["connection", "transfer-encoding", "content-length"].includes(
                name.toLowerCase(),
              )
            )
              continue;
            headers.append(name, incoming.rawHeaders[index + 1]);
          }
          headers.set("cache-control", "private, no-store");
          headers.set("x-ac-dev-data-mode", "local-admin-sandbox");
          const status = incoming.statusCode ?? 502;
          const body =
            [204, 205, 304].includes(status) || init?.method === "HEAD"
              ? null
              : new Uint8Array(Buffer.concat(chunks));
          resolve(new Response(body, { status, headers }));
        });
      },
    );
    request.on("error", reject);
    request.end(
      init?.body instanceof ArrayBuffer ? Buffer.from(init.body) : undefined,
    );
  });
}
