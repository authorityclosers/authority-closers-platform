import { challengeAnswer, challengeToken } from "../../openai-apps-challenge";
import { notHere, publicOrigin } from "../../oauth-discovery";

export const dynamic = "force-dynamic";

/** ChatGPT app directory domain verification: the portal's token as plain text. */
export function GET(request: Request) {
  const origin = publicOrigin(request.headers);
  const token = origin
    ? challengeToken(new URL(origin).host, process.env.AC_OPENAI_APPS_CHALLENGE)
    : null;
  return token ? challengeAnswer(token) : notHere();
}
