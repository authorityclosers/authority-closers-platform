/*
 * Sales Xray for Android: "Calls on this phone".
 * Injected by the app into Sales Xray pages only. Lists the call recordings the
 * phone saved by itself and hands the chosen one to the normal New analysis
 * upload, so consent, plan and approval stay exactly as on the web.
 * Nothing leaves the phone until the person taps Analyse.
 */
(function () {
  if (window.__sxPhone || typeof window.SXPhone === "undefined") return;

  var pending = {};
  var counter = 0;
  window.SXPhone.onmessage = function (event) {
    var message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    var waiter = pending[message.id];
    if (!waiter) return;
    delete pending[message.id];
    if (message.ok) waiter.resolve(message.result);
    else waiter.reject(new Error(message.error || "phone_error"));
  };
  function call(method, args) {
    return new Promise(function (resolve, reject) {
      var id = "m" + ++counter;
      pending[id] = { resolve: resolve, reject: reject };
      window.SXPhone.postMessage(JSON.stringify({ id: id, method: method, args: args || {} }));
    });
  }

  var SENT_KEY = "sx.phone.sent";
  var SEEN_KEY = "sx.phone.seen";
  var PICK_KEY = "sx.phone.pick";
  function load(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key) || "null") || fallback;
    } catch (error) {
      return fallback;
    }
  }
  function save(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {}
  }

  var css =
    ".sxp-fab{position:fixed;right:16px;bottom:calc(88px + env(safe-area-inset-bottom,0px));z-index:2147483000;display:flex;align-items:center;gap:8px;" +
    "height:48px;padding:0 16px 0 14px;border:0;border-radius:24px;background:var(--lx-teal,#14b8a6);color:var(--lx-on-teal,#04221d);" +
    "font:600 14px/1 var(--lx-font-ui,system-ui,sans-serif);box-shadow:0 8px 24px rgba(0,0,0,.28)}" +
    ".sxp-fab[hidden]{display:none}.sxp-fab svg{width:20px;height:20px}" +
    ".sxp-badge{min-width:20px;height:20px;padding:0 6px;border-radius:10px;background:#ef4444;color:#fff;font-size:12px;line-height:20px;text-align:center}" +
    ".sxp-scrim{position:fixed;inset:0;z-index:2147483001;background:rgba(3,8,18,.55);animation:sxpfade .18s ease-out}" +
    ".sxp-sheet{position:fixed;left:0;right:0;bottom:0;z-index:2147483002;max-height:82vh;display:flex;flex-direction:column;" +
    "border-radius:20px 20px 0 0;background:var(--lx-surface,#0f1b2d);color:var(--lx-ink,#e6edf6);font:14px/1.45 var(--lx-font-ui,system-ui,sans-serif);" +
    "padding-bottom:env(safe-area-inset-bottom,0px);box-shadow:0 -12px 40px rgba(0,0,0,.35);animation:sxpup .22s ease-out}" +
    ".sxp-head{padding:16px 18px 10px;border-bottom:1px solid var(--lx-line,rgba(148,163,184,.18))}" +
    ".sxp-grab{width:40px;height:4px;margin:0 auto 12px;border-radius:2px;background:var(--lx-line-strong,rgba(148,163,184,.4))}" +
    ".sxp-title{display:flex;align-items:center;justify-content:space-between;gap:12px}" +
    ".sxp-title h2{margin:0;font-size:18px;font-weight:700}" +
    ".sxp-close{border:0;background:transparent;color:inherit;font-size:22px;line-height:1;padding:4px 8px}" +
    ".sxp-sub{margin:6px 0 0;color:var(--lx-muted,#94a3b8);font-size:13px}" +
    ".sxp-watch{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;padding:10px 12px;border-radius:12px;" +
    "background:var(--lx-surface-2,rgba(148,163,184,.08))}" +
    ".sxp-watch b{display:block;font-size:13px}.sxp-watch small{color:var(--lx-muted,#94a3b8)}" +
    ".sxp-switch{position:relative;width:44px;height:26px;flex:none;border:0;border-radius:13px;background:var(--lx-line-strong,#475569)}" +
    ".sxp-switch[aria-checked=true]{background:var(--lx-teal,#14b8a6)}" +
    ".sxp-switch:after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .18s}" +
    ".sxp-switch[aria-checked=true]:after{transform:translateX(18px)}" +
    ".sxp-list{overflow:auto;padding:6px 10px 14px}" +
    ".sxp-row{display:flex;align-items:center;gap:12px;padding:12px 8px;border-bottom:1px solid var(--lx-line,rgba(148,163,184,.14))}" +
    ".sxp-icon{flex:none;width:38px;height:38px;display:grid;place-items:center;border-radius:12px;background:var(--lx-teal-tint,rgba(20,184,166,.14));color:var(--lx-teal,#2dd4bf)}" +
    ".sxp-main{flex:1;min-width:0}.sxp-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    ".sxp-meta{color:var(--lx-muted,#94a3b8);font-size:12px}" +
    ".sxp-tag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:600;background:rgba(20,184,166,.16);color:var(--lx-teal,#2dd4bf)}" +
    ".sxp-tag.sxp-new{background:rgba(239,68,68,.16);color:#f87171}" +
    ".sxp-go{flex:none;border:0;border-radius:10px;padding:9px 12px;background:var(--lx-teal,#14b8a6);color:var(--lx-on-teal,#04221d);font:600 13px/1 inherit}" +
    ".sxp-go[disabled]{opacity:.45}" +
    ".sxp-empty{padding:22px 14px;text-align:center;color:var(--lx-muted,#94a3b8)}" +
    ".sxp-empty b{display:block;color:var(--lx-ink,#e6edf6);font-size:15px;margin-bottom:6px}" +
    ".sxp-action{margin-top:14px;border:0;border-radius:12px;padding:11px 16px;background:var(--lx-teal,#14b8a6);color:var(--lx-on-teal,#04221d);font:600 14px/1 inherit}" +
    ".sxp-toast{position:fixed;left:16px;right:16px;bottom:calc(150px + env(safe-area-inset-bottom,0px));z-index:2147483003;padding:12px 14px;border-radius:14px;" +
    "background:var(--lx-surface,#0f1b2d);color:var(--lx-ink,#e6edf6);border:1px solid var(--lx-line-strong,rgba(148,163,184,.35));box-shadow:0 10px 30px rgba(0,0,0,.35);font:14px/1.4 var(--lx-font-ui,system-ui,sans-serif)}" +
    "@keyframes sxpup{from{transform:translateY(24px);opacity:0}to{transform:none;opacity:1}}@keyframes sxpfade{from{opacity:0}to{opacity:1}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var PHONE =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg>';
  var WAVE =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
    '<path d="M2 10v4M6 6v12M10 3v18M14 8v8M18 5v14M22 10v4"/></svg>';

  function escape(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function clock(ms) {
    if (!ms) return "";
    var s = Math.round(ms / 1000);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var r = String(s % 60).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + r : m + ":" + r;
  }
  function when(ms) {
    var d = new Date(ms);
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + " · " + d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  }
  function megabytes(bytes) {
    return bytes ? (bytes / 1048576).toFixed(bytes > 10485760 ? 0 : 1) + " MB" : "";
  }

  var toastTimer;
  function toast(text) {
    var old = document.querySelector(".sxp-toast");
    if (old) old.remove();
    var node = document.createElement("div");
    node.className = "sxp-toast";
    node.setAttribute("role", "status");
    node.textContent = text;
    document.body.appendChild(node);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      node.remove();
    }, 5200);
  }

  var hiddenPaths = /^\/(login|register|forgot-password|reset-password|verify|auth)(\/|$)/;
  var fab;
  var items = [];
  var state = null;

  function newCount() {
    var seen = load(SEEN_KEY, 0);
    var sent = load(SENT_KEY, {});
    return items.filter(function (item) {
      return item.addedMs > seen && !sent[item.source];
    }).length;
  }

  function renderFab() {
    var show = !hiddenPaths.test(location.pathname);
    if (!fab) {
      fab = document.createElement("button");
      fab.type = "button";
      fab.className = "sxp-fab";
      fab.setAttribute("aria-label", "Calls on this phone");
      fab.addEventListener("click", openSheet);
      document.body.appendChild(fab);
    }
    var count = newCount();
    fab.innerHTML = PHONE + "<span>Calls</span>" + (count ? '<span class="sxp-badge">' + count + "</span>" : "");
    fab.hidden = !show || Boolean(document.querySelector(".sxp-sheet"));
  }

  function refresh() {
    return call("status")
      .then(function (status) {
        state = status;
        if (!status.audio && !status.allFiles) {
          items = [];
          return;
        }
        return call("list", { limit: 200 }).then(function (result) {
          items = result.items || [];
        });
      })
      .catch(function () {})
      .then(renderFab);
  }

  function closeSheet() {
    var sheet = document.querySelector(".sxp-sheet");
    var scrim = document.querySelector(".sxp-scrim");
    if (sheet) sheet.remove();
    if (scrim) scrim.remove();
    renderFab();
  }

  function openSheet() {
    closeSheet();
    var scrim = document.createElement("div");
    scrim.className = "sxp-scrim";
    scrim.addEventListener("click", closeSheet);
    var sheet = document.createElement("section");
    sheet.className = "sxp-sheet";
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-label", "Calls on this phone");
    document.body.appendChild(scrim);
    document.body.appendChild(sheet);
    renderFab();
    drawSheet(sheet);
    refresh().then(function () {
      if (document.body.contains(sheet)) drawSheet(sheet);
      var newest = items.reduce(function (max, item) {
        return Math.max(max, item.addedMs);
      }, load(SEEN_KEY, 0));
      save(SEEN_KEY, newest);
    });
  }

  function drawSheet(sheet) {
    var sent = load(SENT_KEY, {});
    var seen = load(SEEN_KEY, 0);
    var watching = state && state.watching;
    var head =
      '<header class="sxp-head"><div class="sxp-grab"></div><div class="sxp-title"><h2>Calls on this phone</h2>' +
      '<button type="button" class="sxp-close" aria-label="Close">×</button></div>' +
      '<p class="sxp-sub">Your phone records calls. Sales Xray finds them here. Nothing leaves this phone until you tap Analyse.</p>' +
      (state && (state.audio || state.allFiles)
        ? '<div class="sxp-watch"><span><b>Tell me about new recordings</b><small>Checks every 15 minutes, even when Sales Xray is closed</small></span>' +
          '<button type="button" class="sxp-switch" role="switch" aria-label="Tell me about new recordings" aria-checked="' + Boolean(watching) + '"></button></div>'
        : "") +
      "</header>";
    var body;
    if (!state) {
      body = '<div class="sxp-empty">Looking for call recordings…</div>';
    } else if (!state.audio && !state.allFiles) {
      body =
        '<div class="sxp-empty"><b>Let Sales Xray see your call recordings</b>' +
        "Allow access to audio files so Sales Xray can list the calls your phone recorded. Only the call you pick is uploaded." +
        '<br><button type="button" class="sxp-action" data-act="allow">Allow access</button></div>';
    } else if (!items.length) {
      body =
        '<div class="sxp-empty"><b>No call recordings found</b>' +
        "Turn on automatic call recording in your phone's dialer settings. If it is already on, your phone may hide the folder." +
        (state.allFilesSupported && !state.allFiles
          ? '<br><button type="button" class="sxp-action" data-act="allfiles">Let Sales Xray look in the call folder</button>'
          : "") +
        "</div>";
    } else {
      body =
        '<div class="sxp-list">' +
        items
          .map(function (item, index) {
            var tag = sent[item.source]
              ? '<span class="sxp-tag">Sent</span>'
              : item.addedMs > seen
                ? '<span class="sxp-tag sxp-new">New</span>'
                : "";
            var meta = [when(item.addedMs), clock(item.durationMs), megabytes(item.size)].filter(Boolean).join(" · ");
            var note = item.supported ? "" : ' · <span>.' + escape(item.ext) + " not supported yet</span>";
            return (
              '<div class="sxp-row"><span class="sxp-icon">' + WAVE + '</span><span class="sxp-main"><span class="sxp-name">' +
              escape(item.title) + tag + '</span><span class="sxp-meta">' + escape(meta) + note + "</span></span>" +
              '<button type="button" class="sxp-go" data-index="' + index + '"' + (item.supported ? "" : " disabled") + ">Analyse</button></div>"
            );
          })
          .join("") +
        "</div>";
    }
    sheet.innerHTML = head + body;
    sheet.querySelector(".sxp-close").addEventListener("click", closeSheet);
    var toggle = sheet.querySelector(".sxp-switch");
    if (toggle)
      toggle.addEventListener("click", function () {
        call("setWatch", { on: !(state && state.watching) }).then(function (status) {
          state = status;
          drawSheet(sheet);
          toast(status.watching ? (status.notifications ? "Sales Xray will tell you about new call recordings." : "Turn on notifications for Sales Xray to get alerts.") : "New-recording alerts are off.");
        });
      });
    var allow = sheet.querySelector('[data-act="allow"]');
    if (allow)
      allow.addEventListener("click", function () {
        call("requestAccess").then(function () {
          refresh().then(function () {
            drawSheet(sheet);
          });
        });
      });
    var allFiles = sheet.querySelector('[data-act="allfiles"]');
    if (allFiles)
      allFiles.addEventListener("click", function () {
        call("openAllFiles");
        toast("Turn on “Allow access to manage all files” for Sales Xray, then come back.");
      });
    Array.prototype.forEach.call(sheet.querySelectorAll(".sxp-go"), function (button) {
      button.addEventListener("click", function () {
        analyse(items[Number(button.getAttribute("data-index"))]);
      });
    });
  }

  function waitFor(selector, ms) {
    return new Promise(function (resolve, reject) {
      var started = Date.now();
      (function look() {
        var node = document.querySelector(selector);
        if (node) return resolve(node);
        if (Date.now() - started > ms) return reject(new Error("upload_area_missing"));
        setTimeout(look, 250);
      })();
    });
  }

  function readAll(item, progress) {
    var chunks = [];
    var offset = 0;
    function next() {
      return call("read", { source: item.source, offset: offset }).then(function (result) {
        var binary = atob(result.data);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        chunks.push(bytes);
        offset += bytes.length;
        progress(item.size ? Math.min(99, Math.round((offset / item.size) * 100)) : 0);
        return result.eof || bytes.length === 0 ? chunks : next();
      });
    }
    return next();
  }

  function analyse(item) {
    if (!item || !item.supported) return;
    if (location.pathname !== "/analysis/new") {
      save(PICK_KEY, item.source);
      location.assign("/analysis/new");
      return;
    }
    closeSheet();
    toast("Preparing " + item.title + "…");
    waitFor('[role="group"][aria-label="Add sales call audio files"]', 15000)
      .then(function (area) {
        return readAll(item, function (percent) {
          var node = document.querySelector(".sxp-toast");
          if (node) node.textContent = "Preparing " + item.title + "… " + percent + "%";
        }).then(function (chunks) {
          var file = new File(chunks, item.name, { type: item.mime, lastModified: item.addedMs });
          var transfer = new DataTransfer();
          transfer.items.add(file);
          area.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
          var sent = load(SENT_KEY, {});
          sent[item.source] = Date.now();
          save(SENT_KEY, sent);
          toast("Recording added. Check the details and start the analysis.");
          renderFab();
        });
      })
      .catch(function () {
        toast("That recording could not be added. Open New analysis and try again.");
      });
  }

  function continuePick() {
    var source = load(PICK_KEY, null);
    var launch = call("consumeLaunch").then(function (result) {
      return result && result.source;
    });
    return launch.then(function (fromNotice) {
      var wanted = fromNotice || source;
      if (!wanted) return;
      save(PICK_KEY, null);
      return refresh().then(function () {
        var item = items.filter(function (candidate) {
          return candidate.source === wanted;
        })[0];
        if (!item) return openSheet();
        analyse(item);
      });
    });
  }

  window.__sxPhone = {
    onNative: function (event) {
      if (event === "launch") continuePick();
      else refresh();
    },
  };

  // The web app routes on the client; keep the button's visibility in step.
  ["pushState", "replaceState"].forEach(function (name) {
    var original = history[name];
    history[name] = function () {
      var result = original.apply(this, arguments);
      setTimeout(renderFab, 0);
      return result;
    };
  });
  window.addEventListener("popstate", renderFab);

  refresh().then(continuePick);
})();
