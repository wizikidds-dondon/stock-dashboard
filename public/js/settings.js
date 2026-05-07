/* 設定模組 */
const SettingsModule = (() => {

  async function load() {
    try {
      const settings = await API.getSettings();
      const tokenMasked = settings.telegram_token_masked || '';
      const chatId = settings.telegram_chat_id || '';
      const enabled = settings.report_enabled !== '0' && settings.report_enabled !== 'false';
      const time = settings.report_time || '14:35';

      const tokenEl = document.getElementById('tg-token-input');
      const chatEl  = document.getElementById('tg-chat-id-input');
      const timeEl  = document.getElementById('tg-report-time');
      const toggleEl= document.getElementById('tg-enabled-toggle');

      if (tokenEl && tokenMasked) tokenEl.placeholder = `目前已設定 (${tokenMasked})`;
      if (chatEl)  chatEl.value = chatId;
      if (timeEl)  timeEl.value = time;
      if (toggleEl) toggleEl.checked = enabled;
    } catch (e) {
      showToast('載入設定失敗: ' + e.message, 'error');
    }

    loadReportLog();
  }

  async function save() {
    const tokenRaw = document.getElementById('tg-token-input')?.value.trim();
    const chatId   = document.getElementById('tg-chat-id-input')?.value.trim();
    const time     = document.getElementById('tg-report-time')?.value || '14:35';
    const enabled  = document.getElementById('tg-enabled-toggle')?.checked ? 'true' : 'false';

    const body = { telegram_chat_id: chatId, report_time: time, report_enabled: enabled };
    if (tokenRaw) body.telegram_token = tokenRaw;  // 僅在填寫時更新 token

    try {
      await API.saveSettings(body);
      showToast('設定已儲存', 'success');
      if (tokenRaw) {
        document.getElementById('tg-token-input').value = '';
        document.getElementById('tg-token-input').placeholder = '目前已設定 (已更新)';
      }
    } catch (e) {
      showToast('儲存失敗: ' + e.message, 'error');
    }
  }

  async function testTelegram() {
    const btn = document.getElementById('btn-test-tg');
    btn.disabled = true;
    btn.textContent = '發送中…';
    try {
      await API.testTelegram();
      showToast('測試訊息發送成功！', 'success');
    } catch (e) {
      showToast('發送失敗: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '傳送測試訊息';
    }
  }

  async function sendReport() {
    const btn = document.getElementById('btn-send-report');
    btn.disabled = true;
    btn.textContent = '發送中…';
    try {
      const res = await API.sendReport();
      showToast(`日報發送成功（${res.length} 字元）`, 'success');
      loadReportLog();
    } catch (e) {
      showToast('發送失敗: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '立即發送日報';
    }
  }

  async function previewReport() {
    const area = document.getElementById('report-preview-area');
    if (!area) return;
    area.textContent = '產生中…';
    try {
      const res = await API.previewReport();
      // 移除 HTML 標籤顯示純文字預覽
      area.textContent = res.report.replace(/<[^>]+>/g, '');
    } catch (e) {
      area.textContent = '預覽失敗: ' + e.message;
    }
  }

  async function loadReportLog() {
    const list = document.getElementById('report-log-list');
    if (!list) return;
    try {
      const logs = await API.getReportLog();
      if (logs.length === 0) {
        list.innerHTML = '<li style="color:var(--muted);padding:8px 0;font-size:12px">尚無發送記錄</li>';
        return;
      }
      list.innerHTML = logs.map(log => {
        const statusCls = log.status === 'ok' ? 'log-status-ok' : 'log-status-error';
        const statusTxt = log.status === 'ok' ? '✓ 成功' : '✕ 失敗';
        const time = log.sent_at ? log.sent_at.slice(0, 16).replace('T', ' ') : '';
        return `<li class="report-log-item">
          <span class="${statusCls}">${statusTxt}</span>
          <span class="log-time">${time}</span>
          <span class="log-msg">${log.message || ''}</span>
        </li>`;
      }).join('');
    } catch (e) {
      list.innerHTML = `<li style="color:var(--muted)">載入失敗</li>`;
    }
  }

  function init() {
    document.getElementById('btn-save-settings')?.addEventListener('click', save);
    document.getElementById('btn-test-tg')?.addEventListener('click', testTelegram);
    document.getElementById('btn-send-report')?.addEventListener('click', sendReport);
    document.getElementById('btn-preview-report')?.addEventListener('click', previewReport);
  }

  return { init, load };
})();
