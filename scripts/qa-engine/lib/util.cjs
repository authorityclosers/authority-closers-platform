// Small shared helpers (kept apart so modules do not require each other in a ring).
// A selector that survives rebuilds: no list positions, no hashed CSS-module suffixes, no ids with digits.
function normSelector(selector) {
  return String(selector || "")
    .replace(/:nth-(child|of-type)\(\d+\)/g, ":nth-$1(#)")
    .replace(/(_[a-zA-Z0-9-]+)__[A-Za-z0-9_-]{4,8}\b/g, "$1")
    .replace(/__[A-Za-z0-9_-]{5,8}\b/g, "")
    .replace(/#[\w-]*\d[\w-]*/g, "#id")
    .replace(/\s+/g, " ")
    .slice(0, 70);
}


module.exports = { normSelector };
