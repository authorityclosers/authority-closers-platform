import type { MetaForm, MetaPage } from "../../leads/sources-view";

export type MetaCatalogue = { configured: boolean; pages: MetaPage[] };
export class MetaRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Reads expire; writes deliberately do not auto-retry or abort an import mid-flight. */
export async function metaRequest<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/v1/lead-desk/meta${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal:
      signal ?? (body === undefined ? AbortSignal.timeout(12000) : undefined),
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const value = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new MetaRequestError(
      value?.detail ?? "Meta didn't answer. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

/** Three independent Page reads at once; one refusal never hides another account's forms. */
export async function refreshForms(
  pages: MetaPage[],
  take: (pageId: string, forms: MetaForm[] | null) => void,
  signal: AbortSignal,
) {
  let index = 0;
  const worker = async () => {
    while (index < pages.length && !signal.aborted) {
      const page = pages[index++];
      try {
        const forms = await metaRequest<MetaForm[]>(
          `/pages/${encodeURIComponent(page.pageId)}/forms`,
          undefined,
          AbortSignal.any([signal, AbortSignal.timeout(12000)]),
        );
        if (!signal.aborted)
          take(page.pageId, Array.isArray(forms) ? forms : null);
      } catch {
        if (!signal.aborted) take(page.pageId, null);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(3, pages.length) }, worker));
}
export const formKey = (page: string, form: string) => `${page}:${form}`;
