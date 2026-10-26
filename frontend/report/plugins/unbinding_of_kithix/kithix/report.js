(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const state = { payload: null, pulls: [], pull: 0, tab: "survival" };
  const current = () => state.pulls[state.pull];
  const boss = () => current()?.kithix || {};
  const spell = (id, name) => {
    const spellID = Number(id || 0), label = name || (spellID ? `法术 ${spellID}` : "—");
    return !spellID || [1, 3, 4, 5, 6, 7, 8].includes(spellID)
      ? esc(label)
      : `<a class="spell" href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;spell=${spellID}" target="_blank" rel="noreferrer">${esc(label)}</a>`;
  };
  const refreshTooltips = () => {
    if (window.WH?.Tooltips?.refreshLinks) window.WH.Tooltips.refreshLinks();
    else if (window.$WowheadPower?.refreshLinks) window.$WowheadPower.refreshLinks();
  };
  const player = row => `<span class="player" style="color:${esc(row?.classColor || row?.triggerClassColor || "#e5e7eb")}">${esc(row?.player || row?.triggerPlayer || row?.name || "—")}</span>`;
  const yes = flag => flag ? '<span class="badge good">是</span>' : '<span class="badge bad">否</span>';
  const clock = ms => { const seconds = Math.max(0, Number(ms) || 0) / 1000; return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${(seconds % 60).toFixed(1).padStart(4, "0")}`; };
  const num = value => Number(value || 0).toLocaleString("zh-CN");
  function table(headers, rows) {
    if (!rows.length) return '<div class="empty">没有记录。</div>';
    return `<div class="table-wrap"><table><thead><tr>${headers.map(header => `<th>${header}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function renderStats() {
    const pull = current(), data = boss(), checks = data.checks || {};
    if (!pull) { $("stats").innerHTML = ""; return; }
    const cards = [
      ["时长", pull.duration],
      ["结果", pull.isKill ? "击杀" : `${Number(pull.bossPercentage || 0).toFixed(1)}%`],
      ["难度", pull.difficultyName || "—"],
      ["甲虫触发", checks.beetleTriggers ?? (data.beetles || []).filter(row => row.triggered).length],
      ["虚空之痕命中", checks.voidscarHits ?? 0],
      ["熄灭漏球", checks.extinguishMisses ?? 0],
      ["卵超时", checks.eggsMissed ?? 0],
    ];
    $("stats").innerHTML = cards.map(([label, value]) => `<article class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></article>`).join("");
    $("title").textContent = state.payload?.meta?.bossName || "基希克斯";
    $("meta").textContent = `${pull.date || ""} ${pull.startClock || ""} · ${pull.difficultyName || ""} · Fight ${pull.fightID}`;
    $("wclLink").href = pull.wclDeepLink || "#";
  }
  function renderTabs() {
    const defs = state.payload?.meta?.tabDefinitions || [{ key: "survival", label: "死亡与战复" }];
    if (!defs.some(row => row.key === state.tab)) state.tab = defs[0].key;
    $("tabs").innerHTML = defs.map(row => `<button type="button" data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join("");
    document.querySelectorAll("[data-tab]").forEach(button => { button.onclick = () => { state.tab = button.dataset.tab; render(); }; });
  }
  function renderSurvival() {
    const survival = current()?.survival || {};
    return `<section class="panel"><h2>死亡与战复</h2><p class="hint">死亡 ${survival.deathCount ?? 0}，战复 ${survival.combatResCount ?? 0}，结束时存活 ${survival.survivorCount ?? 0}。</p>${table(["时间", "玩家", "事件", "技能"], (survival.timeline || []).map(row => [esc(row.time), player(row), row.kind === "death" ? '<span class="badge bad">死亡</span>' : '<span class="badge good">战复</span>', spell(row.abilityID, row.ability)]))}</section>`;
  }
  function renderP1() {
    const data = boss();
    const beetles = data.beetles || [];
    const voidHits = data.voidscarHits || [];
    const extinguishes = data.extinguishes || [];
    const eggDamage = data.eggDamage || [];
    const beetleRows = beetles.map((row, index) => [
      `#${index + 1}`,
      clock(row.spawnTimeMs),
      row.explodeTimeMs == null ? "—" : clock(row.explodeTimeMs),
      row.triggered ? player({ player: row.triggerPlayer, classColor: row.triggerClassColor }) : '<span class="badge warn">超时自爆</span>',
      row.triggered ? '<span class="badge bad">触碰爆炸</span>' : (row.explodeTimeMs == null ? "—" : '<span class="badge warn">超时</span>'),
    ]);
    const voidRows = voidHits.map(row => [player(row), row.hits, num(row.damage)]);
    const extinguishRows = extinguishes.map(row => [
      esc(row.time),
      spell(1304424, "熄灭"),
      row.soakedCount ?? 0,
      row.missedCount ?? 0,
      (row.missedPlayers || []).map(player).join("、") || "—",
    ]);
    const eggSections = eggDamage.length
      ? eggDamage.map((egg, index) => `<h3>缚脑者之卵 #${index + 1}（超时孵化，${clock(egg.spawnTimeMs)}）</h3><p class="hint">总承伤 ${num(egg.totalDamage)}。仅超时孵化的卵展开明细。</p>${table(["玩家", "命中", "伤害"], (egg.damageByPlayer || []).map(row => [player(row), row.hits, num(row.damage)]))}`).join("")
      : `<h3>缚脑者之卵</h3><div class="empty">没有超时孵化的卵，无需查看承伤明细。</div>`;
    const barrierRows = (data.barriers || []).map(row => [
      `#${row.index}`,
      clock(row.startTimeMs),
      clock(row.endTimeMs),
      `${row.startRadiusYards} → ${row.endRadiusYards} 码`,
      esc(row.note || ""),
    ]);
    return `<section class="panel"><h2>第一阶段</h2><p class="hint">${esc(data.evidenceNote || "")}</p>
      <h3>自爆甲虫触发</h3>${table(["#", "出现", "爆炸", "触发玩家", "结果"], beetleRows)}
      <h3>虚空之痕命中</h3><p class="hint">地板虚空圈（${spell(1304950, "虚空之痕")}）对各玩家的命中次数与伤害。</p>${table(["玩家", "命中次数", "伤害"], voidRows)}
      <h3>熄灭与圣光之拥</h3><p class="hint">每次 Boss 熄灭时，仍存活却没有 ${spell(1304526, "圣光之拥")} 的玩家记为漏球。</p>${table(["时间", "技能", "吃到", "漏球", "漏球玩家"], extinguishRows)}
      ${eggSections}
      <h3>莉亚德琳 · 神圣光辉屏障</h3><p class="hint">Boss <strong>读完</strong> ${spell(1302951, "窒息黑暗")} 后，莉亚德琳撑起 40 码 ${spell(1303169, "神圣光辉")} 屏障，并以每秒 0.5 码收缩。待莉亚德琳能量到达 100，她会令 Boss 昏迷数秒。场地会被持续压缩，必须赶在被压死前把 Boss 打到 25%，让其读 ${spell(1301479, "八重蚀日")} 转入第二阶段。</p>${table(["次数", "开始", "结束", "半径", "说明"], barrierRows)}
      <h3>窒息黑暗与蚀日碎片</h3>${table(["开始", "结束", "虚空之痕", "挡住碎片", "辉光消逝"], (data.darkness || []).map(row => [clock(row.startTimeMs), clock(row.endTimeMs), row.scarCount ?? 0, row.soakedCount ?? 0, row.leaked ? '<span class="badge bad">碰到莉亚德琳</span>' : '<span class="badge good">未碰到</span>']))}
      <h3>深渊攫取</h3>${table(["玩家", "获得", "移除", "8 秒内"], (data.grasps || []).map(row => [player(row), esc(row.applyTime), esc(row.removeTime || "—"), yes(row.cleared)]))}</section>`;
  }
  function renderP2() {
    const data = boss();
    const axis = data.nullAxis || {};
    const volleys = data.nullVolleys || [];
    const eightfold = data.eightfold || [];
    return `<section class="panel"><h2>第二阶段</h2>
      <p class="hint">转阶段读条是 ${spell(1301479, "八重蚀日")}，不是笼统的「施法」。${esc(axis.note || "")}</p>
      <h3>八重蚀日</h3>${table(["开始", "结束", "技能"], eightfold.map(row => [clock(row.startTimeMs), clock(row.timeMs), spell(row.spellID, row.spellName || "八重蚀日")]))}
      <h3>虚无之门与十二向飞球</h3>
      <p class="hint">点名玩家在脚下放下虚无之门；buff 结束时，该玩家与场上每一扇仍在的门，都会沿基准线每 30° 射出 12 个球（约 8 码/秒）。</p>
      ${table(["玩家", "落门", "后续开火", "清除"], (data.gates || []).map(row => [player(row), clock(row.placeTimeMs ?? row.dropTimeMs), (row.fireTimesMs || []).map(clock).join("、") || "—", row.clearedTimeMs == null ? '<span class="badge bad">仍在</span>' : clock(row.clearedTimeMs)]))}
      ${table(["发射", "来源", "玩家 / 门", "清除"], volleys.map(row => [clock(row.launchTimeMs), row.source === "gate" ? "虚无之门" : "点名玩家", player(row), row.clearedTimeMs == null ? "飞出" : clock(row.clearedTimeMs)]))}
      <h3>湮消清场</h3>
      <p class="hint">${spell(1318467, "湮消")} debuff 移除时，会清掉范围内正在飞行的球与虚无之门；爆炸复稳同样生效。</p>
      ${table(["玩家", "获得", "移除", "已清场"], (data.negations || []).map(row => [player(row), esc(row.applyTime), esc(row.removeTime || "—"), yes(row.restabilized)]))}
      <h3>光耀恩典</h3><p class="hint">只核对第二阶段开始时仍存活的玩家是否获得光耀恩典 debuff。</p>${table(["玩家", "光耀恩典"], (data.finalLights || []).map(row => [player(row), yes(row.radiantGrace)]))}</section>`;
  }
  function renderContent() {
    $("content").querySelectorAll(".mw").forEach(host => host._workbench?.destroy());
    const views = { survival: renderSurvival, p1: renderP1, p2: renderP2, replay: () => '<div id="kithixReplay"></div>' };
    $("content").innerHTML = (views[state.tab] || renderSurvival)();
    if (state.tab === "replay" && window.KithixReplay) window.KithixReplay.mount($("kithixReplay"), boss(), current()?.durationMs);
    refreshTooltips();
  }
  function render() { renderStats(); renderTabs(); renderContent(); }
  function load(payload) {
    state.payload = payload;
    state.pulls = [...(payload.data?.page1_wipeAnalysis || [])];
    const fight = Number(new URLSearchParams(location.search).get("fight"));
    const index = state.pulls.findIndex(row => Number(row.fightID) === fight);
    state.pull = index >= 0 ? index : 0;
    state.tab = new URLSearchParams(location.search).get("tab") || "replay";
    $("pullSelect").innerHTML = state.pulls.map((row, rowIndex) => `<option value="${rowIndex}">Fight ${row.fightID}，${esc(row.difficultyName || "")}，${row.isKill ? "KILL" : `${Number(row.bossPercentage).toFixed(1)}%`}</option>`).join("");
    $("pullSelect").value = String(state.pull);
    $("error").textContent = state.pulls.length ? "" : "分析结果中没有基希克斯战斗。";
    render();
  }
  $("pullSelect").onchange = event => { state.pull = Number(event.target.value); render(); };
  $("fileInput").onchange = async event => { try { load(await window.MythicReportRuntime.readLocalFile(event.target.files[0])); } catch (error) { $("error").textContent = error.message; } };
  const path = new URLSearchParams(location.search).get("json");
  if (path) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(path)}`;
  if (path) window.MythicReportRuntime.loadPayload(path).then(load).catch(error => { $("error").textContent = error.message; });
  else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
})();
