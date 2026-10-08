import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { join } from "node:path";
import { Readable } from "node:stream";
import {
  downloadsDir,
  readDownloads,
  safeFileName,
} from "../../../get-apps/downloads";
import { sessionStatus } from "../../../get-apps/session";

export const runtime = "nodejs";
const privateHeaders = { "cache-control": "private, no-store" };

// CI's static preview has no authenticated server or published artifacts.
export function generateStaticParams() {
  return [{ file: "unavailable" }];
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ file: string }> },
) {
  if (process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1")
    return Response.json(
      { error: "Downloads require the signed-in app" },
      { status: 401, headers: privateHeaders },
    );
  const status = await sessionStatus(request.headers.get("cookie"));
  if (status !== 200)
    return Response.json(
      {
        error:
          status === 401 ? "Sign in to download" : "Account check unavailable",
      },
      { status, headers: privateHeaders },
    );
  const { file } = await params;
  let handle;
  try {
    if (!safeFileName(file)) throw new Error("invalid_name");
    const manifest = await readDownloads();
    const entry = manifest?.files.find((entry) => entry.name === file);
    const directory = downloadsDir();
    if (!entry || !directory) throw new Error("unpublished");
    handle = await open(
      join(directory, file),
      constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
    );
    const info = await handle.stat();
    if (!info.isFile() || info.size !== entry.size)
      throw new Error("invalid_file");
    return new Response(
      Readable.toWeb(handle.createReadStream()) as ReadableStream,
      {
        headers: {
          ...privateHeaders,
          "content-type": "application/octet-stream",
          "content-length": String(info.size),
          "content-disposition": `attachment; filename="${file}"`,
          "x-content-type-options": "nosniff",
          "content-security-policy": "sandbox",
        },
      },
    );
  } catch {
    await handle?.close();
    return Response.json(
      { error: "Download unavailable" },
      { status: 404, headers: privateHeaders },
    );
  }
}
