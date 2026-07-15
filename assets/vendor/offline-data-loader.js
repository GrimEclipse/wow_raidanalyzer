(function () {
  const localFiles = new Map();

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

  function registerLocalFiles(fileList) {
    const rows = [];
    Array.from(fileList || []).forEach(file => {
      if (!file || !/\.json$/i.test(file.name || '')) return;
      const path = localSourcePath(file);
      localFiles.set(path, file);
      rows.push({
        path,
        name: file.name,
        label: file.name,
        size: Number(file.size || 0),
        mtime: Math.floor(Number(file.lastModified || Date.now()) / 1000),
        local: true,
      });
    });
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

  function lookupLocalFile(source) {
    const key = normalizeSource(source);
    if (localFiles.has(key)) return localFiles.get(key);
    const base = key.split('/').pop();
    for (const [path, file] of localFiles.entries()) {
      if (path.split('/').pop() === base) return file;
    }
    return null;
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
    normalizeSource,
  };
})();
