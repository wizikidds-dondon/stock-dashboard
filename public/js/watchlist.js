/* 觀察名單模組 */
const WatchlistModule = (() => {
  let stocks = [];
  let sortCol = '';
  let sortDir = 1; // 1=asc -1=desc

  // ── 渲染 ─────────────────────────────────

  function maBadge(pos, label) {
    if (!pos) return `<span class="ma-badge ma-na">${label}─</span>`;
    const cls = pos === 'above' ? 'ma-above' : 'ma-below';
    const arr = pos === 'above' ? '↑' : '↓';
    return `<span class="ma-badge ${cls}">${label}${arr}</span>`;
  }

  function signalTags(s) {
    const tags = [];
    if (s.bullish_align)     tags.push(`<span class="signal-tag tag-bullish">多頭排列</span>`);
    if (s.bearish_align)     tags.push(`<span class="signal-tag tag-bearish">空頭排列</span>`);
    if (s.golden_cross_520)  tags.push(`<span class="signal-tag tag-golden">黃金交叉5/20</span>`);
    if (s.death_cross_520)   tags.push(`<span class="signal-tag tag-death">死亡交叉5/20</span>`);
    if (s.golden_cross_2060) tags.push(`<span class="signal-tag tag-golden">黃金交叉20/60</span>`);
    if (s.death_cross_2060)  tags.push(`<span class="signal-tag tag-death">死亡交叉20/60</span>`);
    const vol = s.vol_ratio_5d;
    if (vol >= 2.0)  tags.push(`<span class="signal-tag tag-volume">爆量 ${vol.toFixed(1)}x</span>`);
    else if (vol >= 1.5) tags.push(`<span class="signal-tag tag-volume">放量 ${vol.toFixed(1)}x</span>`);
    return tags.length ? `<div class="signal-tags">${tags.join('')}</div>` : '─';
  }

  function priceClass(pct) {
    if (!pct && pct !== 0) return 'price-flat';
    return pct > 0 ? 'price-up' : pct < 0 ? 'price-down' : 'price-flat';
  }

  function renderRow(s) {
    const sym = (s.symbol || '').replace('.TW', '');
    const priceCls = priceClass(s.change_pct);
    const pct = s.change_pct != null
      ? `${s.change_pct > 0 ? '+' : ''}${s.change_pct.toFixed(2)}%`
      : '─';
    const chg = s.change != null
      ? `${s.change > 0 ? '+' : ''}${s.change.toFixed(2)}`
      : '';
    const price = s.close != null ? s.close.toFixed(2) : '─';
    const vol = s.volume != null ? (s.volume / 1000).toFixed(0) + 'K' : '─';
    const volRatio = s.vol_ratio_5d != null ? `${s.vol_ratio_5d.toFixed(1)}x` : '─';

    return `<tr data-symbol="${s.symbol}">
      <td>
        <div class="td-name">${s.name || '─'}</div>
        <div class="td-symbol">${sym}</div>
      </td>
      <td class="${priceCls}" style="font-family:var(--font-mono);font-weight:600">${price}</td>
      <td class="${priceCls}">
        <div class="change-cell">${pct}</div>
        <div style="font-size:11px;color:var(--muted)">${chg}</div>
      </td>
      <td style="color:var(--muted);font-family:var(--font-mono)">${vol}</td>
      <td style="color:var(--muted)">${volRatio}</td>
      <td>
        <div class="ma-badges">
          ${maBadge(s.price_vs_ma5, '5')}
          ${maBadge(s.price_vs_ma20, '20')}
          ${maBadge(s.price_vs_ma60, '60')}
        </div>
      </td>
      <td>${signalTags(s)}</td>
      <td style="color:var(--muted);font-size:11px">${s.sector_name || '─'}</td>
      <td>
        <button class="btn btn-sm btn-outline btn-refresh-sym" data-symbol="${s.symbol}" title="刷新">↻</button>
        <button class="btn btn-sm btn-danger btn-remove" data-symbol="${s.symbol}" style="margin-left:4px">✕</button>
      </td>
    </tr>`;
  }

  function render(data) {
    const tbody = document.querySelector('#watchlist-tbody');
    const empty = document.getElementById('watchlist-empty');
    const table = document.getElementById('watchlist-table');
    if (!tbody) return;

    if (!data || data.length === 0) {
      table.style.display = 'none';
      empty.style.display = '';
      return;
    }
    table.style.display = '';
    empty.style.display = 'none';
    tbody.innerHTML = data.map(renderRow).join('');

    // 刪除按鈕
    tbody.querySelectorAll('.btn-remove').forEach(btn => {
      btn.addEventListener('click', () => removeStock(btn.dataset.symbol));
    });
    // 單支刷新
    tbody.querySelectorAll('.btn-refresh-sym').forEach(btn => {
      btn.addEventListener('click', () => refreshSymbol(btn.dataset.symbol));
    });
  }

  // ── 排序 ─────────────────────────────────

  function applySortAndRender() {
    if (!sortCol) { render(stocks); return; }
    const sorted = [...stocks].sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol];
      if (av == null) av = sortDir > 0 ? -Infinity : Infinity;
      if (bv == null) bv = sortDir > 0 ? -Infinity : Infinity;
      return av > bv ? sortDir : av < bv ? -sortDir : 0;
    });
    render(sorted);
  }

  // ── 資料載入 ─────────────────────────────

  async function load() {
    const table = document.getElementById('watchlist-table');
    const loading = document.getElementById('watchlist-loading');
    const empty = document.getElementById('watchlist-empty');
    if (loading) loading.style.display = '';
    if (table)   table.style.display = 'none';
    if (empty)   empty.style.display = 'none';

    try {
      stocks = await API.getWatchlist();
    } catch (e) {
      showToast('載入觀察名單失敗: ' + e.message, 'error');
      stocks = [];
    }
    if (loading) loading.style.display = 'none';
    applySortAndRender();
  }

  async function removeStock(symbol) {
    if (!confirm(`確定從觀察名單移除 ${symbol}？`)) return;
    try {
      await API.removeWatchlist(symbol);
      showToast(`已移除 ${symbol}`, 'success');
      load();
    } catch (e) {
      showToast('移除失敗: ' + e.message, 'error');
    }
  }

  async function refreshSymbol(symbol) {
    showToast(`正在刷新 ${symbol}…`, 'info');
    try {
      await API.refreshSymbol(symbol);
      setTimeout(load, 5000);
    } catch (e) {
      showToast('刷新失敗: ' + e.message, 'error');
    }
  }

  // ── 初始化 ───────────────────────────────

  function init() {
    // 排序欄位
    document.querySelectorAll('#watchlist-table thead th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (sortCol === col) sortDir *= -1;
        else { sortCol = col; sortDir = -1; }
        document.querySelectorAll('#watchlist-table thead th').forEach(h => {
          h.classList.remove('sort-asc', 'sort-desc');
        });
        th.classList.add(sortDir > 0 ? 'sort-asc' : 'sort-desc');
        applySortAndRender();
      });
    });

    // 新增按鈕
    document.getElementById('btn-add-stock')?.addEventListener('click', () => {
      openAddModal();
    });

    // 自動刷新（5分鐘）
    setInterval(load, 5 * 60 * 1000);
  }

  return { init, load };
})();


/* 新增股票 Modal */
function openAddModal() {
  document.getElementById('modal-add-stock').classList.add('open');
  document.getElementById('add-symbol-input').focus();
}

function closeAddModal() {
  document.getElementById('modal-add-stock').classList.remove('open');
  document.getElementById('add-symbol-input').value = '';
  document.getElementById('add-name-input').value = '';
}

async function submitAddStock() {
  const symbolRaw = document.getElementById('add-symbol-input').value.trim();
  const name = document.getElementById('add-name-input').value.trim();
  const sectorKey = document.getElementById('add-sector-select').value;
  if (!symbolRaw) { showToast('請輸入股票代碼', 'error'); return; }

  const btn = document.getElementById('btn-add-confirm');
  btn.disabled = true;
  btn.textContent = '加入中…';

  try {
    await API.addWatchlist({ symbol: symbolRaw, name, sector_key: sectorKey });
    showToast(`已加入 ${symbolRaw}`, 'success');
    closeAddModal();
    WatchlistModule.load();
  } catch (e) {
    showToast('加入失敗: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '加入';
  }
}
