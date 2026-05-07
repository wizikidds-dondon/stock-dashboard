/* API 客戶端 */
const API = (() => {
  const BASE = '';

  async function req(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(BASE + path, opts);
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
    return json;
  }

  return {
    get:    (path)         => req('GET',    path),
    post:   (path, body)   => req('POST',   path, body),
    put:    (path, body)   => req('PUT',    path, body),
    delete: (path)         => req('DELETE', path),

    // 觀察名單
    getWatchlist:      ()            => req('GET',    '/api/watchlist'),
    addWatchlist:      (data)        => req('POST',   '/api/watchlist', data),
    removeWatchlist:   (symbol)      => req('DELETE', `/api/watchlist/${encodeURIComponent(symbol)}`),
    updateNote:        (symbol, note)=> req('PUT',    `/api/watchlist/${encodeURIComponent(symbol)}/note`, { note }),

    // 個股
    getHistory:        (symbol, days)=> req('GET',    `/api/stock/${encodeURIComponent(symbol)}/history?days=${days || 90}`),
    getQuote:          (symbol)      => req('GET',    `/api/stock/${encodeURIComponent(symbol)}/quote`),

    // 類股
    getSectors:        ()            => req('GET',    '/api/sectors'),
    getSectorStocks:   (key)         => req('GET',    `/api/sectors/${encodeURIComponent(key)}`),
    getSectorsCatalog: ()            => req('GET',    '/api/sectors/catalog'),

    // 篩選
    screen:            (params)      => req('GET',    `/api/screen?${params}`),

    // 刷新
    refreshAll:        ()            => req('POST',   '/api/refresh'),
    refreshSymbol:     (symbol)      => req('POST',   `/api/refresh/${encodeURIComponent(symbol)}`),
    getRefreshStatus:  ()            => req('GET',    '/api/refresh/status'),

    // 設定
    getSettings:       ()            => req('GET',    '/api/settings'),
    saveSettings:      (data)        => req('PUT',    '/api/settings', data),

    // Telegram
    testTelegram:      ()            => req('POST',   '/api/telegram/test'),
    sendReport:        ()            => req('POST',   '/api/telegram/report'),
    previewReport:     ()            => req('GET',    '/api/telegram/preview'),
    getReportLog:      ()            => req('GET',    '/api/report/log'),

    // 搜尋
    searchStocks:      (q)           => req('GET',    `/api/stocks/search?q=${encodeURIComponent(q)}`),
  };
})();
