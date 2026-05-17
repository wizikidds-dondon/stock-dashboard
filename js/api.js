/* API - Static JSON v3 */
const API = (() => {
  let _c = null, _t = 0;
  const TTL = 60000;
  async function load() {
    const now = Date.now();
    if (_c && now - _t < TTL) return _c;
    const r = await fetch('./data.json?t=' + now);
    if (!r.ok) throw new Error('load failed');
    _c = await r.json(); _t = now; return _c;
  }
  function gWL() { try { return JSON.parse(localStorage.getItem('wl')||'[]'); } catch { return []; } }
  function sWL(l) { localStorage.setItem('wl', JSON.stringify(l)); }
  function fS(d, sym) { return d.stocks.find(s => s.symbol===sym || s.symbol===sym+'.TW'); }
  const SM = {'台積電':'半導體','聯發科':'半導體','聯電':'半導體','日月光':'半導體','瑞毅':'半導體','嘉談':'半導體','鴻海':'電子零組件','廣達':'電子零組件','台達電子':'電子零組件','桑世安':'電子零組件','光美':'電子零組件','儲光':'電子零組件','富邦金':'金融','國泰金':'金融','兆豐金':'金融','中信金':'金融','玉山金':'金融','元大金':'金融','合庫金':'金融','彰銀':'金融','中龋鲸':'傳產/鋼鐵','東和這':'傳產/鋼鐵','永豊':'傳產/鋼鐵','台塑一':'石化','南亞塑衫':'石化','台塔山':'石化','台化':'石化','中華電':'電信','台灣大哥大':'電信','遠傳':'電信'};
  function fSectors(inst,tp){const d={};for(const r of inst){const n=tp==='foreign'?r.foreign_net:tp==='trust'?r.trust_net:tp==='dealer'?r.dealer_net:r.total_net;const s=SM[r.name]||'其他';if(!d[s])d[s]={sector_name:s,net_shares:0,stock_count:0};d[s].net_shares+=(n||0);d[s].stock_count++;}return Object.values(d).filter(s=>s.net_shares!==0).sort((a,b)=>b.net_shares-a.net_shares);}
  function fStocks(inst,tp,lim){const m=inst.map(r=>({symbol:r.symbol,name:r.name,net:tp==='foreign'?r.foreign_net:tp==='trust'?r.trust_net:tp==='dealer'?r.dealer_net:r.total_net,foreign_net:r.foreign_net,trust_net:r.trust_net,dealer_net:r.dealer_net,total_net:r.total_net})).filter(r=>r.net!=null&&r.net!==0);return{buy:m.filter(r=>r.net>0).sort((a,b)=>b.net-a.net).slice(0,lim),sell:m.filter(r=>r.net<0).sort((a,b)=>a.net-b.net).slice(0,lim)};}
  function fMatrix(inst){const SECS=['半導體','電子零組件','金融','傳產/鋼鐵','石化','電信'];const mx={};for(const r of inst){const s=SM[r.name];if(!s)continue;if(!mx[s])mx[s]={foreign:0,trust:0,dealer:0};mx[s].foreign+=r.foreign_net||0;mx[s].trust+=r.trust_net||0;mx[s].dealer+=r.dealer_net||0;}const secs=SECS.filter(s=>mx[s]);const data={};for(const s of secs)data[s]=mx[s];return{sectors:secs,data,max_abs:Math.max(...Object.values(data).flatMap(v=>Object.values(v).map(Math.abs)),1)};}
  return {
    get: async(path)=>{const d=await load();const inst=d.institutional||[];const p=new URLSearchParams(path.includes('?')?path.split('?')[1]:'');const tp=p.get('institution')||'total';const lim=parseInt(p.get('limit')||'20');if(path.includes('/flow/sectors'))return{sectors:fSectors(inst,tp),date_range:[d.updated_at]};if(path.includes('/flow/stocks'))return fStocks(inst,tp,lim);if(path.includes('/flow/matrix'))return fMatrix(inst);if(path.includes('institutional'))return{data:inst};if(path.includes('sectors/catalog'))return Object.keys(d.sectors||{});if(path.includes('/sectors/')){const k=decodeURIComponent(path.split('/sectors/')[1].split('?')[0]);const sec=(d.sectors||{})[k];if(!sec)return[];return sec.stocks.map(s=>{const f=fS(d,s.symbol);return{symbol:s.symbol,name:f?.name||s.symbol,price:s.close,change_pct:s.change_pct};});}return{};},
    post: async(path,body)=>{if(path.includes('watchlist')&&body?.symbol){const l=gWL();const sym=body.symbol.includes('.TW')?body.symbol:body.symbol+'.TW';if(!l.includes(sym)){l.push(sym);sWL(l);}return{success:true};}return{success:true};},
    getWatchlist: async()=>{const d=await load();let syms=gWL();if(syms.length===0){syms=d.stocks.map(s=>s.symbol);sWL(syms);}return d.stocks.filter(s=>syms.includes(s.symbol)).map(s=>({symbol:s.symbol,name:s.name,price:s.close,change:s.change,change_pct:s.change_pct,volume:s.volume,ma5:s.ma5,ma20:s.ma20,note:s.note||''}));},
    addWatchlist: async({symbol})=>{const l=gWL();const sym=symbol.includes('.TW')?symbol:symbol+'.TW';if(!l.includes(sym)){l.push(sym);sWL(l);}return{success:true};},
    removeWatchlist: async(symbol)=>{sWL(gWL().filter(s=>s!==symbol&&s!==symbol+'.TW'));return{success:true};},
    updateNote: async(symbol,note)=>{const n=JSON.parse(localStorage.getItem('notes')||'{}');n[symbol]=note;localStorage.setItem('notes',JSON.stringify(n));return{success:true};},
    getHistory: async(symbol,days)=>{const d=await load();const s=fS(d,symbol);if(!s)throw new Error('not found');return{symbol:s.symbol,name:s.name,history:days?s.history.slice(-days):s.history};},
    getQuote: async(symbol)=>{const d=await load();const s=fS(d,symbol);if(!s)throw new Error('not found');return{symbol:s.symbol,name:s.name,price:s.close,change:s.change,change_pct:s.change_pct,volume:s.volume,ma5:s.ma5,ma10:s.ma10,ma20:s.ma20,ma60:s.ma60,high_52w:s.high_52w,low_52w:s.low_52w,market_cap:s.market_cap,pe_ratio:s.pe_ratio};},
    getSectors: async()=>{const d=await load();return Object.entries(d.sectors).map(([name,info])=>{const up=info.stocks.filter(s=>s.change_pct>0).length;const dn=info.stocks.filter(s=>s.change_pct<0).length;return{key:name,name,avg_change_pct:info.avg_change_pct,change_pct:info.avg_change_pct,stock_count:info.stocks.length,advancing:up,declining:dn};});},
    getSectorStocks: async(key)=>{const d=await load();const sec=d.sectors[key];if(!sec)return[];return sec.stocks.map(s=>{const f=fS(d,s.symbol);return{symbol:s.symbol,name:f?.name||s.symbol,price:s.close,change_pct:s.change_pct};});},
    getSectorsCatalog: async()=>{const d=await load();return Object.keys(d.sectors);},
    screen: async(params)=>{const d=await load();let stocks=d.stocks;const p=typeof params==='string'?Object.fromEntries(new URLSearchParams(params)):params;if(p.change_pct_min!=null)stocks=stocks.filter(s=>s.change_pct>=+p.change_pct_min);if(p.change_pct_max!=null)stocks=stocks.filter(s=>s.change_pct<=+p.change_pct_max);if(p.volume_min!=null)stocks=stocks.filter(s=>s.volume>=+p.volume_min);if(p.above_ma20==='true')stocks=stocks.filter(s=>s.ma20&&s.close>s.ma20);if(p.below_ma20==='true')stocks=stocks.filter(s=>s.ma20&&s.close<s.ma20);if(p.sector)stocks=stocks.filter(s=>s.sector&&s.sector.includes(p.sector));return stocks.map(s=>({symbol:s.symbol,name:s.name,price:s.close,change_pct:s.change_pct,volume:s.volume,ma5:s.ma5,ma20:s.ma20}));},
    refreshAll: async()=>{const d=await load();return{status:'static',message:'資料更新於 '+d.updated_at,updated_at:d.updated_at};},
    refreshSymbol: async()=>({status:'static',message:'靜態模式'}),
    getRefreshStatus: async()=>{const d=await load();return{status:'idle',last_updated:d.updated_at,updated_timestamp:d.updated_timestamp};},
    getSettings: async()=>{try{return JSON.parse(localStorage.getItem('settings')||'{}');}catch{return{};}},
    saveSettings: async(s)=>{localStorage.setItem('settings',JSON.stringify(s));return{success:true};},
    testTelegram: async()=>({success:false,message:'static mode'}),
    sendReport: async()=>({success:false,message:'static mode'}),
    previewReport: async()=>({preview:'static mode'}),
    getReportLog: async()=>([]),
    searchStocks: async(q)=>{const d=await load();const query=q.toLowerCase();return d.stocks.filter(s=>s.symbol.toLowerCase().includes(query)||(s.name&&s.name.toLowerCase().includes(query))).map(s=>({symbol:s.symbol,name:s.name,price:s.close,change_pct:s.change_pct}));},
  };
})();
