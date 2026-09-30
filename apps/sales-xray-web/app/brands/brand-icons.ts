"use client";

import { useEffect, useSyncExternalStore } from "react";

// Brand icons come from our own site (public/brands/, built from Simple
// Icons), never from a third-party CDN, so no brand a call mentions leaves
// us. Paths load one first-letter file at a time, only when a brand shows.

export type IndexedBrand = Readonly<{
  name: string;
  slug: string;
  hex: string;
}>;

const paths = new Map<string, string>();
const loading = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();
let index: Map<string, IndexedBrand> | null = null;
let indexLoading: Promise<void> | null = null;

const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
const fileOf = (slug: string) => (/^[a-z]/.test(slug) ? slug[0] : "0");
/** Names compare without case, spaces or punctuation: "Whats App" = "whatsapp". */
export const brandKey = (name: string) =>
  name.toLocaleLowerCase().replace(/[\s.'’&+-]+/g, "");

async function readJson<T>(url: string, empty: T): Promise<T> {
  try {
    const response = await fetch(url);
    return response.ok ? ((await response.json()) as T) : empty;
  } catch {
    return empty;
  }
}

function loadPaths(slug: string) {
  const file = fileOf(slug);
  let job = loading.get(file);
  if (!job) {
    job = readJson<Record<string, string>>(`/brands/${file}.json`, {}).then(
      (found) => {
        for (const [key, path] of Object.entries(found)) paths.set(key, path);
        notify();
      },
    );
    loading.set(file, job);
  }
  return job;
}

function loadIndex() {
  indexLoading ??= readJson<{ icons?: Array<[string[], string, string]> }>(
    "/brands/index.json",
    {},
  ).then((found) => {
    const next = new Map<string, IndexedBrand>();
    for (const [names, slug, hex] of found.icons ?? [])
      for (const name of names)
        if (!next.has(brandKey(name)))
          next.set(brandKey(name), { name: names[0], slug, hex });
    index = next;
    notify();
  });
  return indexLoading;
}

/** The icon path for a brand's Simple Icons slug; null until (or unless) it loads. */
export function useBrandPath(slug: string | null): string | null {
  const path = useSyncExternalStore(
    subscribe,
    () => (slug ? (paths.get(slug) ?? null) : null),
    () => null,
  );
  useEffect(() => {
    if (slug && !paths.has(slug)) void loadPaths(slug);
  }, [slug]);
  return path;
}

/**
 * Any of about 3,200 brands by name ("Discord", "Notion", "Duolingo"), for
 * names that come from a person or a tagged report rather than our curated
 * list. Undefined while the index loads, null when the name is not a brand.
 */
export function useIndexedBrand(
  name: string | null,
): IndexedBrand | null | undefined {
  const found = useSyncExternalStore(
    subscribe,
    () =>
      !name ? null : index ? (index.get(brandKey(name)) ?? null) : undefined,
    () => undefined,
  );
  useEffect(() => {
    if (name && !index) void loadIndex();
  }, [name]);
  return found;
}
