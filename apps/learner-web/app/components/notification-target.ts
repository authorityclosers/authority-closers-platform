export function ownedTargetHref(href: string | null): string | null {
  if (!href || !href.startsWith("/") || href.startsWith("//")) return null;
  // Browsers normalize backslashes into URL separators.
  if (/[\\\u0000-\u001f\u007f]/.test(href) || /%(?:2f|5c)/i.test(href))
    return null;
  try {
    const parsed = new URL(href, "https://learner.invalid");
    if (parsed.origin !== "https://learner.invalid") return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}
