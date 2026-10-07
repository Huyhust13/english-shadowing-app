// Shared helpers for English Hub pages: navigation, theme, dates, API calls, streaks.
(function () {
  "use strict";

  var THEME_KEY = "shadowing-tracker-theme"; // same key the shadowing page always used
  var PAGES = [
    { href: "/", label: "Today" },
    { href: "/vocab", label: "Vocab" },
    { href: "/practice", label: "Practice" },
    { href: "/shadowing", label: "Shadowing" }
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
      '<div class="tabs"></div></div>';
    var tabs = host.querySelector(".tabs");
    PAGES.forEach(function (p) {
      var a = document.createElement("a");
      a.href = p.href;
      a.textContent = p.label;
      if (p.href === here) a.setAttribute("aria-current", "page");
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
  function todayISO() { return isoDate(new Date()); }
  function daysAgoISO(n) {
    var d = new Date();
    d.setDate(d.getDate() - n);
    return isoDate(d);
  }
  function dateLabel(iso, opts) {
    return new Date(iso + "T00:00:00").toLocaleDateString(undefined, opts || { month: "short", day: "numeric" });
  }

  // Consecutive days for which isDone(iso) is true. Today not being done yet doesn't
  // break the streak: until midnight it counts back from yesterday.
  function streak(isDone) {
    var i = isDone(todayISO()) ? 0 : 1;
    var n = 0;
    while (isDone(daysAgoISO(i))) { n++; i++; }
    return n;
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
        if (!res.ok) {
          var err = new Error((data && data.error) || (method + " " + url + " failed: " + res.status));
          err.status = res.status;
          throw err;
        }
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
    streak: streak,
    api: api,
    toast: toast,
    armed: armed
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", renderNav);
  else renderNav();
})();
