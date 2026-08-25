(function (global) {
  "use strict";

  const SAFE_KEY = /^[a-z0-9_]+$/;
  const ROOT_PREFIX = "frontend/report/plugins";

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

  function storePayload(payload) {
    const key = `mythicReportPayload.${Date.now()}.${Math.random().toString(36).slice(2)}`;
    global.sessionStorage.setItem(key, JSON.stringify(payload));
    return `session:${key}`;
  }

  async function loadPayload(sourcePath) {
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

  global.MythicReportRuntime = {
    identityOf,
    descriptorUrl,
    loadDescriptor,
    reportUrl,
    overviewUrl,
    detailUrl,
    storePayload,
    loadPayload
  };
})(window);
