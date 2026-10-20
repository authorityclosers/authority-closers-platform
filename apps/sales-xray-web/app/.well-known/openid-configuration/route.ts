import {
  authorizationServerMetadata,
  discoveryAnswer,
  notHere,
  publicOrigin,
} from "../../oauth-discovery";

export const dynamic = "force-dynamic";

/** Some MCP hosts look for OpenID Connect discovery first: the same Connect metadata as RFC 8414. */
export function GET(request: Request) {
  const origin = publicOrigin(request.headers);
  return origin
    ? discoveryAnswer(authorizationServerMetadata(origin))
    : notHere();
}
