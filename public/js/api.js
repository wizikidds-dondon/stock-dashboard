/* API 客戶端 - 靜態 JSON 版本 */

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

  function calcFlowSectors(institutional, instType) {
    const SECTOR_MAP = {
      '台積電':'半導體','聯發科':'半導體','聯電':'半導體','日月光':'半導體','瑞毅':'半導體',
      '鴻海':'電子零組件','廣達':'電子零組件','台達電子':'電子零組件','桑世安':'電子零組件','光美':'電子零組件',
      '富邦金':'金融','國泰金':'金融','兆豐金':'金融','中信金':'金融','玉山金':'金融',
      '中龋鲸':'傳產/鋼鐵','東和這':'傳產/鋼鐵','永豊':'傳產/鋼鐵',
      '台塑一':'石化','南亞塑衫':'石化','台塔山':'石化',
      '中華電':'電信','台灣大哥大':'電信','遠傳':'電信',
    };
    const sectorData = {};
    for (const rec of institutional) {
      const net = instType==='foreign'?rec.foreign_net:instType==='trust'?rec.trust_net:instType==='dealer'?rec.dealer_net:rec.total_net;
      const sector = SECTOR_MAP[rec.name] || '其他';
      if (!sectorData[sector]) sectorData[sector] = { sector_name: sector, net_shares: 0, stock_count: 0 };
      sectorData[sector].net_shares += (net || 0);
      sectorData[sector].stock_count++;
    }
    return Object.values(sectorData).filter(s => s.net_shares !== 0).sort((a,b) => b.net_shares - a.net_shares);
  }

  function calcFlowStocks(institutional, instType, limit) {
    const mapped = institutional.map(rec => ({
      symbol:rec.symbol, name:rec.name,
      net:instType==='foreign'?rec.foreign_net:instType==='trust'?rec.trust_net:instType==='dealer'?rec.dealer_net:rec.total_net,
      foreign_net:rec.foreign_net, trust_net:rec.trust_net, dealer_net:rec.dealer_net, total_net:rec.total_net,
    })).filter(r => r.net !== 0 && r.net != null);
    return { buy: mapped.filter(r=>r.net>0).sort((a,b)=>b.net-a.net).slice(0,limit), sell: mapped.filter(r=>r.net<0).sort((a,b)=>a.net-b.net).slice(0,limit) };
  }

  function calcFlowMatrix(institutional) {
    const SECTORS = ['半導體','電子零組件','金融','傳產/鋼鐵','石化','電信'];
    const SECTOR_MAP = {
      '台積電':'半導體','聯發科':'半導體','聯電':'半導體','日月光':'半導體','瑞毅':'半導體',
      '鴻海':'電子零組件','廣達':'電子零組件','台達電子':'電子零組件','桑世安':'電子零組件','光美':'電子零組件',
      '富邦金':'金融','國泰金':'金融','兆豐金':'金融','中信金':'金融','玉山金':'金融',
      '中龋鲸':'傳產/鋼鐵','東和這':'傳產/鋼鐵','永豊':'傳產/鋼鐵',
      '台塑一':'石化','南亞塑衫':'石化','台塔山':'石化',
      '中華電':'電信','台灣大哥大':'電信','遠傳':'電信',
    };
    const matrix = {};
    for (const rec of institutional) {
      const sector = SECTOR_MAP[rec.name];
      if (!sector) continue;
      if (!matrix[sector]) matrix[sector] = { foreign:0, trust:0, dealer:0 };
      matrix[sector].foreign += rec.foreign_net||0;
      matrix[sector].trust += rec.trust_net||0;
      matrix[sector].dealer += rec.dealer_net||0;
    }
    const sectors = SECTORS.filter(s => matrix[s]);
    const data = {};
    for (const s of sectors) data[s] = matrix[s];
    return { sectors, data, max_abs: Math.max(...Object.values(data).flatMap(v=>Object.values(v).map(Math.abs)),1) };
  }

  return {
    get: async (path) => {
      const data = await loadData();
      const inst = data.institutional || [];
      const p = new URLSearchParams(path.includes('?') ? path.split('?')[1] : '');
      const instType = p.get('institution') || 'total';
      const limit = parseInt(p.get('limit') || '20');
      if (path.includes('/flow/sectors')) return { sectors: calcFlowSectors(inst, instType), date_range: [data.updated_at] };
      if (path.includes('/flow/stocks')) return calcFlowStocks(inst, instType, limit);
      if (path.includes('/flow/matrix')) return calcFlowMatrix(inst);
      if (path.includes('institutional')) return { data: inst };
      if (path.includes('sectors/catalog')) return Object.keys(data.sectors || {});
      if (path.includes('/sectors/')) {
        const key = decodeURIComponent(path.split('/sectors/')[1].split('?')[0]);
        const sector = (data.sectors||{})[key];
        if (!sector) return [];
        return sector.stocks.map(s => { const full=findStock(data,s.symbol); return {symbol:s.symbol,name:full?.name||s.symbol,price:s.close,change_pct:s.change_pct}; });
      }
      return {};
    },
    post: async (path, body) => {
      if (path.includes('watchlist') && body && body.symbol) {
        const list = getWatchlistSymbols();
        const sym = body.symbol.includes('.TW') ? body.symbol : body.symbol+'.TW';
        if (!list.includes(sym)) { list.push(sym); saveWatchlistSymbols(list); }
        return { success: true };
      }
      return { success: true };
    },
    getWatchlist: async () => {
      const data = await loadData();
      const symbols = getWatchlistSymbols();
      const targets = symbols.length > 0 ? symbols : data.stocks.map(s => s.symbol);
      return data.stocks.filter(s => targets.includes(s.symbol)).map(s => ({
        symbol:s.symbol, name:s.name, price:s.close, change:s.change,
        change_pct:s.change_pct, volume:s.volume, ma5:s.ma5, ma20:s.ma20, note:s.note||'',
      }));
    },
    addWatchlist: async ({ symbol }) => {
      const list = getWatchlistSymbols();
      const sym = symbol.includes('.TW') ? symbol : symbol+'.TW';
      if (!list.includes(sym)) { list.push(sym); saveWatchlistSymbols(list); }
      return { success: true };
    },
    removeWatchlist: async (symbol) => {
      saveWatchlistSymbols(getWatchlistSymbols().filter(s => s!==symbol && s!==symbol+'.TW'));
      return { success: true };
    },
    updateNote: async (symbol, note) => {
      const notes = JSON.parse(localStorage.getItem('notes')||'{}');
      notes[symbol] = note; localStorage.setItem('notes', JSON.stringify(notes));
      return { success: true };
    },
    getHistory: async (symbol, days) => {
      const data = await loadData();
      const stock = findStock(data, symbol);
      if (!stock) throw new Error('找不到 '+symbol);
      return { symbol:stock.symbol, name:stock.name, history:days?stock.history.slice(-days):stock.history };
    },
    getQuote: async (symbol) => {
      const data = await loadData();
      const stock = findStock(data, symbol);
      if (!stock) throw new Error('找不到 '+symbol);
      return { symbol:stock.symbol, name:stock.name, price:stock.close, change:stock.change,
        change_pct:stock.change_pct, volume:stock.volume, ma5:stock.ma5, ma10:stock.ma10,
        ma20:stock.ma20, ma60:stock.ma60, high_52w:stock.high_52w, low_52w:stock.low_52w,
        market_cap:stock.market_cap, pe_ratio:stock.pe_ratio };
    },
    getSectors: async () => {
      const data = await loadData();
      return Object.entries(data.sectors).map(([name, info]) => {
        const up = info.stocks.filter(s => s.change_pct > 0).length;
        const down = info.stocks.filter(s => s.change_pct < 0).length;
        return { key:name, name, avg_change_pct:info.avg_change_pct, change_pct:info.avg_change_pct,
          stock_count:info.stocks.length, advancing:up, declining:down };
      });
    },
    getSectorStocks: async (key) => {
      const data = await loadData(); const sector = data.sectors[key]; if (!sector) return [];
      return sector.stocks.map(s => { const full=findStock(data,s.symbol); return {symbol:s.symbol,name:full?.name||s.symbol,price:s.close,change_pct:s.change_pct}; });
    },
    getSectorsCatalog: async () => { const data = await loadData(); return Object.keys(data.sectors); },
    screen: async (params) => {
      const data = await loadData(); let stocks = data.stocks;
      const p = typeof params==='string' ? Object.fromEntries(new URLSearchParams(params)) : params;
      if (p.change_pct_min!=null) stocks=stocks.filter(s=>s.change_pct>=+p.change_pct_min);
      if (p.change_pct_max!=null) stocks=stocks.filter(s=>s.change_pct<=+p.change_pct_max);
      if (p.volume_min!=null) stocks=stocks.filter(s=>s.volume>=+p.volume_min);
      if (p.above_ma20==='true') stocks=stocks.filter(s=>s.ma20&&s.close>s.ma20);
      if (p.below_ma20==='true') stocks=stocks.filter(s=>s.ma20&&s.close<s.ma20);
      if (p.sector) stocks=stocks.filter(s=>s.sector&&s.sector.includes(p.sector));
      return stocks.map(s=>({symbol:s.symbol,name:s.name,price:s.close,change_pct:s.change_pct,volume:s.volume,ma5:s.ma5,ma20:s.ma20}));
    },
    refreshAll: async () => { const data=await loadData(); return {status:'static',message:'資料更新於 '+data.updated_at,updated_at:data.updated_at}; },
    refreshSymbol: async () => ({status:'static',message:'靜態模式，請等待每日自動更新'}),
    getRefreshStatus: async () => { const data=await loadData(); return {status:'idle',last_updated:data.updated_at,updated_timestamp:data.updated_timestamp}; },
    getSettings: async () => { try { return JSON.parse(localStorage.getItem('settings')||'{}'); } catch { return {}; } },
    saveSettings: async (settings) => { localStorage.setItem('settings',JSON.stringify(settings)); return {success:true}; },
    testTelegram: async () => ({success:false,message:'靜態模式不支援 Telegram 推送'}),
    sendReport: async () => ({success:false,message:'靜態模式不支援 Telegram 推送'}),
    previewReport: async () => ({preview:'靜態模式不支援預覽'}),
    getReportLog: async () => ([]),
    searchStocks: async (q) => {
      const data=await loadData(); const query=q.toLowerCase();
      return data.stocks.filter(s=>s.symbol.toLowerCase().includes(query)||(s.name&&s.name.toLowerCase().includes(query))
      ).map(s=>({symbol:s.symbol,name:s.name,price:s.close,change_pct:s.change_pct}));
    },
  };
})();
