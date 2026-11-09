/* Admin-only Git tag update notice. The server enforces all update checks. */
(() => {
  const notice = document.getElementById('appUpdateNotice');
  if (!notice) return;
  const label = document.getElementById('appUpdateText');
  const button = document.getElementById('appUpdateButton');
  let latest = null;

  async function check() {
    const response = await fetch('/api/system/update', {cache: 'no-store'});
    if (!response.ok) return;
    const state = await response.json();
    notice.hidden = !state.updateAvailable;
    if (!state.updateAvailable) return;
    latest = state.latestVersion;
    button.disabled = !state.canApply;
    label.textContent = state.blocker
      ? `GitHub 已发布 v${latest}。${state.blocker}`
      : state.activeJobs
        ? `GitHub 已发布 v${latest}。请等待 ${state.activeJobs} 个分析任务结束。`
        : `GitHub 已发布 v${latest}。当前版本 v${state.currentVersion}。`;
  }

  async function waitForRestart() {
    for (let attempt = 0; attempt < 60; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      try {
        const response = await fetch('/api/system/update', {cache: 'no-store'});
        if (!response.ok) continue;
        const state = await response.json();
        if (state.currentVersion === latest) { location.reload(); return; }
      } catch (_) { /* Service is restarting. */ }
    }
    label.textContent = '更新尚未完成，请查看服务器 data/app_update.log。';
  }

  button.addEventListener('click', async () => {
    button.disabled = true;
    label.textContent = '正在启动更新，服务将短暂重启。';
    try {
      const response = await fetch('/api/system/update', {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      waitForRestart();
    } catch (error) {
      label.textContent = error.message;
      check().catch(() => {});
    }
  });
  check().catch(() => {});
  setInterval(() => check().catch(() => {}), 15 * 60 * 1000);
})();
