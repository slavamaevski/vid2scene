const CACHE_NAME = 'lod-cache-v1';
let sasMaps = {};

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SET_SAS_URLS') {
        const { spjId, sasUrls } = event.data;
        if (spjId && sasUrls) {
            sasMaps[spjId] = sasUrls;
            // console.log(`[SW] Updated SAS URLs for scene ${spjId}: ${Object.keys(sasUrls).length} files`);
        }
    }
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Intercept requests to /virtual/lod/<spjId>/<relativePath>
    if (url.pathname.includes('/virtual/lod/')) {
        const prefix = '/virtual/lod/';
        const pathAfterPrefix = url.pathname.substring(url.pathname.indexOf(prefix) + prefix.length);

        // Extract spjId and relativePath
        const firstSlash = pathAfterPrefix.indexOf('/');
        if (firstSlash === -1) return;

        const spjId = pathAfterPrefix.substring(0, firstSlash);
        const relativePath = pathAfterPrefix.substring(firstSlash + 1);

        const sceneMap = sasMaps[spjId];
        if (!sceneMap) {
            // console.warn(`[SW] No SAS map found for scene ${spjId}`);
            return;
        }

        // Logic to handle potential directory requests from PlayCanvas
        let entry = sceneMap[relativePath];
        if (!entry) {
            // Heuristic: check if appending /meta.json finds a match
            if (sceneMap[relativePath + '/meta.json']) {
                entry = sceneMap[relativePath + '/meta.json'];
            } else if (sceneMap[relativePath + 'meta.json']) {
                entry = sceneMap[relativePath + 'meta.json'];
            }
        }

        if (entry) {
            event.respondWith(
                caches.open(CACHE_NAME).then((cache) => {
                    return cache.match(event.request, { ignoreSearch: true }).then((cachedResponse) => {
                        if (cachedResponse) {
                            const fetchedOn = cachedResponse.headers.get('sw-fetched-on');
                            // Check if cache entry is valid (less than 1 hour old)
                            if (fetchedOn && (Date.now() - parseInt(fetchedOn, 10) < 3600 * 1000)) {
                                return cachedResponse;
                            }
                            // If expired or missing header, allow to fall through to fetch
                        }

                        // Fetch real URL
                        return fetch(entry.url).then((response) => {
                            if (!response || response.status !== 200 || response.type !== 'basic' && response.type !== 'cors') {
                                return response;
                            }

                            // Cache the response with a timestamp
                            const newHeaders = new Headers(response.headers);
                            newHeaders.append('sw-fetched-on', Date.now().toString());

                            const responseToCache = new Response(response.clone().body, {
                                status: response.status,
                                statusText: response.statusText,
                                headers: newHeaders
                            });

                            cache.put(event.request, responseToCache);

                            return response;
                        });
                    });
                })
            );
        }
    }
});
