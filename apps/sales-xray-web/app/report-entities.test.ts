import { expect, it } from "vitest";

import { brandNamed, mentions } from "./report-entities";

const found = (text: string) =>
  mentions(text).map((part) =>
    part.brand ? [part.kind, part.text, part.brand.key] : [part.kind, part.text],
  );

it("finds what the report mentions, with the words it used", () => {
  expect(
    found(
      "You pivoted to pitching the 3-day Leadership Funnel Program and agreed to share video material over WhatsApp and arrange a call the next day alongside a senior manager.",
    ),
  ).toEqual([
    ["program", "3-day Leadership Funnel Program"],
    ["video", "video"],
    ["brand", "WhatsApp", "whatsapp"],
    ["date", "next day"],
    ["person", "senior manager"],
  ]);
  expect(
    found("It uncovered 15 to 20 lakh of unpaid receivables and the syllabus and workbook."),
  ).toEqual([
    ["money", "15 to 20 lakh"],
    ["money", "unpaid receivables"],
    ["document", "syllabus"],
    ["document", "workbook"],
  ]);
});

it("spots brands in Hindi and Marathi script and in any letter case", () => {
  expect(found("मैं आपको व्हाट्सएप पे भेज देता हूं, यूट्यूब पे भी है")).toEqual([
    ["brand", "व्हाट्सएप", "whatsapp"],
    ["brand", "यूट्यूब", "youtube"],
  ]);
  expect(found("join our discord and pay by phone pe or gpay")).toEqual([
    ["brand", "discord", "discord"],
    ["brand", "phone pe", "phonepe"],
    ["brand", "gpay", "googlepay"],
  ]);
  expect(found("Send the Google Meet link, not Google Drive")).toEqual([
    ["brand", "Google Meet", "googlemeet"],
    ["brand", "Google Drive", "googledrive"],
  ]);
});

it("does not mistake ordinary words for brands", () => {
  expect(found("zoom in on the numbers and tally them up")).toEqual([]);
  expect(found("We can do a Zoom call and keep accounts in Tally")).toEqual([
    ["brand", "Zoom call", "zoom"],
    ["brand", "Tally", "tally"],
  ]);
  // "naukri" is Hindi for a job, not the job portal.
  expect(found("उनकी naukri अच्छी है")).toEqual([]);
  // A brand inside a longer word is not a mention.
  expect(found("instant results")).toEqual([]);
});

it("finds money, places, time and team size in Hindi too", () => {
  expect(
    found("अहमदाबाद में 5 करोड़ का टर्नओवर है, 15 लोग काम करते हैं, 90 मिनट की रिकॉर्डिंग"),
  ).toEqual([
    ["place", "अहमदाबाद"],
    ["money", "5 करोड़"],
    ["money", "टर्नओवर"],
    ["team", "15 लोग"],
    ["time", "90 मिनट"],
    ["video", "रिकॉर्डिंग"],
  ]);
  expect(found("Their Pune office grew 20% on Monday")).toEqual([
    ["place", "Pune"],
    ["percent", "20%"],
    ["date", "Monday"],
  ]);
});

it("leaves plain text alone", () => {
  expect(found("They asked about the program and the call went well.")).toEqual([]);
  expect(mentions("No mentions here.")).toEqual([]);
});

it("finds a curated brand by any of its names", () => {
  expect(brandNamed("Whats App")?.key).toBe("whatsapp");
  expect(brandNamed("फेसबुक")?.key).toBe("facebook");
  expect(brandNamed("Nothing Inc")).toBeNull();
});

it("keeps Marathi case endings joined to a brand", () => {
  expect(found("मी तुम्हाला उद्या व्हॉट्सॲपवर पाठवतो")).toEqual([
    ["date", "उद्या"],
    ["brand", "व्हॉट्सॲपवर", "whatsapp"],
  ]);
});
