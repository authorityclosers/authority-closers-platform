/**
 * crypto.randomUUID where the browser has none (v1.94, the real-iPhone check):
 * a page served over plain http on a LAN address is not a secure context, so
 * Safari leaves randomUUID out, and opening a lead hit "This screen hit a snag".
 * Real users are on https; a test setup should not break either. The fallback
 * is a version 4 UUID from crypto.getRandomValues, which every browser has.
 */

/** The fallback, as the init script installs it: 16 random bytes, version 4. */
export const UUID_FALLBACK = `function () {
  var b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 15) | 64;
  b[8] = (b[8] & 63) | 128;
  var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join("");
  return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
}`;

/** Run before the app starts (layout.tsx): every crypto.randomUUID() call then works. */
export function uuidInitScript(): string {
  return `try{if(self.crypto&&typeof crypto.getRandomValues==="function"&&typeof crypto.randomUUID!=="function"){crypto.randomUUID=${UUID_FALLBACK};}}catch(e){}`;
}
