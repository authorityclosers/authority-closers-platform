/**
 * An email address as page text. Cloudflare's email obfuscation rewrites any
 * address it finds in the served HTML, so the page React hydrates no longer
 * matches what it rendered (React error #418 on /privacy, 19 Oct) and its
 * decoder script fails on SVG links (/apps). A line-break opportunity after
 * the "@" keeps the address out of its pattern; it reads, wraps and copies
 * the same.
 */
export function EmailText({ address }: { address: string }) {
  const at = address.indexOf("@");
  if (at < 0) return address;
  return (
    <>
      {address.slice(0, at + 1)}
      <wbr />
      {address.slice(at + 1)}
    </>
  );
}
