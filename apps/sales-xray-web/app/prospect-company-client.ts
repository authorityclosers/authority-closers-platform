import {
  parseCompanyDetail,
  parseCompanyList,
  type CompanyListPage,
  type CompanyReadBinding,
  type CompanyRecord,
} from "./prospect-company-contract";
import { UUID_RE } from "./prospects-client";

export const COMPANIES_API = "/v1/conversation/companies";
export type CompanyRead<T> =
  | { status: "ready"; binding: CompanyReadBinding; data: T }
  | { status: "unavailable"; message: string };
export type CompanyReader = (
  path: string,
  signal: AbortSignal,
) => Promise<unknown>;

async function browserRead(path: string, signal: AbortSignal) {
  const response = await fetch(path, {
    method: "GET",
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("company_read_rejected");
  return readCompanyResponseBody(response);
}

/** Bounded JSON shared by Company reads and explicit human-save acknowledgements. */
export async function readCompanyResponseBody(
  response: Response,
): Promise<unknown> {
  if (Number(response.headers.get("content-length")) > 131072)
    throw new Error("company_read_too_large");
  if (!response.body) throw new Error("company_read_empty");
  const stream = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await stream.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > 131072) throw new Error("company_read_too_large");
      chunks.push(part.value);
    }
  } finally {
    await stream.cancel();
    stream.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(body),
  ) as unknown;
}

/** One bounded read for server preload or an explicit browser refresh. No writes. */
async function read<T>(
  binding: CompanyReadBinding,
  path: () => string,
  parse: (value: unknown) => T,
  options: {
    signal?: AbortSignal;
    reader?: CompanyReader;
    deadlineMs?: number;
  },
): Promise<CompanyRead<T>> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const signal = options.signal;
  const deadline = options.deadlineMs ?? 2500;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    if (
      ![binding.personId, binding.tenantId, binding.sessionId].every((id) =>
        UUID_RE.test(id),
      ) ||
      !Number.isFinite(deadline) ||
      deadline < 1 ||
      deadline > 15000 ||
      signal?.aborted
    )
      throw new Error("company_read_scope_unavailable");
    signal?.addEventListener("abort", abort, { once: true });
    const requestPath = path();
    const cancelled = new Promise<never>((_, reject) => {
      controller.signal.addEventListener(
        "abort",
        () => reject(new Error("company_read_cancelled")),
        { once: true },
      );
      timer = setTimeout(() => controller.abort(), deadline);
    });
    const raw = await Promise.race([
      Promise.resolve().then(() =>
        (options.reader ?? browserRead)(requestPath, controller.signal),
      ),
      cancelled,
    ]);
    if (controller.signal.aborted) throw new Error("company_read_cancelled");
    return { status: "ready", binding: { ...binding }, data: parse(raw) };
  } catch {
    return {
      status: "unavailable",
      message: "Companies are unavailable. Try again.",
    };
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    controller.abort();
  }
}

export function readCompanies(
  binding: CompanyReadBinding,
  options: {
    search?: string;
    offset?: number;
    signal?: AbortSignal;
    reader?: CompanyReader;
    deadlineMs?: number;
  } = {},
): Promise<CompanyRead<CompanyListPage>> {
  const scope = { ...binding };
  return read(
    scope,
    () => {
      const offset = options.offset ?? 0;
      const search = options.search ?? "";
      if (
        !Number.isSafeInteger(offset) ||
        offset < 0 ||
        typeof search !== "string" ||
        search.length > 160
      )
        throw new Error("company_query_invalid");
      const query = new URLSearchParams({
        limit: "20",
        offset: String(offset),
      });
      if (search) query.set("search", search);
      return `${COMPANIES_API}?${query}`;
    },
    (value) => {
      const page = parseCompanyList(value, scope);
      if (
        page.next_offset !== null &&
        (page.next_offset <= (options.offset ?? 0) || !page.companies.length)
      )
        throw new Error("company_pagination_invalid");
      return page;
    },
    options,
  );
}

export function readCompany(
  binding: CompanyReadBinding,
  companyId: string,
  options: {
    signal?: AbortSignal;
    reader?: CompanyReader;
    deadlineMs?: number;
  } = {},
): Promise<CompanyRead<CompanyRecord>> {
  const scope = { ...binding };
  return read(
    scope,
    () => {
      if (!UUID_RE.test(companyId)) throw new Error("company_id_invalid");
      return `${COMPANIES_API}/${companyId}`;
    },
    (value) => parseCompanyDetail(value, scope, companyId),
    options,
  );
}
