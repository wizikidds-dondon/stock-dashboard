/* 技術指標篩選模組 */
const ScreenerModule = (() => {
  const filters = {
    ma_position:   null,
    cross:         null,
    volume_surge:  null,
    alignment:     null,
    ma_return:     null,
    ma60_60m:      null,
    institutional: null,
    sector:        null,
  };

  // ── 篩選結果渲染 ─────────────────────────

  function maBadge(pos, label) {
    if (!pos) return `<span class="ma-badge ma-na">${label}─</span>`;
    const cls = pos === 'above' ? 'ma-above' : 'ma-below';
    const arr = pos === 'above' ? '↑' : '↓';
    return `<span class="ma-badge ${cls}">${label}${arr}</span>`;
  }

  function pctStr(pct) {
    if (pct == null) return '─';
    return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`;
  }

  function renderRow(s) {
    const sym = (s.symbol || '').replace('.TW', '');
    const pctCls = s.change_pct > 0 ? 'price-up' : s.change_pct < 0 ? 'price-down' : 'price-flat';
    const price = s.close != null ? s.close.toFixed(2) : '─';

    const sigs = [];
    if (s.bullish_align)     sigs.push(`<span class="signal-tag tag-bullish">多頭排列</span>`);
    if (s.bearish_align)     sigs.push(`<span class="signal-tag tag-bearish">空頭排列</span>`);
    if (s.golden_cross_520)  sigs.push(`<span class="signal-tag tag-golden">5/20黃金交叉</span>`);
    if (s.death_cross_520)   sigs.push(`<span class="signal-tag tag-death">5/20死亡交叉</span>`);
    if (s.golden_cross_2060) sigs.push(`<span class="signal-tag tag-golden">20/60黃金交叉</span>`);
    if (s.death_cross_2060)  sigs.push(`<span class="signal-tag tag-death">20/60死亡交叉</span>`);
    const vol = s.vol_ratio_5d;
    if (vol >= 2.0)  sigs.push(`<span class="signal-tag tag-volume">爆量 ${vol.toFixed(1)}x</span>`);
    else if (vol >= 1.5) sigs.push(`<span class="signal-tag tag-volume">放量 ${vol.toFixed(1)}x</span>`);
    // 60分K MA60
    if (s.price_vs_ma60_60m === 'above') sigs.push(`<span class="signal-tag tag-bullish">60m站MA60</span>`);
    else if (s.price_vs_ma60_60m === 'below') sigs.push(`<span class="signal-tag tag-bearish">60m跌MA60</span>`);
    // 三大法人
    const fn = s.foreign_net, tn = s.trust_net, dn = s.dealer_net;
    if (fn > 0) sigs.push(`<span class="signal-tag tag-golden">外資+${_fmt(fn)}</span>`);
    if (tn > 0) sigs.push(`<span class="signal-tag tag-golden">投信+${_fmt(tn)}</span>`);
    if (dn > 0) sigs.push(`<span class="signal-tag tag-golden">自營+${_fmt(dn)}</span>`);

    return `<tr>
      <td>
        <div class="td-name">${s.name || '─'}</div>
        <div class="td-symbol">${sym}</div>
      </td>
      <td style="font-family:var(--font-mono);font-weight:600" class="${pctCls}">${price}</td>
      <td class="${pctCls}" style="font-family:var(--font-mono)">${pctStr(s.change_pct)}</td>
      <td>
        <div class="ma-badges">
          ${maBadge(s.price_vs_ma5, '5')}
          ${maBadge(s.price_vs_ma20, '20')}
          ${maBadge(s.price_vs_ma60, '60')}
        </div>
      </td>
      <td>${sigs.length ? `<div class="signal-tags">${sigs.join('')}</div>` : '─'}</td>
      <td style="color:var(--muted);font-size:12px">${s.sector_name || '─'}</td>
      <td>
        <button class="btn btn-sm btn-outline btn-add-to-wl2" data-symbol="${s.symbol}" data-name="${s.name}">
          + 觀察
        </button>
      </td>
    </tr>`;
  }

  // ── 篩選執行 ─────────────────────────────

  async function fetchScreen() {
    const params = Object.entries(filters)
      .filter(([, v]) => v !== null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');

    const tbody = document.getElementById('screener-tbody');
    const countEl = document.getElementById('screener-count');
    const table = document.getElementById('screener-table');
    const empty = document.getElementById('screener-empty');

    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    table.style.display = '';
    empty.style.display = 'none';

    try {
      const stocks = await API.screen(params);
      if (countEl) countEl.textContent = `找到 ${stocks.length} 支符合條件的股票`;

      if (stocks.length === 0) {
        table.style.display = 'none';
        empty.style.display = '';
        return;
      }

      tbody.innerHTML = stocks.map(renderRow).join('');

      // 加入觀察名單
      tbody.querySelectorAll('.btn-add-to-wl2').forEach(btn => {
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
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--muted)">查詢失敗: ${e.message}</td></tr>`;
    }
  }

  function _fmt(n) {
    if (!n && n !== 0) return '─';
    const abs = Math.abs(n);
    if (abs >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return (n / 1000).toFixed(0) + 'K';
    return String(n);
  }

  // ── Chip 切換邏輯 ─────────────────────────

  function initChips(groupEl, filterKey) {
    groupEl.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const val = chip.dataset.value;
        if (filters[filterKey] === val) {
          filters[filterKey] = null;
          chip.classList.remove('active');
        } else {
          groupEl.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
          filters[filterKey] = val;
          chip.classList.add('active');
        }
        fetchScreen();
      });
    });
  }

  // ── 類股下拉選單填充 ─────────────────────

  async function populateSectorSelect() {
    const sel = document.getElementById('screener-sector-select');
    if (!sel) return;
    try {
      const catalog = await API.getSectorsCatalog();
      sel.innerHTML = '<option value="">所有類股</option>' +
        catalog.map(s => `<option value="${s.key}">${s.name}</option>`).join('');
      sel.addEventListener('change', () => {
        filters.sector = sel.value || null;
        fetchScreen();
      });
    } catch (e) {
      // ignore
    }
  }

  function init() {
    initChips(document.getElementById('chips-ma-position'), 'ma_position');
    initChips(document.getElementById('chips-cross'),       'cross');
    initChips(document.getElementById('chips-volume'),      'volume_surge');
    initChips(document.getElementById('chips-alignment'),   'alignment');
    initChips(document.getElementById('chips-ma-return'),   'ma_return');
    initChips(document.getElementById('chips-ma60-60m'),    'ma60_60m');
    initChips(document.getElementById('chips-institutional'),'institutional');

    populateSectorSelect();

    // 初始載入（無篩選條件，顯示全部）
    fetchScreen();

    // 重設按鈕
    document.getElementById('btn-reset-screener')?.addEventListener('click', () => {
      Object.keys(filters).forEach(k => (filters[k] = null));
      document.querySelectorAll('.screener-filters .chip').forEach(c => c.classList.remove('active'));
      const sel = document.getElementById('screener-sector-select');
      if (sel) sel.value = '';
      fetchScreen();
    });

    // 更新三大法人資料按鈕
    document.getElementById('btn-refresh-inst')?.addEventListener('click', async () => {
      const btn = document.getElementById('btn-refresh-inst');
      btn.disabled = true; btn.textContent = '更新中…';
      try {
        await API.post('/api/institutional/refresh');
        showToast('三大法人資料更新中（背景執行）', 'info');
        setTimeout(fetchScreen, 8000);
      } catch(e) {
        showToast('更新失敗: ' + e.message, 'error');
      } finally {
        setTimeout(() => { btn.disabled = false; btn.textContent = '更新法人資料'; }, 5000);
      }
    });
  }

  return { init };
})();
