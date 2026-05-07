/* 資金流向模組 */
const FlowModule = (() => {
  let state = { days: 5, institution: 'total' };

  // ── 格式化工具 ────────────────────────────

  function fmtShares(n) {
    // 原始股數 → 張 (1張=1000股)
    const lots = Math.round(Math.abs(n) / 1000);
    if (lots >= 10000) return (lots / 10000).toFixed(1) + '萬張';
    if (lots >= 1000)  return (lots / 1000).toFixed(1) + '千張';
    return lots.toLocaleString() + '張';
  }

  function fmtValue(n) {
    // TWD → 億
    const yi = Math.abs(n) / 1e8;
    if (yi >= 100) return yi.toFixed(0) + '億';
    return yi.toFixed(2) + '億';
  }

  function netClass(n) {
    if (!n || n === 0) return 'price-flat';
    return n > 0 ? 'price-down' : 'price-up'; // 台灣慣例：綠漲紅跌
  }

  function netSign(n) {
    if (n == null || n === 0) return '─';
    const sign = n > 0 ? '+' : '-';
    return sign + fmtShares(n);
  }

  function instLabel(key) {
    return { total: '合計', foreign: '外資', trust: '投信', dealer: '自營商' }[key] || key;
  }

  // ── Section A: 類股資金流向 橫向Bar ───────

  function renderSectorBars(data) {
    const el = document.getElementById('flow-sectors-container');
    if (!el) return;

    const sectors = (data.sectors || []).filter(s => s.net_shares !== 0 && s.net_shares != null);
    if (!sectors.length) {
      el.innerHTML = '<div class="flow-empty">目前沒有類股資金資料，請先更新法人資料</div>';
      return;
    }

    const maxAbs = Math.max(...sectors.map(s => Math.abs(s.net_shares || 0)), 1);

    const rows = sectors.map(s => {
      const val = s.net_shares || 0;
      const pct = Math.min(Math.abs(val / maxAbs) * 50, 50);
      const isBuy = val >= 0;
      const barClass = isBuy ? 'flow-bar-buy' : 'flow-bar-sell';
      const valClass = netClass(val);
      const countTxt = s.stock_count > 0 ? `<span style="color:var(--muted);font-size:11px">${s.stock_count}支</span>` : '';

      return `<div class="flow-sector-row">
        <div class="flow-sector-name">${s.sector_name} ${countTxt}</div>
        <div class="flow-bar-wrap">
          <div class="flow-bar-center"></div>
          <div class="flow-bar-fill ${barClass}" style="width:${pct.toFixed(1)}%"></div>
        </div>
        <div class="flow-sector-value ${valClass}">${netSign(val)}</div>
      </div>`;
    });

    const range = data.date_range || [];
    const subtitle = range.length === 2
      ? `<span style="font-size:12px;color:var(--muted);font-weight:400">${range[0]} ~ ${range[1]}</span>`
      : '';

    el.innerHTML = `
      <div style="margin-bottom:8px;font-size:13px;font-weight:600">${instLabel(data.institution)} 類股資金流向 ${subtitle}</div>
      <div class="flow-sector-list">${rows.join('')}</div>`;
  }

  // ── Section B: 個股排行 ───────────────────

  function renderRankTable(tbodyId, stocks, isBuy) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    if (!stocks.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted)">無資料</td></tr>`;
      return;
    }
    tbody.innerHTML = stocks.slice(0, 20).map((s, i) => {
      const sym = (s.symbol || '').replace('.TW', '');
      const cls = isBuy ? 'price-down' : 'price-up';
      const sharesStr = fmtShares(Math.abs(s.net_shares || 0));
      const valueStr  = s.net_value ? fmtValue(s.net_value) : '─';
      return `<tr>
        <td class="flow-rank-num">${i + 1}</td>
        <td>
          <div style="font-weight:600">${s.name || '─'}</div>
          <div class="td-symbol">${sym}</div>
        </td>
        <td style="color:var(--muted);font-size:11px;white-space:nowrap">${s.sector_name || '─'}</td>
        <td class="${cls}" style="font-family:var(--font-mono);font-weight:600">${sharesStr}</td>
        <td style="color:var(--muted);font-family:var(--font-mono)">${valueStr}</td>
      </tr>`;
    }).join('');
  }

  // ── Section C: 資金熱區矩陣 ───────────────

  function cellBg(value, maxAbs) {
    if (!value || maxAbs === 0) return 'transparent';
    const intensity = Math.min(Math.abs(value) / maxAbs, 1);
    const alpha = (0.08 + intensity * 0.55).toFixed(2);
    if (value > 0) return `rgba(63,185,80,${alpha})`;
    return `rgba(248,81,73,${alpha})`;
  }

  function renderMatrix(data) {
    const el = document.getElementById('flow-matrix-container');
    if (!el) return;
    const sectors = data.sectors || [];
    const matData = data.data || {};
    const maxAbs  = data.max_abs || 1;
    const insts = [
      { key: 'foreign', label: '外資' },
      { key: 'trust',   label: '投信' },
      { key: 'dealer',  label: '自營商' },
    ];
    if (!sectors.length) {
      el.innerHTML = '<div class="flow-empty">目前沒有矩陣資料</div>';
      return;
    }
    const headerCols = insts.map(i => `<th>${i.label}</th>`).join('');
    const rows = sectors.map(sector => {
      const cells = insts.map(inst => {
        const v   = (matData[sector] || {})[inst.key] || 0;
        const bg  = cellBg(v, maxAbs);
        const cls = netClass(v);
        const txt = v !== 0 ? netSign(v) : '─';
        return `<td style="background:${bg}"><span class="${cls}">${txt}</span></td>`;
      }).join('');
      return `<tr><td>${sector}</td>${cells}</tr>`;
    }).join('');

    el.innerHTML = `
      <div class="flow-matrix-wrap">
        <table class="flow-matrix-table">
          <thead><tr><th>類股</th>${headerCols}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // ── 資料載入 ──────────────────────────────

  async function loadSectors() {
    const el = document.getElementById('flow-sectors-container');
    if (el) el.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>載入中…</p></div>';
    try {
      const data = await API.get(`/api/flow/sectors?days=${state.days}&institution=${state.institution}`);
      renderSectorBars(data);
    } catch (e) {
      if (el) el.innerHTML = `<div class="flow-empty">載入失敗: ${e.message}</div>`;
    }
  }

  async function loadStocks() {
    const loadRow = '<tr><td colspan="5" style="text-align:center;padding:20px"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    document.getElementById('flow-buy-tbody') ?.innerHTML && (document.getElementById('flow-buy-tbody').innerHTML  = loadRow);
    document.getElementById('flow-sell-tbody')?.innerHTML && (document.getElementById('flow-sell-tbody').innerHTML = loadRow);
    document.getElementById('flow-buy-tbody').innerHTML  = loadRow;
    document.getElementById('flow-sell-tbody').innerHTML = loadRow;
    try {
      const data = await API.get(`/api/flow/stocks?days=${state.days}&institution=${state.institution}&limit=20`);
      renderRankTable('flow-buy-tbody',  data.buy  || [], true);
      renderRankTable('flow-sell-tbody', data.sell || [], false);
    } catch (e) {
      const errRow = (msg) => `<tr><td colspan="5" style="color:var(--up);padding:16px;text-align:center">${msg}</td></tr>`;
      document.getElementById('flow-buy-tbody') .innerHTML = errRow(e.message);
      document.getElementById('flow-sell-tbody').innerHTML = errRow(e.message);
    }
  }

  async function loadMatrix() {
    const el = document.getElementById('flow-matrix-container');
    if (el) el.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>載入中…</p></div>';
    try {
      const data = await API.get('/api/flow/matrix');
      renderMatrix(data);
    } catch (e) {
      if (el) el.innerHTML = `<div class="flow-empty">載入失敗: ${e.message}</div>`;
    }
  }

  async function load() {
    await Promise.all([loadSectors(), loadStocks(), loadMatrix()]);
  }

  // ── 初始化 ────────────────────────────────

  function init() {
    // 時間區間切換
    document.getElementById('flow-days-chips')?.addEventListener('click', e => {
      const chip = e.target.closest('[data-days]');
      if (!chip) return;
      document.querySelectorAll('#flow-days-chips .chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.days = parseInt(chip.dataset.days, 10);
      loadSectors();
      loadStocks();
    });

    // 法人切換
    document.getElementById('flow-inst-chips')?.addEventListener('click', e => {
      const chip = e.target.closest('[data-inst]');
      if (!chip) return;
      document.querySelectorAll('#flow-inst-chips .chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.institution = chip.dataset.inst;
      loadSectors();
      loadStocks();
    });
  }

  return { init, load };
})();
