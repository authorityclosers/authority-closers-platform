/**
 * Turning what a person selected on a page into a Sales Xray lead link.
 *
 * The extension never sends anything anywhere itself. It opens Sales Xray's
 * Leads page with the details after "#" (browsers never send that part to a
 * server), and Sales Xray shows Add lead filled in for the person to check.
 */

export const SITES = {
  live: "https://salesxray.authorityclosers.com",
  dev: "https://salesxray-dev.authorityclosers.com",
};

const LIMITS = { name: 200, phone: 40, email: 254, note: 1000 };

/** Name, phone and email from selected text: a contact card, a signature, a chat. */
export function parseContact(text) {
  const source = String(text ?? "").slice(0, 4000);
  const email = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.exec(source)?.[0];
  const rest = email ? source.replace(email, " ") : source;
  const digits = /\+?\d[\d\s().-]{7,}\d/.exec(rest)?.[0];
  const phone = digits ? digits.replace(/[^\d+]/g, "") : undefined;
  const name = source
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*(name|naam|contact)\s*[:-]\s*/i, "")
        .replace(/^[~*\s]+|[*\s]+$/g, ""),
    )
    .find(
      (line) =>
        line.length > 1 &&
        line.length <= 80 &&
        /[A-Za-zऀ-ॿ]/.test(line) &&
        !line.includes("@") &&
        !/\d{5,}/.test(line.replace(/\s/g, "")),
    );
  return {
    name: name || undefined,
    phone: phone && phone.replace(/\D/g, "").length >= 8 ? phone : undefined,
    email,
  };
}

/** The number in a tel: link, as written. */
export function phoneFromTel(url) {
  try {
    return decodeURIComponent(String(url).replace(/^tel:/i, "")).trim();
  } catch {
    return String(url).replace(/^tel:/i, "").trim();
  }
}

/** Where the lead came from, by site name only (never the full address). */
export function fromPage(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host ? `Added from ${host}` : "";
  } catch {
    return "";
  }
}

/** Sales Xray's Leads page with Add lead filled in. */
export function leadLink(site, lead) {
  const base = SITES[site] ?? SITES.live;
  const params = new URLSearchParams({ add: "lead" });
  for (const [key, max] of Object.entries(LIMITS)) {
    const value = String(lead?.[key] ?? "")
      .trim()
      .slice(0, max);
    if (value) params.set(key, value);
  }
  return `${base}/leads#${params.toString()}`;
}

export function deskLink(site) {
  return `${SITES[site] ?? SITES.live}/leads`;
}
