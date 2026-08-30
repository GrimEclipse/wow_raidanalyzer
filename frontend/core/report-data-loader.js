(function () {
  const localFiles = new Map();
  const cachedPayloads = new Map();
  const DB_NAME = 'wow-raidanalyzer-cache';
  const DB_VERSION = 1;
  const STORE_NAME = 'analysis-json';
  let databasePromise = null;

  function normalizeSource(source) {
    return String(source || '')
      .replace(/^\.\//, '')
      .replace(/\\/g, '/');
  }

  function localSourcePath(file) {
    const relative = normalizeSource(file.webkitRelativePath || '');
    const dataMarker = relative.lastIndexOf('/data/');
    if (dataMarker >= 0) return relative.slice(dataMarker + 1);
    if (relative.startsWith('data/')) return relative;
    if (/^wcl_.+\.json$/i.test(file.name || '')) return `data/${file.name}`;
    return `local/${file.name}`;
  }

  function parseJsonFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        try {
          resolve(JSON.parse(String(reader.result || '')));
        } catch (error) {
          reject(new Error(`JSON 解析失败：${error.message}`));
        }
      };
      reader.onerror = () => reject(new Error('无法读取所选 JSON 文件。'));
      reader.readAsText(file, 'utf-8');
    });
  }

  function firstFightDate(payload) {
    const fights = payload?.data?.page1_wipeAnalysis;
    return Array.isArray(fights) ? String(fights.find(row => row?.date)?.date || '') : '';
  }

  function safeIdentityPart(value, fallback) {
    const normalized = String(value || '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-');
    return normalized.replace(/^-+|-+$/g, '') || fallback;
  }

  function analysisIdentity(payload, file) {
    const meta = payload?.meta || {};
    const declaredIdentity = String(meta.analysisId || meta.analysisIdentity?.key || '').trim();
    if (declaredIdentity) return declaredIdentity;
    const reports = Array.from(new Set((meta.analyzedReports || []).map(String).filter(Boolean))).sort();
    const version = safeIdentityPart(meta.version, 'unknown-version');
    const raid = safeIdentityPart(meta.raidKey, 'unknown-raid');
    const boss = safeIdentityPart(meta.bossKey, 'unknown-boss');
    const reportKey = safeIdentityPart(reports.join('+'), safeIdentityPart(file?.name, 'local-json'));
    const date = safeIdentityPart(meta.progressDate || firstFightDate(payload), 'unknown-date');
    return `${version}/${raid}/${boss}/${reportKey}/${date}`;
  }

  function cacheSourcePath(identity) {
    return `cache/${identity.split('/').map(encodeURIComponent).join('/')}.json`;
  }

  function cacheLabel(payload, file) {
    const meta = payload?.meta || {};
    const reports = (meta.analyzedReports || []).map(String).filter(Boolean).join('+');
    const date = meta.progressDate || firstFightDate(payload);
    const boss = meta.bossName || meta.bossKey;
    const parts = [boss, reports, date].filter(Boolean);
    return parts.length ? parts.join(' · ') : (file?.name || '已缓存 JSON');
  }

  function openDatabase() {
    if (!window.indexedDB) return Promise.resolve(null);
    if (databasePromise) return databasePromise;
    databasePromise = new Promise((resolve, reject) => {
      const request = window.indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          database.createObjectStore(STORE_NAME, { keyPath: 'path' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('无法打开浏览器 JSON 缓存。'));
    });
    return databasePromise;
  }

  async function runStore(mode, operation) {
    const database = await openDatabase();
    if (!database) return null;
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const store = transaction.objectStore(STORE_NAME);
      let request;
      try {
        request = operation(store);
      } catch (error) {
        reject(error);
        return;
      }
      transaction.oncomplete = () => resolve(request?.result ?? null);
      transaction.onerror = () => reject(transaction.error || request?.error || new Error('浏览器 JSON 缓存操作失败。'));
      transaction.onabort = () => reject(transaction.error || new Error('浏览器 JSON 缓存操作已取消。'));
    });
  }

  function recordToSource(record) {
    return {
      path: record.path,
      name: record.name,
      label: record.label,
      size: Number(record.size || 0),
      mtime: Number(record.mtime || 0),
      cached: true,
      identity: record.identity,
    };
  }

  async function persistJsonFile(file) {
    const payload = await parseJsonFile(file);
    const identity = analysisIdentity(payload, file);
    const path = cacheSourcePath(identity);
    const record = {
      path,
      identity,
      name: file.name,
      label: cacheLabel(payload, file),
      size: Number(file.size || 0),
      mtime: Math.floor(Number(file.lastModified || Date.now()) / 1000),
      cachedAt: Date.now(),
      payload,
    };
    cachedPayloads.set(path, payload);
    try {
      await runStore('readwrite', store => store.put(record));
    } catch (error) {
      console.warn('IndexedDB cache unavailable; keeping JSON for this page only.', error);
    }
    return recordToSource(record);
  }

  async function registerLocalFiles(fileList) {
    const files = Array.from(fileList || []).filter(file => file && /\.json$/i.test(file.name || ''));
    const rows = await Promise.all(files.map(persistJsonFile));
    return rows.sort((a, b) => b.mtime - a.mtime);
  }

  function localSourceFiles() {
    return Array.from(localFiles.entries()).map(([path, file]) => ({
      path,
      name: file.name,
      label: file.name,
      size: Number(file.size || 0),
      mtime: Math.floor(Number(file.lastModified || Date.now()) / 1000),
      local: true,
    }));
  }

  async function cachedSourceFiles() {
    try {
      const rows = await runStore('readonly', store => store.getAll());
      return (rows || []).map(recordToSource).sort((a, b) => b.mtime - a.mtime);
    } catch (error) {
      console.warn('Unable to list cached JSON files.', error);
      return [];
    }
  }

  function lookupLocalFile(source) {
    const key = normalizeSource(source);
    if (localFiles.has(key)) return localFiles.get(key);
    const base = key.split('/').pop();
    for (const [path, file] of localFiles.entries()) {
      if (path.split('/').pop() === base) return file;
    }
    return null;
  }

  async function lookupCachedPayload(source) {
    const key = normalizeSource(source);
    if (cachedPayloads.has(key)) return cachedPayloads.get(key);
    if (!key.startsWith('cache/')) return null;
    try {
      const record = await runStore('readonly', store => store.get(key));
      if (!record?.payload) return null;
      cachedPayloads.set(key, record.payload);
      return record.payload;
    } catch (error) {
      console.warn('Unable to read cached JSON.', error);
      return null;
    }
  }

  async function clearCachedSources() {
    cachedPayloads.clear();
    for (const key of Array.from(localFiles.keys())) {
      if (key.startsWith('cache/')) localFiles.delete(key);
    }
    try {
      await runStore('readwrite', store => store.clear());
    } catch (error) {
      console.warn('Unable to clear cached JSON.', error);
    }
  }

  function chooseLocalJson(source) {
    return new Promise((resolve, reject) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:99999', 'display:grid', 'place-items:center',
        'padding:24px', 'background:rgba(2,6,23,.88)', 'font-family:system-ui,sans-serif',
      ].join(';');
      const panel = document.createElement('div');
      panel.style.cssText = [
        'width:min(520px,100%)', 'padding:24px', 'border:1px solid #334155', 'border-radius:8px',
        'background:#0f172a', 'color:#e2e8f0', 'box-shadow:0 24px 70px rgba(0,0,0,.55)',
      ].join(';');
      panel.innerHTML = `
        <div style="font-size:18px;font-weight:700;margin-bottom:8px">选择复盘 JSON</div>
        <div style="font-size:13px;color:#94a3b8;line-height:1.6;margin-bottom:18px">
          未找到打包内嵌数据，且当前为 <code>file://</code> 打开，浏览器不能自动读取
          <code>${String(source || '')}</code>。请选择同目录中的 JSON 文件。
        </div>
      `;
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,application/json';
      input.style.cssText = 'display:block;width:100%;padding:10px;border:1px solid #475569;border-radius:6px;background:#020617;color:#e2e8f0';
      input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        try {
          const data = await parseJsonFile(file);
          overlay.remove();
          resolve(data);
        } catch (error) {
          reject(error);
          overlay.remove();
        }
      }, { once: true });
      panel.appendChild(input);
      overlay.appendChild(panel);
      document.body.appendChild(overlay);
    });
  }

  function lookupBakedMap(source) {
    const map = window.__WCL_DATA_BY_SOURCE__;
    if (!map || typeof map !== 'object') return null;
    const key = normalizeSource(source);
    if (map[key]) return map[key];
    if (map['./' + key]) return map['./' + key];
    const base = key.split('/').pop();
    if (base && map[base]) return map[base];
    if (base && map['data/' + base]) return map['data/' + base];
    return null;
  }

  function bakedPayload(source) {
    const path = normalizeSource(source);
    if (/verdict/i.test(path) && window.__VERDICT_DATA__) return window.__VERDICT_DATA__;
    const mapped = lookupBakedMap(source);
    if (mapped) return mapped;
    if (window.__WCL_HARDCORE_DATA__) return window.__WCL_HARDCORE_DATA__;
    if (window.__OFFLINE_DATA__) return window.__OFFLINE_DATA__;
    return null;
  }

  function bakedSourceList() {
    const map = window.__WCL_DATA_BY_SOURCE__;
    if (!map || typeof map !== 'object') return [];
    return Object.keys(map).sort();
  }

  function bakedSourceFiles() {
    const files = window.__WCL_DATA_FILES__;
    if (Array.isArray(files)) return files.slice();
    return bakedSourceList().map(path => {
      const name = path.split('/').pop();
      return { path, name, label: name, size: 0, mtime: 0 };
    });
  }

  async function loadJson(source) {
    const localFile = lookupLocalFile(source);
    if (localFile) return parseJsonFile(localFile);
    const cached = await lookupCachedPayload(source);
    if (cached) return cached;
    const baked = bakedPayload(source);
    if (baked) return baked;

    if (window.location.protocol === 'file:') return chooseLocalJson(source);

    const key = normalizeSource(source);
    if (!key || key === 'wcl_hardcore_api.json' || key === 'latest') {
      try {
        const latest = await fetch('/api/data/latest', { cache: 'no-store' });
        if (latest.ok) return latest.json();
      } catch (_) { /* fall through */ }
    }

    const response = await fetch(key.startsWith('http') || key.startsWith('/') ? key : './' + key);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  window.OfflineDataLoader = {
    loadJson,
    bakedPayload,
    bakedSourceList,
    bakedSourceFiles,
    registerLocalFiles,
    localSourceFiles,
    cachedSourceFiles,
    clearCachedSources,
    analysisIdentity,
    normalizeSource,
  };
})();
