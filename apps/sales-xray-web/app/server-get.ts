import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

/**
 * One GET from this web server to the internal API origin, sending the
 * page's own Host header.
 *
 * fetch() cannot do this: Node replaces any `host` header with the URL's
 * own host. On dev the origin is the loopback edge (127.0.0.1:3016), so
 * the API saw that address, refused it as an unknown host (400), and no
 * page ever arrived with its data (20 Oct 2026).
 *
 * No redirects are followed (a 3xx is just its status), and an answer
 * larger than MAX_ANSWER_BYTES is dropped.
 */
export type ServerAnswer = Readonly<{
  status: number;
  contentType: string | null;
  text: string;
}>;

export const MAX_ANSWER_BYTES = 4 * 1024 * 1024;

export function serverGet(
  url: string,
  headers: Readonly<Record<string, string>>,
  signal: AbortSignal,
): Promise<ServerAnswer> {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const send = target.protocol === "https:" ? httpsRequest : httpRequest;
    const outgoing = send(
      target,
      { method: "GET", headers: { ...headers }, signal },
      (answer) => {
        const chunks: Buffer[] = [];
        let size = 0;
        answer.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_ANSWER_BYTES)
            outgoing.destroy(new Error("The API answer is too large."));
          else chunks.push(chunk);
        });
        answer.on("end", () =>
          resolve({
            status: answer.statusCode ?? 0,
            contentType: answer.headers["content-type"] ?? null,
            text: Buffer.concat(chunks).toString("utf8"),
          }),
        );
        answer.on("error", reject);
        answer.on("close", () => {
          if (!answer.complete)
            reject(new Error("The API answer was cut off."));
        });
      },
    );
    outgoing.on("error", reject);
    outgoing.end();
  });
}
