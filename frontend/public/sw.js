// Service Worker: nur für Push-Benachrichtigungen und „Zum Startbildschirm“.
// Bewusst kein Offline-Cache – Finanzdaten sollen nicht im Browser-Cache liegen.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let daten = {};
  try {
    daten = event.data ? event.data.json() : {};
  } catch {
    daten = { titel: 'BankPocket', text: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.registration.showNotification(daten.titel || 'BankPocket', {
      body: daten.text || '',
      icon: '/icon-192.png',
      badge: '/badge-72.png',
      tag: daten.tag,
      data: { link: daten.link || '#/hinweise' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const link = event.notification.data?.link || '#/';
  event.waitUntil(
    (async () => {
      const fenster = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const f of fenster) {
        if ('focus' in f) {
          await f.focus();
          f.postMessage({ navigate: link });
          return;
        }
      }
      await self.clients.openWindow('/' + link);
    })(),
  );
});

self.addEventListener('fetch', () => {});
