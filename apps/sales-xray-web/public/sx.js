/*! Sales X-Ray website line (sx.js), v1.
 *
 * Paste once into the site's <head>:
 *   <script src="https://salesxray.authorityclosers.com/sx.js" data-key="sxw_..." async></script>
 *
 * What it does, and nothing else:
 * - Says hello once per page: the page's address, title and how many lead forms it has.
 *   No visitor id, no cookie of its own.
 * - When a visitor sends a lead form (one with a phone or email field), sends its answers
 *   to Sales X-Ray with where the visit came from: UTM tags, ad click ids (gclid, gbraid,
 *   wbraid, fbclid, msclkid, ttclid, li_fat_id) and Meta's own _fbc/_fbp cookies. The
 *   form itself goes on exactly as before.
 * - Never sends passwords, card, OTP or identity-number fields, hidden fields or files.
 *
 * Options on the script tag: data-forms="marked" takes only forms marked data-sx.
 * A form or area marked data-sx-off is never read. For a form that isn't a <form>, call
 * window.sx("lead", { name: "...", phone: "...", email: "..." }) when it is sent.
 * Add ?sx_check=1 to a page's address to see "connected" on the page; ?sx_debug=1 logs.
 */
(function () {
  "use strict";
  var w = window;
  var d = document;
  if (w.__salesXray) return; // the line pasted twice
  var me =
    d.currentScript || d.querySelector('script[data-key][src*="/sx.js"]');
  if (!me) return;
  var KEY = me.getAttribute("data-key") || "";
  var API;
  try {
    API = new URL(me.src, location.href).origin + "/v1/lead-desk/site/";
  } catch {
    return;
  }
  var VERSION = "1";
  var MARKED = me.getAttribute("data-forms") === "marked";
  var DAY = 86400000;
  var KEEP = 90 * DAY;
  var started = Date.now();
  var touches = 0;
  var query = new URLSearchParams(location.search);
  var DEBUG = query.has("sx_debug");
  var CHECK = query.has("sx_check");
  w.__salesXray = { version: VERSION };

  function log() {
    if (DEBUG && w.console) {
      var args = Array.prototype.slice.call(arguments);
      args.unshift("[Sales X-Ray]");
      console.info.apply(console, args);
    }
  }

  function store(name, value) {
    try {
      if (value === undefined)
        return JSON.parse(localStorage.getItem(name) || "null");
      if (value === null) localStorage.removeItem(name);
      else localStorage.setItem(name, JSON.stringify(value));
    } catch {
      /* private mode, blocked storage: nothing kept */
    }
    return null;
  }

  function cookie(name) {
    var match = d.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    if (!match) return null;
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return null; // a malformed cookie: as if it weren't there
    }
  }

  /* ---------- where the visit came from ---------- */

  var TAGS = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
  ];
  var CLICKS = [
    "gclid",
    "gbraid",
    "wbraid",
    "fbclid",
    "msclkid",
    "ttclid",
    "li_fat_id",
  ];

  function page() {
    return (location.origin + location.pathname).slice(0, 500);
  }

  function hostOf(address) {
    try {
      return new URL(address).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  }

  function thisVisit() {
    var touch = {};
    var found = false;
    TAGS.concat(CLICKS).forEach(function (name) {
      var value = query.get(name);
      if (value) {
        touch[name] = value.slice(0, 500);
        found = true;
      }
    });
    var referrer = d.referrer;
    if (referrer && hostOf(referrer) !== hostOf(location.href)) {
      touch.referrer = referrer.split(/[?#]/)[0].slice(0, 500);
      found = true;
    }
    if (!found) return null;
    if (touch.fbclid && !cookie("_fbc")) {
      touch.fbc = "fb.1." + Date.now() + "." + touch.fbclid;
    }
    touch.landing_url = page();
    touch.at = Date.now();
    return touch;
  }

  function attribution() {
    var saved = store("sx_a") || {};
    var now = Date.now();
    if (saved.first && now - saved.first.at > KEEP) saved.first = null;
    if (saved.last && now - saved.last.at > KEEP) saved.last = null;
    var visit = thisVisit();
    if (visit) {
      saved.last = visit;
      if (!saved.first) saved.first = visit;
      store("sx_a", saved);
    }
    return saved;
  }

  var visitTags = attribution();

  function tagsNow() {
    var last = {};
    var source = visitTags.last || {};
    Object.keys(source).forEach(function (name) {
      last[name] = source[name];
    });
    var fbc = cookie("_fbc");
    var fbp = cookie("_fbp");
    if (fbc) last.fbc = fbc;
    if (fbp) last.fbp = fbp;
    var gcl = cookie("_gcl_aw");
    if (gcl && !last.gclid) last.gclid = gcl.split(".").slice(2).join(".");
    return { last: last, first: visitTags.first || null };
  }

  /* ---------- which builder the site is on ---------- */

  function platform() {
    var meta = d.querySelector('meta[name="generator"]');
    var generator = ((meta && meta.content) || "").toLowerCase();
    if (generator.indexOf("elementor") >= 0 || d.querySelector(".elementor"))
      return "elementor";
    if (
      generator.indexOf("wordpress") >= 0 ||
      d.querySelector('[src*="/wp-content/"]')
    )
      return "wordpress";
    if (generator.indexOf("webflow") >= 0 || w.Webflow) return "webflow";
    if (
      generator.indexOf("framer") >= 0 ||
      d.querySelector("[data-framer-hydrate-v2]")
    )
      return "framer";
    if (generator.indexOf("wix") >= 0) return "wix";
    if (generator.indexOf("squarespace") >= 0) return "squarespace";
    if (generator.indexOf("hubspot") >= 0) return "hubspot";
    if (w.Shopify) return "shopify";
    if (d.getElementById("__NEXT_DATA__") || w.next) return "nextjs";
    return "other";
  }

  /* ---------- reading a form ---------- */

  var SECRET =
    /pass|pwd|card|expiry|aadhaa?r|ifsc|account.?(no|number)|captcha|nonce|token|csrf|(^|[^a-z])(cvv|cvc|otp|pan|ssn|iban|upi)([^a-z]|$)/i;

  function words(text) {
    return String(text || "")
      .replace(/\s+/g, " ")
      .replace(/[*:]+\s*$/, "")
      .trim();
  }

  function labelOf(el, index) {
    var text = "";
    if (el.labels && el.labels.length) text = words(el.labels[0].textContent);
    if (!text) text = words(el.getAttribute("aria-label"));
    if (!text && el.getAttribute("aria-labelledby")) {
      var named = d.getElementById(el.getAttribute("aria-labelledby"));
      if (named) text = words(named.textContent);
    }
    if (!text)
      text = words(el.getAttribute("placeholder")).replace(
        /^(enter\s+)?(your\s+)/i,
        "",
      );
    if (!text || text.length > 80) {
      var name = el.name || el.id || "";
      var inner = name.match(/\[([^[\]]+)\]$/);
      text = words((inner ? inner[1] : name).replace(/[_-]+/g, " "));
    }
    if (!text) text = "Field " + (index + 1);
    return text.charAt(0).toUpperCase() + text.slice(1, 80);
  }

  function roleOf(el, type, auto, label) {
    // A tick box is an answer ("Send me updates on WhatsApp"), never a phone or email.
    if (type === "checkbox" || type === "radio") return null;
    if (type === "email" || auto === "email") return "email";
    if (type === "tel" || auto.indexOf("tel") === 0) return "phone";
    if (auto === "name") return "name";
    if (auto === "given-name") return "first_name";
    if (auto === "family-name") return "last_name";
    if (auto === "organization") return "company";
    if (auto === "address-level2") return "city";
    var said = (
      el.name +
      " " +
      el.id +
      " " +
      label +
      " " +
      (el.placeholder || "")
    ).toLowerCase();
    if (/e-?mail/.test(said)) return "email";
    if (
      /phone|mobile|whats ?app|contact (no|number)|\bmob\b|\bcell\b/.test(said)
    )
      return "phone";
    if (/first.?name|\bfname\b|given/.test(said)) return "first_name";
    if (/last.?name|surname|\blname\b/.test(said)) return "last_name";
    if (/company|business|organi[sz]ation|\bfirm\b/.test(said))
      return "company";
    if (/\bcity\b|\btown\b/.test(said)) return "city";
    if (
      el.tagName === "TEXTAREA" ||
      /message|comment|query|enquiry|inquiry|requirement/.test(said)
    )
      return "message";
    if (/name/.test(said)) return "name";
    return null;
  }

  function isSearch(form) {
    if (form.getAttribute("role") === "search") return true;
    if (/search/i.test(form.getAttribute("action") || "")) return true;
    var inputs = form.querySelectorAll(
      "input:not([type=hidden]):not([type=submit])",
    );
    return (
      inputs.length === 1 && /^(q|s|search|query)$/i.test(inputs[0].name || "")
    );
  }

  // Hidden fields a form tool adds for itself, and the ad tags this line already sends.
  var PLUMBING =
    /^(utm_[a-z]+|gclid|gbraid|wbraid|fbclid|fbc|fbp|msclkid|ttclid|li_fat_id|form_id|post_id|page_id|queried_id|referr?er(_title)?|page_(url|title)|url|action|redirect.*|source_url)$|\[(id|author|post_id|token)\]$/i;

  function read(form) {
    var fields = [];
    var byLabel = {};
    var byAnswer = {};
    var contact = false;
    var secret = false;
    var trap = false;
    var elements = form.elements || [];
    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var type = String(el.type || "").toLowerCase();
      var auto = String(el.getAttribute("autocomplete") || "").toLowerCase();
      if (!el.tagName || el.disabled || el.closest("[data-sx-off]")) continue;
      if (/^(submit|button|reset|image|file)$/.test(type)) continue;
      // A step-by-step form often keeps its answers in hidden fields: those count, the
      // tool's own (names starting "_", ids, nonces, tokens) don't.
      var hidden = type === "hidden";
      if (hidden && (!el.name || /^_/.test(el.name) || PLUMBING.test(el.name)))
        continue;
      if (type === "password" || /^cc-|one-time-code|password/.test(auto)) {
        secret = true;
        continue;
      }
      if ((type === "checkbox" || type === "radio") && !el.checked) continue;
      var value = "";
      if (el.tagName === "SELECT") {
        value = Array.prototype.filter
          .call(el.options, function (option) {
            return option.selected && option.value !== "";
          })
          .map(function (option) {
            return words(option.text);
          })
          .join(", ");
      } else {
        value = String(el.value || "").trim();
        // A ticked box with no value of its own says "on": send what it means.
        if (type === "checkbox" && value === "on") value = "Yes";
      }
      if (!value) continue;
      if (hidden && value.length > 100 && !/\s/.test(value)) continue; // a token
      // A field people can't reach (tab index -1, no autofill) that holds text: a bot's.
      if (
        !hidden &&
        el.tabIndex === -1 &&
        auto === "off" &&
        el.tagName === "INPUT"
      ) {
        trap = true;
        continue;
      }
      var label = labelOf(el, i);
      if (SECRET.test(el.name + " " + label)) continue;
      var role = roleOf(el, type, auto, label);
      // The same answer twice (a visible field and its hidden copy): once.
      if (role && byAnswer[role + "|" + value]) continue;
      if (role) byAnswer[role + "|" + value] = true;
      if (role === "phone" || role === "email") contact = true;
      if (
        byLabel[label] !== undefined &&
        (type === "checkbox" || type === "radio")
      ) {
        fields[byLabel[label]].v += ", " + value;
        continue;
      }
      byLabel[label] = fields.length;
      fields.push({ k: label, v: value.slice(0, 1000), r: role });
      if (fields.length >= 40) break;
    }
    if (!contact) {
      // A form with no marked phone or email still counts when an answer is one.
      contact = fields.some(function (field) {
        return /@/.test(field.v) || /^\+?[\d\s().-]{8,20}$/.test(field.v);
      });
    }
    return {
      fields: fields,
      lead: contact && !secret && !isSearch(form),
      trap: trap,
    };
  }

  function wanted(form) {
    if (!form || form.tagName !== "FORM" || form.closest("[data-sx-off]"))
      return false;
    return !MARKED || form.hasAttribute("data-sx");
  }

  function leadForms() {
    var count = 0;
    var forms = d.forms || [];
    for (var i = 0; i < forms.length; i++) {
      if (!wanted(forms[i]) || isSearch(forms[i])) continue;
      var inputs = forms[i].querySelectorAll("input");
      for (var j = 0; j < inputs.length; j++) {
        if (
          /^(email|tel)$/i.test(inputs[j].type) ||
          /phone|mail|mobile|whats/i.test(inputs[j].name || "")
        ) {
          count++;
          break;
        }
      }
    }
    return count;
  }

  /* ---------- sending ---------- */

  function post(path, body, done) {
    var text = JSON.stringify(body);
    if (w.fetch) {
      w.fetch(API + path, {
        method: "POST",
        body: text,
        keepalive: text.length < 60000,
        mode: "cors",
        credentials: "omit",
        headers: { "Content-Type": "text/plain" },
      })
        .then(function (response) {
          return response.json().then(
            function (answer) {
              if (done) done(response.status, answer);
            },
            function () {
              if (done) done(response.status, null);
            },
          );
        })
        .catch(function () {
          if (done) done(0, null);
        });
      return;
    }
    if (navigator.sendBeacon) {
      navigator.sendBeacon(
        API + path,
        new Blob([text], { type: "text/plain" }),
      );
      if (done) done(202, null);
    }
  }

  // A lead waits on this browser until Sales X-Ray has it: a send cut off by the page
  // closing, or by a moment when Sales X-Ray was being updated, goes again on the next page.
  function queue(change) {
    var waiting = (store("sx_q") || []).filter(function (item) {
      return Date.now() - item.at < DAY;
    });
    waiting = change(waiting).slice(-5);
    store("sx_q", waiting.length ? waiting : null);
  }

  function send(item) {
    post("lead", item.body, function (status) {
      log("lead", status, item.body);
      if (
        (status >= 200 && status < 300) ||
        (status >= 400 && status < 500 && status !== 408 && status !== 429)
      ) {
        queue(function (waiting) {
          return waiting.filter(function (other) {
            return other.id !== item.id;
          });
        });
      }
    });
  }

  var lastSent = { at: 0, text: "" };

  function sendLead(fields, formName, trap) {
    var text = JSON.stringify(fields);
    if (text === lastSent.text && Date.now() - lastSent.at < 10000) return; // one press, two hooks
    lastSent = { at: Date.now(), text: text };
    var now = Date.now();
    var item = {
      id: Math.random().toString(36).slice(2) + now.toString(36),
      at: now,
      body: {
        at: now,
        k: KEY,
        v: VERSION,
        u: page(),
        t: d.title.slice(0, 200),
        form: formName,
        fields: fields,
        a: tagsNow(),
        it: touches,
        ms: Date.now() - started,
        wd: navigator.webdriver === true,
        hp: trap === true,
        ua: navigator.userAgent.slice(0, 300),
        p: platform(),
      },
    };
    queue(function (waiting) {
      return waiting.concat([item]);
    });
    send(item);
  }

  function capture(form) {
    if (!wanted(form)) return;
    if (!form.noValidate && form.checkValidity && !form.checkValidity()) return;
    var found = read(form);
    log("form", found);
    if (!found.lead || !found.fields.length) return;
    var name = words(
      form.getAttribute("name") ||
        form.getAttribute("aria-label") ||
        form.getAttribute("data-name") ||
        form.id ||
        "",
    ).slice(0, 120);
    sendLead(found.fields, name || null, found.trap);
  }

  d.addEventListener(
    "submit",
    function (event) {
      try {
        capture(event.target);
      } catch (e) {
        log("submit", e);
      }
    },
    true,
  );
  // form.submit() from a site's own script fires no submit event.
  try {
    var submit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
      try {
        capture(this);
      } catch (e) {
        log("submit()", e);
      }
      return submit.apply(this, arguments);
    };
  } catch {
    /* a locked prototype: the submit event still works */
  }

  ["keydown", "pointerdown", "touchstart"].forEach(function (name) {
    d.addEventListener(
      name,
      function () {
        touches++;
      },
      { capture: true, passive: true },
    );
  });

  /* ---------- hello, and "connected" on ?sx_check ---------- */

  function badge(text, good) {
    var box = d.createElement("div");
    box.setAttribute("role", "status");
    box.textContent = text;
    box.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:320px;" +
      "padding:12px 16px;border-radius:12px;font:600 14px/1.4 system-ui,sans-serif;" +
      "box-shadow:0 8px 24px rgba(0,0,0,.18);color:#fff;background:" +
      (good ? "#0f766e" : "#b91c1c");
    d.body.appendChild(box);
    setTimeout(function () {
      box.remove();
    }, 10000);
  }

  var helloPath = null;

  function hello() {
    try {
      sayHello();
    } catch (e) {
      log("hello", e);
    }
  }

  function sayHello() {
    if (helloPath === location.pathname) return;
    helloPath = location.pathname;
    var forms = leadForms();
    post(
      "hello",
      {
        k: KEY,
        v: VERSION,
        u: page(),
        t: d.title.slice(0, 200),
        f: forms,
        p: platform(),
      },
      function (status, answer) {
        log("hello", status, answer);
        if (!CHECK) return;
        var site = answer && answer.site;
        if (status === 200 && site === "active")
          badge(
            "Sales X-Ray is connected. Lead forms on this page: " + forms + ".",
            true,
          );
        else if (site === "paused")
          badge("This site is paused in Sales X-Ray.", false);
        else if (site === "removed")
          badge(
            "This site was removed in Sales X-Ray. Add it back there.",
            false,
          );
        else
          badge(
            (answer && answer.detail) ||
              "Sales X-Ray can't be reached from this page.",
            false,
          );
      },
    );
  }

  function soon(fn, ms) {
    var timer = null;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, ms);
    };
  }

  var helloSoon = soon(hello, 500);
  ["pushState", "replaceState"].forEach(function (name) {
    var original = history[name];
    history[name] = function () {
      var result = original.apply(this, arguments);
      helloSoon();
      return result;
    };
  });
  w.addEventListener("popstate", helloSoon);

  function ready() {
    setTimeout(hello, CHECK ? 0 : 800);
    // Kept leads go again (not one still on its way); a day on, they are dropped.
    queue(function (waiting) {
      return waiting;
    });
    (store("sx_q") || []).forEach(function (item) {
      var age = Date.now() - item.at;
      if (age > 20000 && age < DAY) send(item);
    });
  }
  if (d.readyState === "complete") ready();
  else w.addEventListener("load", ready);

  // For forms that aren't <form>s: sx("lead", { name, phone, email, ... }).
  function lead(data) {
    if (!data || typeof data !== "object") return;
    var fields = Object.keys(data)
      .slice(0, 40)
      .map(function (name) {
        var role = roleOf(
          { name: name, id: "", tagName: "INPUT" },
          "",
          "",
          name,
        );
        return {
          k: name.charAt(0).toUpperCase() + name.slice(1, 80),
          v: String(data[name]).slice(0, 1000),
          r: role,
        };
      })
      .filter(function (field) {
        return field.v && !SECRET.test(field.k);
      });
    if (fields.length) sendLead(fields, null);
  }

  // For forms that aren't <form>s. A site's own window.sx is never replaced; the same call
  // is window.__salesXray.lead({...}) then.
  w.__salesXray.lead = function (data) {
    try {
      lead(data);
    } catch (e) {
      log("lead", e);
    }
  };
  if (w.sx === undefined) {
    w.sx = function (command, data) {
      if (command === "lead") w.__salesXray.lead(data);
    };
  }
})();
