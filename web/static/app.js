// Shared helpers for English Hub pages: navigation, theme, dates, API calls.
(function () {
  "use strict";

  var THEME_KEY = "shadowing-tracker-theme"; // same key the shadowing page always used
  var PAGES = [
    { href: "/", label: "Today" },
    { href: "/vocab", label: "Vocab" },
    { href: "/practice", label: "Practice" },
    { href: "/shadowing", label: "Shadowing" },
    { href: "/guide", label: "Guide", wideOnly: true }  // phones: linked from Today and Settings
  ];

  // Apply a stored theme as early as possible to avoid a flash.
  try {
    var stored = localStorage.getItem(THEME_KEY);
    if (stored) document.documentElement.setAttribute("data-theme", stored);
  } catch (e) {}

  function renderNav() {
    var host = document.getElementById("appNav");
    if (!host) return;
    var here = location.pathname.replace(/\/$/, "") || "/";
    if (here === "/today") here = "/";
    host.className = "app-nav";
    host.innerHTML =
      '<div class="nav-inner">' +
      '<a class="brand" href="/"><img src="/icons/icon.svg" alt=""><span>English Hub</span></a>' +
      '<div class="tabs"></div>' +
      '<a class="avatar" href="/settings" title="Settings" aria-label="Settings"></a></div>';
    var tabs = host.querySelector(".tabs");
    var avatar = host.querySelector(".avatar");
    if (here === "/settings" || here === "/admin") avatar.setAttribute("aria-current", "page");
    me().then(function (m) {
      avatar.textContent = (m.displayName || m.username || "?").trim().charAt(0).toUpperCase();
      avatar.title = m.displayName + " · Settings";
    }).catch(function () {});
    PAGES.forEach(function (p) {
      var a = document.createElement("a");
      a.href = p.href;
      a.textContent = p.label;
      if (p.href === here) a.setAttribute("aria-current", "page");
      else if (p.wideOnly) a.className = "wide-only";
      tabs.appendChild(a);
    });
  }

  function effectiveDark() {
    var current = document.documentElement.getAttribute("data-theme");
    var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return current ? current === "dark" : prefersDark;
  }

  function setupTheme(buttonId) {
    var btn = document.getElementById(buttonId || "themeToggle");
    if (!btn) return;
    function label() { btn.textContent = effectiveDark() ? "Light" : "Dark"; }
    label();
    btn.addEventListener("click", function () {
      var next = effectiveDark() ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      label();
    });
  }

  function isoDate(d) {
    var c = new Date(d.getTime());
    c.setMinutes(c.getMinutes() - c.getTimezoneOffset());
    return c.toISOString().slice(0, 10);
  }
  // "Today" follows the server (the timezone in Settings) once /api/summary has
  // answered; until then, the browser's own date.
  var serverToday = null;
  function todayISO() { return serverToday || isoDate(new Date()); }
  function daysAgoISO(n) {
    var d = new Date(todayISO() + "T12:00:00");
    d.setDate(d.getDate() - n);
    return isoDate(d);
  }
  function dateLabel(iso, opts) {
    return new Date(iso + "T00:00:00").toLocaleDateString(undefined, opts || { month: "short", day: "numeric" });
  }

  var mePromise = null;
  function me() {
    if (!mePromise) mePromise = api("GET", "/api/me");
    return mePromise;
  }

  function api(method, url, payload) {
    return fetch(url, {
      method: method,
      headers: payload === undefined ? {} : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload)
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) {}
        if (res.status === 401 && url.indexOf("/api/auth/") !== 0) {
          // Logged out (expired, or the password changed elsewhere): back to the login page.
          location.replace("/login?next=" + encodeURIComponent(location.pathname + location.search + location.hash));
        }
        if (!res.ok) {
          var err = new Error((data && data.error) || (method + " " + url + " failed: " + res.status));
          err.status = res.status;
          throw err;
        }
        if (data && typeof data.today === "string") serverToday = data.today;
        return data;
      });
    });
  }

  var toastTimer = null;
  function toast(msg, ms) {
    var el = document.getElementById("hubToast");
    if (!el) {
      el = document.createElement("div");
      el.id = "hubToast";
      el.className = "toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, ms || 2600);
  }

  // Two-step confirm for destructive buttons: first click arms, second (within 3s) runs.
  function armed(btn, label, run) {
    var original = btn.textContent;
    var timer = null;
    btn.addEventListener("click", function () {
      if (btn.getAttribute("data-armed") !== "1") {
        btn.setAttribute("data-armed", "1");
        btn.textContent = label;
        timer = setTimeout(function () { btn.removeAttribute("data-armed"); btn.textContent = original; }, 3000);
        return;
      }
      clearTimeout(timer);
      btn.removeAttribute("data-armed");
      btn.textContent = original;
      run();
    });
  }

  window.Hub = {
    setupTheme: setupTheme,
    todayISO: todayISO,
    daysAgoISO: daysAgoISO,
    dateLabel: dateLabel,
    api: api,
    me: me,
    toast: toast,
    armed: armed
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", renderNav);
  else renderNav();
})();
