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
    if (
      descriptor.supported === false
      || descriptor.renderer === "generic"
      || String(descriptor.reportPage || "").endsWith("/generic.html")
    ) {
      throw new Error(descriptor.disabledReason || `${identity.bossName} 尚未提供 Boss 专属报告页面`);
    }
    if (!descriptor.reportPage) {
      throw new Error(`${identity.bossName} 的前端插件缺少专属 reportPage`);
    }
    return descriptor;
  }

  function reportUrl(descriptor, sourcePath) {
    const page = descriptor && descriptor.reportPage;
    if (!page) throw new Error("该 Boss 尚未提供专属报告页面");
    if (!sourcePath) return page;
    const separator = page.includes("?") ? "&" : "?";
    return `${page}${separator}json=${encodeURIComponent(sourcePath)}`;
  }

  global.MythicReportRuntime = {
    identityOf,
    descriptorUrl,
    loadDescriptor,
    reportUrl
  };
})(window);
