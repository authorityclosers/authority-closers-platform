import {
  ReviewFrameStore,
  REVIEW_LIMITS,
  progressReceipt,
} from "./sales-xray-review-store.mjs";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export async function boundedJson(
  response,
  limit = REVIEW_LIMITS.responseBytes,
) {
  if (
    !response.ok ||
    !response.headers.get("content-type")?.includes("application/json") ||
    !response.body
  )
    return null;
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        void reader.cancel().catch(() => {});
        return null;
      }
      chunks.push(Buffer.from(value));
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return null;
  } finally {
    reader.releaseLock();
  }
}

export function createReviewService({
  fetcher,
  upstreamOrigin,
  store = new ReviewFrameStore(),
} = {}) {
  const read = async (callId, headers) => {
    const response = await fetcher(
      new URL(
        `/v1/conversation/acquisition/submissions/${callId}`,
        upstreamOrigin,
      ),
      {
        method: "GET",
        headers,
        redirect: "manual",
        cache: "no-store",
        credentials: "omit",
        signal: AbortSignal.timeout(10_000),
      },
    );
    return progressReceipt(await boundedJson(response));
  };
  const response = (status, body) => ({ status, body });
  return {
    store,
    async handle({ pathname, search, method, session, headers, body }) {
      if (!session)
        return response(401, {
          detail: "Sign in to the local workspace to review a saved call.",
        });
      if (search) return response(404, { detail: "Unknown review address." });
      const isStart = method === "POST" && pathname === "/__review/api/start";
      const isReset = method === "POST" && pathname === "/__review/api/reset";
      const isCatalog =
        method === "GET" && pathname === "/__review/api/catalog";
      const match =
        method === "GET" &&
        /^\/__review\/api\/frames\/([0-9a-f-]{36})$/.exec(pathname);
      if (!isStart && !isReset && !isCatalog && !match)
        return response(404, { detail: "Unknown review action." });
      if (isReset) {
        store.reset(session);
        return response(200, { reset: true });
      }
      if (isStart) {
        if (!body || Object.keys(body).length !== 1 || !UUID.test(body.call_id))
          return response(400, { detail: "Choose one valid saved call." });
        store.start(session, body.call_id);
      }
      const scope = store.scope(session);
      if (!scope)
        return response(404, {
          detail:
            "No active capture. Choose a call; old or expired states are not reconstructed.",
        });
      try {
        const receipt = await read(scope.callId, headers);
        if (!store.authorize(session, receipt, scope.epoch))
          return response(403, {
            detail:
              "Review access could not be verified. The capture is unavailable.",
          });
        store.observe(session, receipt, scope.epoch);
        const value = match
          ? store.frame(session, match[1])
          : store.catalog(session);
        return value
          ? response(200, value)
          : response(404, {
              detail: "Not captured, expired, or removed from this review.",
            });
      } catch {
        // A failed authorization read never renews access from cached success.
        if (store.scope(session)?.epoch === scope.epoch) store.reset(session);
        return response(503, {
          detail:
            "Live access check failed. Start capture again when the connection returns.",
        });
      }
    },
  };
}
