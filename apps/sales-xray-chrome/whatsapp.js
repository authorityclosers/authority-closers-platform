/*
 * Sales Xray for Chrome on WhatsApp Web: an "Add to Sales Xray" button in the
 * open chat's header. It reads only the chat's name (and its number when the
 * chat shows one) and asks the extension to open Add lead. Nothing else on the
 * page is read, and nothing is sent anywhere.
 */
(function () {
  if (window.__sxWhatsApp) return;
  window.__sxWhatsApp = true;

  var BUTTON_ID = "sx-add-lead";
  var css =
    "#sx-add-lead{margin:0 8px;padding:6px 12px;border:0;border-radius:16px;" +
    "background:#0d7c74;color:#fff;font:600 13px/1.2 system-ui,sans-serif;cursor:pointer;white-space:nowrap}" +
    "#sx-add-lead:focus-visible{outline:2px solid #4fd1c1;outline-offset:2px}";

  function chatTitle(header) {
    var span = header.querySelector("span[title]");
    var title = span ? span.getAttribute("title") : "";
    return (title || "").trim();
  }

  function leadFrom(title) {
    var digits = title.replace(/[^\d+]/g, "");
    var isNumber =
      digits.replace(/\D/g, "").length >= 8 && !/[A-Za-z]/.test(title);
    return isNumber ? { phone: title } : { name: title };
  }

  function place() {
    var header = document.querySelector("#main header");
    if (!header || header.querySelector("#" + BUTTON_ID)) return;
    var button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "Add to Sales Xray";
    button.title = "Open Sales Xray with this chat's contact filled in";
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var title = chatTitle(header);
      if (!title) return;
      chrome.runtime.sendMessage({ type: "add-lead", lead: leadFrom(title) });
    });
    header.appendChild(button);
  }

  var style = document.createElement("style");
  style.textContent = css;
  document.documentElement.appendChild(style);
  // WhatsApp redraws often; look for the header at most once a frame.
  var queued = false;
  new MutationObserver(function () {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () {
      queued = false;
      place();
    });
  }).observe(document.body, { childList: true, subtree: true });
  place();
})();
