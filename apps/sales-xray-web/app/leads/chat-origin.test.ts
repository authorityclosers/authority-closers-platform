import { expect, it } from "vitest";

import { chatFacts, chatOrigin } from "./chat-origin";

it("knows a lead that began as a chat from where it was filed", () => {
  expect(
    chatOrigin({
      source: "webhook",
      source_label: "Messenger · Fictional Homes",
    }),
  ).toBe("messenger");
  expect(
    chatOrigin({ source: "webhook", source_label: "Instagram · @fictional" }),
  ).toBe("instagram");
  expect(
    chatOrigin({
      source: "webhook",
      source_label: "WhatsApp · +91 99990 10001",
    }),
  ).toBe("whatsapp");
  expect(
    chatOrigin({ source: "meta", source_label: "Messenger · X" }),
  ).toBeNull();
  expect(
    chatOrigin({ source: "webhook", source_label: "Website form" }),
  ).toBeNull();
});

it("never shows Meta's raw ids, and says 'came from a comment' plainly", () => {
  expect(
    chatFacts([
      { label: "Name", value: "Asha Rao" },
      { label: "Messenger", value: "39786018197663141" },
      { label: "Came from", value: "comment" },
      { label: "Budget", value: "60 lakh" },
      { label: "Ref", value: "1234567" },
    ]),
  ).toEqual([
    { label: "Came from", value: "A comment on your post" },
    { label: "Budget", value: "60 lakh" },
  ]);
});
