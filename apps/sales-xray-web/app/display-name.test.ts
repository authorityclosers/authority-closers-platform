import { expect, it } from "vitest";

import {
  displayName,
  displayNameOf,
  shortName,
  withDisplayNames,
} from "./display-name";

// Owner, 22 Oct 2026: "Swamini Deshpande", not "swamini deshpande".
it("shows names typed in one case with capitals", () => {
  expect(displayName("swamini deshpande")).toBe("Swamini Deshpande");
  expect(displayName("RAHUL VERMA")).toBe("Rahul Verma");
  expect(displayName("  asha   fictional ")).toBe("Asha Fictional");
  expect(displayName("anne-marie d'souza")).toBe("Anne-Marie D'Souza");
  expect(displayName("r.k. sharma")).toBe("R.K. Sharma");
  expect(displayName("mr. ravi")).toBe("Mr. Ravi");
});

it("keeps names typed in mixed case, emails, numbers and scripts without case", () => {
  expect(displayName("McDonald")).toBe("McDonald");
  expect(displayName("Priya de Souza")).toBe("Priya de Souza");
  expect(displayName("asha@example.test")).toBe("asha@example.test");
  expect(displayName("+91 98765 43210")).toBe("+91 98765 43210");
  expect(displayName("स्वामिनी देशपांडे")).toBe("स्वामिनी देशपांडे");
  expect(displayName("")).toBe("");
  expect(displayNameOf(null)).toBeNull();
});

it("shows the listed keys with capitals at any depth and leaves the rest", () => {
  const answer = {
    me: { name: "priya fictional", role: "owner" },
    queue: [
      {
        name: "ravi fictional",
        owner_name: "ASHA FICTIONAL",
        stage_label: "follow up",
        source_label: "website form",
      },
    ],
    count: 3,
  };
  expect(withDisplayNames(answer, new Set(["name", "owner_name"]))).toEqual({
    me: { name: "Priya Fictional", role: "owner" },
    queue: [
      {
        name: "Ravi Fictional",
        owner_name: "Asha Fictional",
        stage_label: "follow up",
        source_label: "website form",
      },
    ],
    count: 3,
  });
  // The answer itself is untouched.
  expect(answer.me.name).toBe("priya fictional");
});

// v1.94: a tag's name is the team's own word, on its row and in the list.
it("leaves a tag's name as typed", () => {
  const answer = {
    name: "ravi fictional",
    tags: [{ tag_id: "t1", name: "VIP", colour: "rose" }],
  };
  expect(withDisplayNames(answer, new Set(["name"]))).toEqual({
    name: "Ravi Fictional",
    tags: [{ tag_id: "t1", name: "VIP", colour: "rose" }],
  });
  expect(
    withDisplayNames({ tag_id: "t2", name: "hot" }, new Set(["name"])),
  ).toEqual({ tag_id: "t2", name: "hot" });
});

// Polish pass, 24 Oct 2026: a short label instead of a name cut mid-word.
it("shortens a name to the first name and last initial", () => {
  expect(shortName("swamini fictional")).toBe("Swamini F.");
  expect(shortName("Anne-Marie de Souza")).toBe("Anne-Marie S.");
  expect(shortName("Ravi")).toBe("Ravi");
  expect(shortName("asha@example.com")).toBe("asha@example.com");
});
