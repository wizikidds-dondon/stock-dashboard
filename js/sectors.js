/* 類股監控模組 */
const SectorsModule = (() => {
  let currentSector = null;

  function pctClass(pct) {
    if (!pct && pct !== 0) return 'price-flat';
    return pct > 0 ? 'price-up' : pct < 0 ? 'price-down' : 'price-flat';
  }

  function pctStr(pct) {
    if (pct == null) return '─';
    return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`;
  }

  function maBadge(pos, label) {
    if (!pos) return `<span class="ma-badge ma-na">${label}─</span>`;
    const cls = pos === 'above' ? 'ma-above' : 'ma-below';
    const arr = pos === 'above' ? '↑' : '↓';
    return `<span class="ma-badge ${cls}">${label}${arr}</span>`;
  }

  // ── 類股卡片 ─────────────────────────────

  function renderSectorCard(s) {
    const pct = pctStr(s.avg_change_pct);
    const cls = pctClass(s.avg_change_pct);
    const total = s.advancing + s.declining;
    const advPct = total > 0 ? (s.advancing / total * 100).toFixed(0) : 50;

    return `<div class="sector-card" data-key="${s.key}" onclick="SectorsModule.selectSector('${s.key}', '${s.name}')">
      <div class="sector-card-header">
        <div class="sector-name">${s.name}</div>
        <div class="sector-chg ${cls}">${pct}</div>
      </div>
      <div class="sector-adv-dec">
        <span class="adv">▲ ${s.advancing} 漲</span>
        <span class="dec">▼ ${s.declining} 跌</span>
        <span style="color:var(--muted)">${s.stock_count} 支</span>
      </div>
      <div class="sector-bar">
        <div class="sector-bar-fill" style="width:${advPct}%"></div>
      </div>
    </div>`;
  }

  // ── 類股個股表格 ─────────────────────────

  function renderStockRow(s) {
    const sym = (s.symbol || '').replace('.TW', '');
    const cls = pctClass(s.change_pct);
    const pct = pctStr(s.change_pct);
    const price = s.close != null ? s.close.toFixed(2) : '─';

    const sigs = [];
    if (s.bullish_align)    sigs.push(`<span class="signal-tag tag-bullish">多頭</span>`);
    if (s.bearish_align)    sigs.push(`<span class="signal-tag tag-bearish">空頭</span>`);
    if (s.golden_cross_520) sigs.push(`<span class="signal-tag tag-golden">黃金叉</span>`);
    if (s.death_cross_520)  sigs.push(`<span class="signal-tag tag-death">死亡叉</span>`);
    const vol = s.vol_ratio_5d;
    if (vol >= 1.5) sigs.push(`<span class="signal-tag tag-volume">量${vol.toFixed(1)}x</span>`);

    return `<tr>
      <td>
        <div class="td-name">${s.name || '─'}</div>
        <div class="td-symbol">${sym}</div>
      </td>
      <td style="font-family:var(--font-mono);font-weight:600" class="${cls}">${price}</td>
      <td class="${cls}" style="font-family:var(--font-mono)">${pct}</td>
      <td>
        <div class="ma-badges">
          ${maBadge(s.price_vs_ma5, '5')}
          ${maBadge(s.price_vs_ma20, '20')}
          ${maBadge(s.price_vs_ma60, '60')}
        </div>
      </td>
      <td>${sigs.length ? `<div class="signal-tags">${sigs.join('')}</div>` : '─'}</td>
      <td>
        <button class="btn btn-sm btn-outline btn-add-to-wl" data-symbol="${s.symbol}" data-name="${s.name}">
          + 觀察
        </button>
      </td>
    </tr>`;
  }

  // ── 主要載入邏輯 ─────────────────────────

  async function load() {
    const grid = document.getElementById('sectors-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>載入類股資料…</p></div>';

    try {
      const sectors = await API.getSectors();
      grid.innerHTML = sectors.map(renderSectorCard).join('');
      // 恢復選取狀態
      if (currentSector) {
        document.querySelector(`.sector-card[data-key="${currentSector}"]`)?.classList.add('active');
      }
    } catch (e) {
      grid.innerHTML = `<div class="empty-state"><p>載入失敗: ${e.message}</p></div>`;
    }
  }

  async function selectSector(key, name) {
    // 更新卡片選取
    document.querySelectorAll('.sector-card').forEach(c => c.classList.remove('active'));
    document.querySelector(`.sector-card[data-key="${key}"]`)?.classList.add('active');
    currentSector = key;

    // 顯示詳細面板
    const panel = document.getElementById('sector-stocks-panel');
    const title = document.getElementById('sector-panel-title');
    const tbody = document.getElementById('sector-stocks-tbody');
    panel.style.display = '';
    title.textContent = name;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';

    try {
      const res = await API.getSectorStocks(key);
      const stocks = res.stocks || [];
      if (stocks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">此類股暫無資料</td></tr>';
      } else {
        tbody.innerHTML = stocks.map(renderStockRow).join('');
        // 加入觀察名單按鈕
        tbody.querySelectorAll('.btn-add-to-wl').forEach(btn => {
          btn.addEventListener('click', async () => {
            try {
              await API.addWatchlist({ symbol: btn.dataset.symbol, name: btn.dataset.name });
              showToast(`已加入觀察名單: ${btn.dataset.name}`, 'success');
              btn.textContent = '✓ 已加入';
              btn.disabled = true;
            } catch (e) {
              showToast('加入失敗: ' + e.message, 'error');
            }
          });
        });
      }
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">載入失敗: ${e.message}</td></tr>`;
    }
  }

  function init() {
    // 刷新按鈕
    document.getElementById('btn-refresh-sectors')?.addEventListener('click', load);
    // 關閉面板
    document.getElementById('btn-close-sector-panel')?.addEventListener('click', () => {
      document.getElementById('sector-stocks-panel').style.display = 'none';
      document.querySelectorAll('.sector-card').forEach(c => c.classList.remove('active'));
      currentSector = null;
    });
  }

  return { init, load, selectSector };
})();
