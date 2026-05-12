/* API 客戶端 - 靜態 JSON 版本
 * 改成讀取 data.json
 */

const API = (() => {
  let _cache = null, _cacheTime = 0;
  const CACHE_TTL = 60000;
  async function loadData() {
    const now = Date.now();
    if (_cache && now - _cacheTime < CACHE_TTL) return _cache;
    const res = await fetch('./data.json?t=' + now);
    if (!res.ok) throw new Error('無法載入資料');
    _cache = await res.json();
    _cacheTime = now;
    return _cache;
  }
  function getWatchlistSymbols() {
    try { return JSON.parse(localStorage.getItem('watchlist') || '[]'); } catch { return []; }
  }
  function saveWatchlistSymbols(list) { localStorage.setItem('watchlist', JSON.stringify(list)); }
  function findStock(data, symbol) {
    return data.stocks.find(s => s.symbol === symbol || s.symbol === symbol + '.TW');
  }
  return {
    getWatchlist: async () => {
      const data = await loadData();
      const symbols = getWatchlistSymbols();
      const targets = symbols.length > 0 ? symbols : data.stocks.map(s => s.symbol);
      return data.stocks.filter(s => targets.includes(s.symbol)).map(s => ({
        symbol: s.symbol, name: s.name, price: s.close, change: s.change,
        change_pct: s.change_pct, volume: s.volume, ma5: s.ma5, ma20: s.ma20, note: s.note || '',
      }));
    },
    addWatchlist: async ({ symbol }) => {
      const list = getWatchlistSymbols();
      const sym = symbol.includes('.TW') ? symbol : symbol + '.TW';
      if (!list.includes(sym)) { list.push(sym); saveWatchlistSymbols(list); }
      return { success: true };
    },
    removeWatchlist: async (symbol) => {
      saveWatchlistSymbols(getWatchlistSymbols().filter(s => s !== symbol && s !== symbol + '.TW'));
      return { success: true };
    },
    updateNote: async (symbol, note) => {
      const notes = JSON.parse(localStorage.getItem('notes') || '{}');
      notes[symbol] = note;
      localStorage.setItem('notes', JSON.stringify(notes));
      return { success: true };
    },
    getHistory: async (symbol, days) => {
      const data = await loadData();
      const stock = findStock(data, symbol);
      if (!stock) throw new Error('找不到 ' + symbol);
      return { symbol: stock.symbol, name: stock.name, history: days ? stock.history.slice(-days) : stock.history };
    },
    getQuote: async (symbol) => {
      const data = await loadData();
      const stock = findStock(data, symbol);
      if (!stock) throw new Error('找不到 ' + symbol);
      return { symbol: stock.symbol, name: stock.name, price: stock.close, change: stock.change,
        change_pct: stock.change_pct, volume: stock.volume, ma5: stock.ma5, ma10: stock.ma10,
        ma20: stock.ma20, ma60: stock.ma60, high_52w: stock.high_52w, low_52w: stock.low_52w,
        market_cap: stock.market_cap, pe_ratio: stock.pe_ratio };
    },
    getSectors: async () => {
      const data = await loadData();
      return Object.entries(data.sectors).map(([name, info]) => ({
        name, change_pct: info.avg_change_pct, stock_count: info.stocks.length }));
    },
    getSectorStocks: async (key) => {
      const data = await loadData();
      const sector = data.sectors[key];
      if (!sector) return [];
      return sector.stocks.map(s => {
        const full = findStock(data, s.symbol);
        return { symbol: s.symbol, name: full?.name || s.symbol, price: s.close, change_pct: s.change_pct };
      });
    },
    getSectorsCatalog: async () => { const data = await loadData(); return Object.keys(data.sectors); },
    screen: async (params) => {
      const data = await loadData();
      let stocks = data.stocks;
      const p = typeof params === 'string' ? Object.fromEntries(new URLSearchParams(params)) : params;
      if (p.change_pct_min != null) stocks = stocks.filter(s => s.change_pct >= +p.change_pct_min);
      if (p.change_pct_max != null) stocks = stocks.filter(s => s.change_pct <= +p.change_pct_max);
      if (p.volume_min != null) stocks = stocks.filter(s => s.volume >= +p.volume_min);
      if (p.above_ma20 === 'true') stocks = stocks.filter(s => s.ma20 && s.close > s.ma20);
      if (p.below_ma20 === 'true') stocks = stocks.filter(s => s.ma20 && s.close < s.ma20);
      if (p.sector) stocks = stocks.filter(s => s.sector && s.sector.includes(p.sector));
      return stocks.map(s => ({ symbol: s.symbol, name: s.name, price: s.close,
        change_pct: s.change_pct, volume: s.volume, ma5: s.ma5, ma20: s.ma20 }));
    },
    refreshAll: async () => {
      const data = await loadData();
      return { status: 'static', message: '資料更新於 ' + data.updated_at, updated_at: data.updated_at };
    },
    refreshSymbol: async () => ({ status: 'static', message: '靜態模式，請等待每日自動更新' }),
    getRefreshStatus: async () => {
      const data = await loadData();
      return { status: 'idle', last_updated: data.updated_at, updated_timestamp: data.updated_timestamp };
    },
    getSettings: async () => { try { return JSON.parse(localStorage.getItem('settings') || '{}'); } catch { return {}; } },
    saveSettings: async (settings) => { localStorage.setItem('settings', JSON.stringify(settings)); return { success: true }; },
    testTelegram: async () => ({ success: false, message: '靜態模式不支援 Telegram 推送' }),
    sendReport: async () => ({ success: false, message: '靜態模式不支援 Telegram 推送' }),
    previewReport: async () => ({ preview: '靜態模式不支援預覽' }),
    getReportLog: async () => ([]),
    searchStocks: async (q) => {
      const data = await loadData();
      const query = q.toLowerCase();
      return data.stocks.filter(s =>
        s.symbol.toLowerCase().includes(query) || (s.name && s.name.toLowerCase().includes(query))
      ).map(s => ({ symbol: s.symbol, name: s.name, price: s.close, change_pct: s.change_pct }));
    },
    // 相容舊版 HTTP 方法（screener.js / flow.js 使用）
    get: async (path) => {
      const data = await loadData();
      if (path.includes('institutional')) return { data: data.institutional || [] };
      if (path.includes('watchlist')) return await API.getWatchlist();
      if (path.includes('sectors/catalog')) return await API.getSectorsCatalog();
      if (path.includes('sectors')) return await API.getSectors();
      if (path.includes('refresh/status')) return await API.getRefreshStatus();
      if (path.includes('settings')) return await API.getSettings();
      return {};
    },
    post: async (path, body) => {
      if (path.includes('watchlist') && body && body.symbol) return await API.addWatchlist(body);
      if (path.includes('refresh')) return await API.refreshAll();
      if (path.includes('telegram/test')) return await API.testTelegram();
      if (path.includes('telegram/report')) return await API.sendReport();
      if (path.includes('settings')) return await API.saveSettings(body);
      return { success: true };
    },
    put: async (path, body) => {
      if (path.includes('watchlist') && path.includes('note')) {
        const sym = decodeURIComponent(path.split('/').slice(-2)[0]);
        return await API.updateNote(sym, body?.note || '');
      }
      if (path.includes('settings')) return await API.saveSettings(body);
      return { success: true };
    },
    delete: async (path) => {
      const sym = decodeURIComponent(path.split('/').pop());
      return await API.removeWatchlist(sym);
    },
  };
})();
