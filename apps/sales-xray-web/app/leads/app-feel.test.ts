import { describe, expect, it } from "vitest";

import { pullDistance, swipeFires, swipeOffset } from "./gestures";
import {
  deskSections,
  fillTemplate,
  firstName,
  linkedLead,
  smsHref,
  whatsappHref,
  type LeadRow,
} from "./leads-client";

const row = (over: Partial<LeadRow>): LeadRow => ({
  lead_id: "00000000-0000-4000-8000-000000000001",
  revision: 1,
  name: "Asha Patil",
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New",
  source: "meta",
  source_label: "Meta lead form",
  owner_person_id: null,
  owner_name: null,
  why: "New lead",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-17T05:00:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...over,
});

describe("ready messages", () => {
  const intro =
    "Hi {first_name}, this is {my_name} from {org}. Thanks for your enquiry{about_interest}. When is a good time to call you?";

  it("fills the lead's first name, my first name, the organisation and the interest", () => {
    expect(
      fillTemplate(intro, {
        leadName: "Asha Patil",
        myName: "Suyash Kulkarni",
        org: "Authority Closers",
        interest: "Solar rooftop",
      }),
    ).toBe(
      "Hi Asha, this is Suyash from Authority Closers. Thanks for your enquiry about Solar rooftop. When is a good time to call you?",
    );
  });

  it("reads well without an interest or a real name", () => {
    expect(
      fillTemplate(intro, {
        leadName: "+91 98765 43210",
        myName: "Suyash",
        org: "AC",
        interest: null,
      }),
    ).toBe(
      "Hi there, this is Suyash from AC. Thanks for your enquiry. When is a good time to call you?",
    );
    expect(firstName("  रवि कुमार ")).toBe("रवि");
    expect(firstName("9876543210")).toBe("there");
  });

  it("opens WhatsApp or Messages with the text ready", () => {
    expect(whatsappHref("+91 98765 43210")).toBe("https://wa.me/919876543210");
    expect(whatsappHref("+919876543210", "Hi & bye")).toBe(
      "https://wa.me/919876543210?text=Hi%20%26%20bye",
    );
    expect(smsHref("+91 98765-43210", "Hi")).toBe("sms:+919876543210?body=Hi");
  });
});

describe("links from a phone alert", () => {
  it("opens one lead by its id, and can ask to call it", () => {
    const id = "6c2d1f0e-1b2a-4c3d-9e8f-0a1b2c3d4e5f";
    expect(linkedLead(`#lead=${id}`)).toEqual({ leadId: id, call: false });
    expect(linkedLead(`#lead=${id}&call=1&n=5`)).toEqual({
      leadId: id,
      call: true,
    });
    expect(linkedLead("#lead=not-an-id")).toBeNull();
    expect(linkedLead("#add=lead&name=Asha")).toBeNull();
  });
});

describe("the due-now list", () => {
  it("puts late calls first, then call now, then later today", () => {
    const sections = deskSections([
      row({ lead_id: "a", overdue: true, why_kind: "due" }),
      row({ lead_id: "b", why_kind: "new" }),
      row({ lead_id: "c", why_kind: "later" }),
      row({ lead_id: "d", why_kind: "retry" }),
    ]);
    expect(sections.map((section) => section.key)).toEqual([
      "overdue",
      "now",
      "later",
    ]);
    expect(sections[1].rows.map((item) => item.lead_id)).toEqual(["b", "d"]);
    expect(
      deskSections([row({ why_kind: "later" })]).map((s) => s.key),
    ).toEqual(["later"]);
  });
});

describe("gestures", () => {
  it("fires a swipe past a quarter of the row (at least 84 px)", () => {
    expect(swipeFires(80, 360)).toBe(false);
    expect(swipeFires(95, 360)).toBe(true);
    expect(swipeFires(-95, 360)).toBe(true);
    expect(swipeFires(120, 600)).toBe(false);
  });

  it("follows the finger, then slows past the trigger", () => {
    expect(swipeOffset(50, 360)).toBe(50);
    expect(swipeOffset(-50, 360)).toBe(-50);
    expect(swipeOffset(400, 360)).toBeLessThan(400);
    expect(swipeOffset(400, 360)).toBeCloseTo(93.6 + 60, 5);
  });

  it("pulls at half speed, never past 96 px", () => {
    expect(pullDistance(-20)).toBe(0);
    expect(pullDistance(100)).toBe(50);
    expect(pullDistance(1000)).toBe(96);
  });
});
