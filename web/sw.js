// English Hub service worker: shows reminder notifications (Web Push) and opens the
// app when one is tapped. It deliberately doesn't cache pages; the app needs the server.
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "English Hub", {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: "daily-reminder",          // a newer reminder replaces an older one
    renotify: true,
    data: { url: data.url || "/" }
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
  if (url.origin !== self.location.origin) url = new URL("/", self.location.origin);
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (wins) {
    for (var i = 0; i < wins.length; i++) {
      if (new URL(wins[i].url).origin === url.origin && "focus" in wins[i]) {
        wins[i].navigate(url.href);
        return wins[i].focus();
      }
    }
    return self.clients.openWindow(url.href);
  }));
});
