import { deskLink, leadLink, parseContact } from "./lead-link.js";

const WHATSAPP = { origins: ["https://web.whatsapp.com/*"] };
const field = (id) => document.getElementById(id);

async function site() {
  const { site: chosen } = await chrome.storage.sync.get("site");
  return chosen === "dev" ? "dev" : "live";
}

async function start() {
  field("site").value = await site();
  field("whatsapp").checked = await chrome.permissions.contains(WHATSAPP);
}

field("paste").addEventListener("input", () => {
  const found = parseContact(field("paste").value);
  if (found.name) field("name").value = found.name;
  if (found.phone) field("phone").value = found.phone;
});

field("add").addEventListener("submit", async (event) => {
  event.preventDefault();
  const found = parseContact(field("paste").value);
  const lead = {
    name: field("name").value,
    phone: field("phone").value,
    email: found.email,
  };
  if (!lead.name.trim() && !lead.phone.trim() && !lead.email) {
    field("name").focus();
    return;
  }
  await chrome.tabs.create({ url: leadLink(await site(), lead) });
  window.close();
});

field("desk").addEventListener("click", async () => {
  await chrome.tabs.create({ url: deskLink(await site()) });
  window.close();
});

field("site").addEventListener("change", () => {
  void chrome.storage.sync.set({ site: field("site").value });
});

field("whatsapp").addEventListener("change", async () => {
  const box = field("whatsapp");
  // Chrome asks the person here, from their click; nothing is granted silently.
  const done = box.checked
    ? await chrome.permissions.request(WHATSAPP)
    : await chrome.permissions.remove(WHATSAPP);
  if (!done) box.checked = !box.checked;
  void chrome.runtime.sendMessage({ type: "whatsapp-changed" });
});

void start();
