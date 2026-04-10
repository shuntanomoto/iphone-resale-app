/* ─── iPhone転売利益計算 Service Worker ─── */
const CACHE_NAME = 'iphone-resale-v1';
const PRECACHE   = ['/'];

/* インストール: メインページをキャッシュ */
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE))
  );
  self.skipWaiting();
});

/* アクティベート: 古いキャッシュを削除 */
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

/* フェッチ戦略
 *  /api/* → ネットワーク優先（常に最新価格を取得）
 *  その他  → キャッシュ優先、失敗時はネットワーク
 */
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  if (url.pathname.startsWith('/api/')) {
    /* API: network only */
    e.respondWith(fetch(e.request));
    return;
  }

  /* 静的リソース: cache-first */
  e.respondWith(
    caches.match(e.request).then(cached => {
      const networkFetch = fetch(e.request).then(res => {
        if (res && res.status === 200) {
          caches.open(CACHE_NAME).then(c => c.put(e.request, res.clone()));
        }
        return res;
      }).catch(() => cached);
      return cached || networkFetch;
    })
  );
});
