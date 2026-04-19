// Service Worker for Pool Séries 2026
// Handles background notifications when draft turn changes

const CACHE_NAME = 'pool-series-v21';
const FIREBASE_DB_URL = 'https://pool-series-2026-default-rtdb.firebaseio.com';

// Install: cache essential files
self.addEventListener('install', event => {
  console.log('[SW] Install');
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  console.log('[SW] Activate');
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Listen for messages from the main page
self.addEventListener('message', event => {
  const data = event.data;
  if (data.type === 'SHOW_NOTIFICATION') {
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: 'icon-192.png',
      badge: 'icon-192.png',
      tag: data.tag || 'draft-turn',
      renotify: true,
      vibrate: [200, 100, 200],
      data: { url: data.url || './' }
    });
  }
  if (data.type === 'CHECK_TURN') {
    // Store the current user info for background checking
    self._poolerName = data.poolerName;
    self._lastNotifiedKey = data.lastNotifiedKey || '';
  }
});

// Handle notification click — open or focus the app
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = event.notification.data?.url || './';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // Focus existing tab if open
      for (const client of windowClients) {
        if (client.url.includes('pool-series-2026') && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open new tab
      return clients.openWindow(url);
    })
  );
});
