# Sales Xray for Chrome

A Manifest V3 extension that adds leads to Sales Xray from any page (owner order, 16 Oct 2026: "a proper Chrome extension like Pulse has"). Plan: https://claude.ai/artifact/8ZtZ5cgpkjdZnYYq2H3sYD.

## What it does

- **Right-click "Add to Sales Xray"** on selected text: a name, a number, an email, a signature or a chat message. The extension reads the name, phone and email out of it.
- **Right-click "Add this number to Sales Xray"** on a phone link (`tel:`).
- **WhatsApp Web button**, off until the person switches it on in the popup. Chrome then asks once for `web.whatsapp.com`. The button sits in the open chat's header and reads only the chat's name or number.
- **Popup**: paste a contact or message to fill in name and phone, "Open my desk", and the site to use (Sales Xray or Dev).

Each of these opens Sales Xray's Leads page with **Add lead filled in**. The person checks the details and taps Add lead in their normal signed-in page. The details travel after `#` in the link, so browsers never send them to a server.

## What it doesn't do (by design)

- It makes no network requests and keeps no sign-in or token. No device sign-in is needed (ADR 0055 stays off).
- It asks for no site access up front. The only optional site is WhatsApp Web.
- It doesn't record calls yet. Recording Meet and Zoom calls in a tab is the next slice, and it needs an upload route for the extension.

## Files

- `manifest.json`: permissions `contextMenus`, `storage`, `scripting`; optional `https://web.whatsapp.com/*`.
- `worker.js`: the right-click menu, and opening Sales Xray with the lead.
- `lead-link.js`: reads a contact out of text and builds the link. Tested in `test/`.
- `popup.html`, `popup.js`, `popup.css`: the toolbar popup.
- `whatsapp.js`: the WhatsApp Web button, registered only after the person allows that site.
- `icons/`: copied from the Android app's launcher icons.

## Build and install

- Test: `node --test test/*.test.js` (Node 22, no dependencies).
- GitHub: `.github/workflows/sales-xray-chrome.yml` tests and zips the extension on pushes to `main` that touch this folder, or by hand. It keeps the zip as an artifact. On `main` it also replaces the files of the `sales-xray-chrome-latest` test release.
- Install for now: unzip, open `chrome://extensions`, switch on Developer mode, click "Load unpacked" and choose the folder. An unpacked extension can't update itself; the Chrome Web Store comes later.
