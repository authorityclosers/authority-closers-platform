import {
  discoveryAnswer,
  notHere,
  protectedResourceMetadata,
  publicOrigin,
} from "../../../oauth-discovery";

export const dynamic = "force-dynamic";

/**
 * RFC 9728: /.well-known/oauth-protected-resource/v1/mcp (and /v1/api) names
 * Connect as the place to sign in. The bare path describes the MCP server.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ resource?: string[] }> },
) {
  const origin = publicOrigin(request.headers);
  const { resource } = await params;
  const path = resource?.length ? `/${resource.join("/")}` : "";
  const body = origin ? protectedResourceMetadata(origin, path) : null;
  return body ? discoveryAnswer(body) : notHere();
}
