// Which fictional sandbox person stands in for each matrix persona. Sign-in goes through persona-qa's proxy
// (/__as/<alias>), which knows the ten sellers and the owner. Sellers named in the matrix keep their own login; the
// rest take a seller who works both sides, spread by persona number. Owner-side personas (owner, manager, coach)
// use the owner session when persona-qa has issued one; their rows are not claimed by the click runner yet.
const matrix = require("./matrix.cjs");

const NAMED = { Priya: "priya", Rohan: "rohan", Sneha: "sneha", Aditya: "imran", Imran: "imran", Karan: "karan", Pooja: "pooja", Neha: "neha", Farah: "farah" };
const BOTH_SIDES = ["priya", "rohan", "farah", "karan", "pooja"]; // not vikas: kept untouched for first-sign-in journeys
const OWNER_TAGS = /[omk]/; // owner, manager, coach

let table = null;
async function load() {
  if (table) return table;
  const rows = await matrix.personas();
  table = new Map(
    rows.map((p) => {
      const first = p.name.split(" ")[0].replace(/^Mrs?\.$/, p.name.split(" ")[1] || "");
      const number = Number(p.id.slice(1));
      const owner = OWNER_TAGS.test(p.tags || "");
      const alias = owner ? "owner" : NAMED[first] || BOTH_SIDES[number % BOTH_SIDES.length];
      return [p.id, { id: p.id, name: p.name, alias, owner, tags: p.tags || "" }];
    }),
  );
  return table;
}

module.exports = {
  load,
  aliasFor: async (id) => ((await load()).get(id) || {}).alias || "priya",
  sellerIds: async () => [...(await load()).values()].filter((p) => !p.owner).map((p) => p.id),
  ownerIds: async () => [...(await load()).values()].filter((p) => p.owner).map((p) => p.id),
};
