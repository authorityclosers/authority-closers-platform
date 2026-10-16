/**
 * Sales Xray for Chrome: the background worker. It adds "Add to Sales Xray" to
 * the right-click menu and opens Sales Xray with Add lead filled in. It makes
 * no network requests and keeps no sign-in; Sales Xray's own tab does that.
 */

import {
  deskLink,
  fromPage,
  leadLink,
  parseContact,
  phoneFromTel,
} from "./lead-link.js";

const MENU_SELECTION = "sx-add-selection";
const MENU_PHONE_LINK = "sx-add-phone-link";
const WHATSAPP = {
  id: "sx-whatsapp",
  matches: ["https://web.whatsapp.com/*"],
  js: ["whatsapp.js"],
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_SELECTION,
      title: "Add to Sales Xray",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: MENU_PHONE_LINK,
      title: "Add this number to Sales Xray",
      contexts: ["link"],
      targetUrlPatterns: ["tel:*"],
    });
  });
  void syncWhatsApp();
});

chrome.runtime.onStartup.addListener(() => void syncWhatsApp());

async function site() {
  const { site: chosen } = await chrome.storage.sync.get("site");
  return chosen === "dev" ? "dev" : "live";
}

async function openLead(lead) {
  await chrome.tabs.create({ url: leadLink(await site(), lead) });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const note = fromPage(tab?.url ?? "");
  if (info.menuItemId === MENU_SELECTION) {
    const found = parseContact(info.selectionText ?? "");
    const unparsed = !found.name && !found.phone && !found.email;
    void openLead({
      ...found,
      note: unparsed
        ? `${note}: ${String(info.selectionText ?? "").slice(0, 300)}`
        : note,
    });
  } else if (info.menuItemId === MENU_PHONE_LINK) {
    void openLead({ phone: phoneFromTel(info.linkUrl ?? ""), note });
  }
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== chrome.runtime.id || !message) return;
  if (message.type === "add-lead") {
    void openLead({ ...message.lead, note: fromPage(sender.tab?.url ?? "") });
  } else if (message.type === "open-desk") {
    void site().then((chosen) => chrome.tabs.create({ url: deskLink(chosen) }));
  } else if (message.type === "whatsapp-changed") {
    void syncWhatsApp();
  }
});

/** The WhatsApp Web button runs only once the person has allowed that one site. */
async function syncWhatsApp() {
  const allowed = await chrome.permissions.contains({
    origins: WHATSAPP.matches,
  });
  const existing = await chrome.scripting.getRegisteredContentScripts({
    ids: [WHATSAPP.id],
  });
  if (allowed && !existing.length) {
    await chrome.scripting.registerContentScripts([
      { ...WHATSAPP, runAt: "document_idle" },
    ]);
  } else if (!allowed && existing.length) {
    await chrome.scripting.unregisterContentScripts({ ids: [WHATSAPP.id] });
  }
}

chrome.permissions.onAdded.addListener(() => void syncWhatsApp());
chrome.permissions.onRemoved.addListener(() => void syncWhatsApp());
