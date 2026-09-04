(function (global) {
  "use strict";

  const SAFE_KEY = /^[a-z0-9_]+$/;
  const ROOT_PREFIX = "frontend/report/plugins";
  const TOOLTIP_LAYER = 2147483647;

  function installTooltipLayer() {
    if (!global.document || global.document.getElementById("report-tooltip-layer-style")) return;

    const style = global.document.createElement("style");
    style.id = "report-tooltip-layer-style";
    style.textContent = `
      .wowhead-tooltip,
      .wowhead-tooltip-powered,
      .wowhead-tooltip-screen {
        z-index: ${TOOLTIP_LAYER} !important;
      }
      .report-hover-tooltip {
        position: fixed;
        z-index: ${TOOLTIP_LAYER} !important;
        display: none;
        max-width: min(360px, calc(100vw - 24px));
        padding: 8px 10px;
        border: 1px solid #5f7c82;
        border-radius: 6px;
        background: #050a0df5;
        box-shadow: 0 10px 30px #000c;
        color: #edf3f1;
        font: 12px/1.45 system-ui, "Microsoft YaHei", sans-serif;
        pointer-events: none;
        white-space: normal;
      }
      .report-hover-tooltip.visible { display: block; }
    `;
    global.document.head.appendChild(style);

    const tooltip = global.document.createElement("div");
    tooltip.id = "reportHoverTooltip";
    tooltip.className = "report-hover-tooltip";
    tooltip.setAttribute("role", "tooltip");
    global.document.body.appendChild(tooltip);

    let trigger = null;
    const move = event => {
      if (!trigger) return;
      const gap = 14;
      const bounds = tooltip.getBoundingClientRect();
      const left = Math.min(event.clientX + gap, global.innerWidth - bounds.width - 8);
      const top = Math.min(event.clientY + gap, global.innerHeight - bounds.height - 8);
      tooltip.style.left = `${Math.max(8, left)}px`;
      tooltip.style.top = `${Math.max(8, top)}px`;
    };
    global.document.addEventListener("pointerover", event => {
      const candidate = event.target instanceof Element
        ? event.target.closest("[data-report-tooltip]")
        : null;
      if (!candidate) return;
      trigger = candidate;
      tooltip.textContent = candidate.dataset.reportTooltip || "";
      tooltip.classList.add("visible");
      move(event);
    });
    global.document.addEventListener("pointermove", move);
    global.document.addEventListener("pointerout", event => {
      if (!trigger || (event.relatedTarget instanceof Node && trigger.contains(event.relatedTarget))) return;
      if (event.target instanceof Node && trigger.contains(event.target)) {
        trigger = null;
        tooltip.classList.remove("visible");
      }
    });
    global.addEventListener("blur", () => tooltip.classList.remove("visible"));
    global.addEventListener("scroll", () => tooltip.classList.remove("visible"), true);
  }

  function identityOf(payload) {
    const meta = payload && payload.meta ? payload.meta : {};
    const identity = meta.analysisIdentity || {};
    return {
      version: String(meta.version || identity.version || ""),
      raidKey: String(meta.raidKey || identity.raidKey || ""),
      bossKey: String(meta.bossKey || identity.bossKey || ""),
      bossName: String(meta.bossName || meta.fightName || meta.bossKey || "未知 Boss")
    };
  }

  function assertPluginKey(value, label) {
    if (!SAFE_KEY.test(value)) {
      throw new Error(`${label} 不是合法的插件标识：${value || "空值"}`);
    }
    return value;
  }

  function descriptorUrl(identity) {
    const raidKey = assertPluginKey(identity.raidKey, "raidKey");
    const bossKey = assertPluginKey(identity.bossKey, "bossKey");
    return `${ROOT_PREFIX}/${raidKey}/${bossKey}/plugin.js`;
  }

  async function loadDescriptor(payload) {
    const identity = identityOf(payload);
    global.MythicReportPlugin = null;
    const script = document.createElement("script");
    script.src = descriptorUrl(identity);
    script.async = true;
    await new Promise((resolve, reject) => {
      script.onload = resolve;
      script.onerror = () => reject(new Error(`尚未找到 ${identity.raidKey}/${identity.bossKey} 的前端插件`));
      document.head.appendChild(script);
    });
    const descriptor = global.MythicReportPlugin;
    if (!descriptor) {
      throw new Error(`${identity.raidKey}/${identity.bossKey} 尚未提供前端插件描述`);
    }
    if (descriptor.supported === false) {
      throw new Error(descriptor.disabledReason || `${identity.bossName} 尚未提供 Boss 专属报告页面`);
    }
    if (!descriptor.reportPage) {
      throw new Error(`${identity.bossName} 的前端插件缺少专属 reportPage`);
    }
    return descriptor;
  }

  function appendQuery(page, values) {
    const url = new URL(page, global.document.baseURI);
    Object.entries(values).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    });
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function overviewUrl(sourcePath) {
    return appendQuery("frontend/report/overview.html", { json: sourcePath });
  }

  function detailUrl(descriptor, sourcePath, fightID) {
    const page = descriptor && descriptor.reportPage;
    if (!page) throw new Error("该 Boss 尚未提供专属报告页面");
    return appendQuery(page, { json: sourcePath, fight: fightID });
  }

  function reportUrl(_descriptor, sourcePath) {
    return overviewUrl(sourcePath);
  }

  const LOCAL_DB_NAME = "mythic-analyzer-local";
  const LOCAL_STORE_NAME = "reports";

  function openLocalDatabase() {
    return new Promise((resolve, reject) => {
      if (!global.indexedDB) return reject(new Error("当前浏览器不支持本地报告库。"));
      const request = global.indexedDB.open(LOCAL_DB_NAME, 1);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(LOCAL_STORE_NAME)) {
          database.createObjectStore(LOCAL_STORE_NAME, { keyPath: "key" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("无法打开本地报告库。"));
    });
  }

  function databaseRequest(mode, operation) {
    return openLocalDatabase().then(database => new Promise((resolve, reject) => {
      const transaction = database.transaction(LOCAL_STORE_NAME, mode);
      const store = transaction.objectStore(LOCAL_STORE_NAME);
      let request;
      try { request = operation(store); }
      catch (error) { database.close(); reject(error); return; }
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("本地报告操作失败。"));
      transaction.oncomplete = () => database.close();
      transaction.onerror = () => { database.close(); reject(transaction.error); };
    }));
  }

  async function storePayload(payload, options = {}) {
    const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const identity = identityOf(payload);
    const record = {
      key,
      payload,
      savedAt: Date.now(),
      label: String(options.label || identity.bossName || "本地分析报告"),
      identity,
      approximateBytes: new Blob([JSON.stringify(payload)]).size
    };
    try {
      await databaseRequest("readwrite", store => store.put(record));
      return `idb:${key}`;
    } catch (_) {
      const sessionKey = `mythicReportPayload.${key}`;
      global.sessionStorage.setItem(sessionKey, JSON.stringify(payload));
      return `session:${sessionKey}`;
    }
  }

  async function loadPayload(sourcePath) {
    if (String(sourcePath || "").startsWith("idb:")) {
      const key = String(sourcePath).slice("idb:".length);
      const record = await databaseRequest("readonly", store => store.get(key));
      if (!record?.payload) throw new Error("本地报告已被清除，请重新选择 JSON。");
      return record.payload;
    }
    if (String(sourcePath || "").startsWith("session:")) {
      const key = String(sourcePath).slice("session:".length);
      const value = global.sessionStorage.getItem(key);
      if (!value) throw new Error("临时导入数据已失效，请重新选择 JSON。");
      return JSON.parse(value);
    }
    const response = await global.fetch(sourcePath, { cache: "no-store" });
    if (!response.ok) throw new Error(`读取失败：HTTP ${response.status}`);
    return response.json();
  }

  async function listLocalPayloads() {
    try {
      const rows = await databaseRequest("readonly", store => store.getAll());
      return (rows || []).sort((a, b) => Number(b.savedAt || 0) - Number(a.savedAt || 0)).map(row => ({
        key: row.key,
        sourcePath: `idb:${row.key}`,
        savedAt: row.savedAt,
        label: row.label,
        identity: row.identity,
        approximateBytes: row.approximateBytes || 0
      }));
    } catch (_) {
      return [];
    }
  }

  async function deleteLocalPayload(sourcePath) {
    const key = String(sourcePath || "").replace(/^idb:/, "");
    if (!key) return;
    await databaseRequest("readwrite", store => store.delete(key));
  }

  global.MythicReportRuntime = {
    identityOf,
    descriptorUrl,
    loadDescriptor,
    reportUrl,
    overviewUrl,
    detailUrl,
    storePayload,
    loadPayload,
    listLocalPayloads,
    deleteLocalPayload
  };
  installTooltipLayer();
})(window);
