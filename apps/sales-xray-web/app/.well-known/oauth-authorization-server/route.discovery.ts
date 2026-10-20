import {
  authorizationServerMetadata,
  discoveryAnswer,
  notHere,
  publicOrigin,
} from "../../oauth-discovery";

export const dynamic = "force-dynamic";

/** RFC 8414: how apps and MCP hosts sign people in with Connect. */
export function GET(request: Request) {
  const origin = publicOrigin(request.headers);
  return origin
    ? discoveryAnswer(authorizationServerMetadata(origin))
    : notHere();
}
