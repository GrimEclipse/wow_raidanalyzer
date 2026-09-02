(function () {
  "use strict";

  const state = { payload: null, pulls: [], pull: 0, tab: "survival" };
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const num = value => Number(value || 0).toLocaleString("zh-CN");
  const current = () => state.pulls[state.pull] || null;
  const boss = () => current()?.ulatek || {};
  const player = row => `<span class="player" style="color:${row?.classColor || "#fff"}">${esc(row?.player || row?.name || "—")}</span>`;
  const players = rows => (rows || []).map(player).join("、") || "—";
  const spell = (id, name) => { const spellID = Number(id || 0), label = name || (spellID ? `法术 ${spellID}` : "—"); return !spellID || [1, 3, 4, 5, 6, 7, 8].includes(spellID) ? esc(label) : `<a href="https://www.wowhead.com/cn/spell=${spellID}" data-wowhead="domain=cn&amp;spell=${spellID}" target="_blank" rel="noreferrer">${esc(label)}</a>`; };
  const badge = (text, tone = "") => `<span class="badge ${tone}">${esc(text)}</span>`;
  const table = (headers, rows) => !rows?.length ? '<div class="empty">没有对应记录。</div>' : `<table><thead><tr>${headers.map(item => `<th>${esc(item)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell ?? "—"}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const metric = (label, value) => `<div class="summary-item"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
  const ordinal = index => ({1:"第一次",2:"第二次",3:"第三次"}[Number(index)] || `第 ${Number(index) || "—"} 次`);
  const refreshTooltips = () => window.WH?.Tooltips?.refreshLinks ? window.WH.Tooltips.refreshLinks() : window.$WowheadPower?.refreshLinks?.();

  function renderStats() {
    const pull = current(), survival = pull?.survival || {};
    $("title").textContent = `乌拉特克 · Fight ${pull?.fightID || "-"}`;
    $("meta").textContent = `${pull?.difficultyName || "未知难度"} · ${pull?.isKill ? "击杀" : `Boss 剩余 ${Number(pull?.bossPercentage || 0).toFixed(2)}%`} · ${pull?.date || ""} ${pull?.startClock || ""}`;
    $("wclLink").href = pull?.wclDeepLink || "#";
    const rows = [["战斗时长", pull?.duration || "—"], ["结果", pull?.isKill ? "KILL" : `${Number(pull?.bossPercentage || 0).toFixed(2)}%`], ["难度", pull?.difficultyName || "未知"], ["阵亡", survival.deathCount || 0], ["战复", survival.combatResCount || 0], ["结束存活", `${survival.survivorCount || 0}/${survival.rosterCount || 0}`]];
    $("stats").innerHTML = rows.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  }

  function renderTabs() {
    const definitions = state.payload?.meta?.tabDefinitions || [{key:"survival", label:"全场存活情况"}];
    if (!definitions.some(row => row.key === state.tab)) state.tab = definitions[0].key;
    $("tabs").innerHTML = definitions.map(row => `<button data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join("");
    document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => { state.tab = button.dataset.tab; renderTabs(); renderContent(); });
  }

  function renderSurvival() {
    const survival = current()?.survival || {};
    return `<section class="panel"><h2>死亡原因 / 战复时间线</h2><p class="muted">未记录致死技能视为跌落；死亡技能可悬停查看中文 tooltip。</p>${table(["时间","类型","玩家","原因 / 技能"], (survival.timeline || []).map(event => [esc(event.time), event.kind === "combat_res" ? badge("战复", "good") : badge("死亡", "bad"), player(event), event.kind === "combat_res" ? `${player({player:event.source,classColor:event.sourceClassColor})} 使用 ${spell(event.abilityID,event.ability)}` : event.deathCause === "fall" ? "跌落" : spell(event.abilityID,event.ability)]))}</section>`;
  }

  function renderWaves() {
    const data = boss().wavesAndEggs || {};
    return `<section class="summary-strip">${metric("中腐蚀浪潮", `${data.hitCount || 0} 次`)}${metric("带蛋中波", `${data.eggCarrierHitCount || 0} 次`)}${metric("提前孵化", `${data.earlyHatchCount || 0} 次`)}${metric("P1 / P3 搬蛋", `${(data.carries || []).length} 人次`)}</section><section class="panel"><h2>${spell(data.spellID || 1292403,"腐蚀浪潮")}命中</h2>${table(["时间","阶段","玩家","带蛋","提前孵化","伤害"], (data.hits || []).map(row => [esc(row.time), esc(row.phase), player(row), row.eggCarrier ? badge("携带蛇卵", "bad") : "—", row.earlyHatchConfirmed ? badge("已确认", "bad") : "—", num(row.amount)]))}</section><section class="panel"><h2>${spell(data.eggAuraID || 1295360,"恶性甲壳")}携带区间（P1 / P3）</h2>${table(["阶段","玩家","携带时间","持续","中波","提前孵化"], (data.carries || []).map(row => [esc(row.phase), player(row), `${esc(row.startTime)}–${esc(row.endTime)}`, `${row.durationSec} 秒`, row.waveHitCount || 0, row.earlyHatchCount || 0]))}</section>`;
  }

  function renderHeart() {
    const data = boss().rage || {};
    const rounds = data.rounds || [];
    return `<section class="summary-strip">${metric("被缚之怒", `${rounds.length} 轮`)}${metric("易伤期间死亡", `${data.totalDeathCount || 0} 人次`)}${metric("落石命中", `${rounds.reduce((sum,row)=>sum+(row.fallingDebrisHitCount||0),0)} 次`)}${metric("烈毒之心总伤害", num(rounds.reduce((sum,row)=>sum+(row.heartDamage||0),0)))}</section><div class="rage-rounds">${rounds.map(row => `<article class="card round-card ${row.deathCount || row.fallingDebrisHitCount ? "bad" : "good"}"><h3>${spell(1286860,`${ordinal(row.index)}被缚之怒`)} <span class="muted">${esc(row.time)}–${esc(row.endTime)}</span> ${badge(`${row.durationSec} 秒`)} ${row.deathCount ? badge(`死亡 ${row.deathCount}`,"bad") : badge("无人死亡","good")}</h3><h4>${spell(1299526,"烈毒之心")} · 总伤害 ${num(row.heartDamage)}</h4><div class="rage-damage-table">${table(["玩家","伤害"], (row.heartDamageByPlayer || []).map(item => [player(item),num(item.damage)]))}</div><h4>${spell(1286885,"落石")} · ${row.fallingDebrisHitCount || 0} 次 / ${num(row.fallingDebrisDamage)} 伤害</h4>${table(["时间","玩家","伤害"], (row.fallingDebrisHits || []).map(item => [esc(item.time),player(item),num(item.amount)]))}<h4>易伤期间死亡</h4>${table(["时间","玩家","致死技能"], (row.deaths || []).map(item => [esc(item.time),player(item),spell(item.abilityID,item.ability)]))}</article>`).join("") || '<div class="empty">本场没有记录到被缚之怒窗口。</div>'}</div>`;
  }

  function renderFangs() {
    const data = boss().fangs || {};
    return `<section class="summary-strip">${metric("点名人数", `${data.rounds?.[0]?.targetCount || 0} 人`)}${metric("超过上限", `${data.wrongBreakCount || 0} 人`)}${metric("凋萎静脉最高", `${data.maxBlightStack || 0} 层`)}${metric("安全上限", `${data.safeStack || 2} 层`)}</section><div class="cards">${(data.rounds || []).map(round => `<article class="card round-card ${round.wrongBreakCount ? "bad" : "good"}"><h3>${spell(1311611,"攫取毒牙")} · ${esc(round.time)} ${badge(`点名 ${round.targetCount || (round.targets || []).length} 人`)} ${round.wrongBreakCount ? badge(`超过上限 ${round.wrongBreakCount} 人`,"bad") : badge("按批拉断","good")}</h3><p><strong>点名：</strong>${players(round.targets)}</p>${table(["拉断时间","玩家","持有时长","凋萎静脉变化","判定"], (round.breaks || []).map(row => [esc(row.time),player(row),`${row.heldSec} 秒`,row.evidenceMissing?badge("未取得叠层证据"): `${row.fromStack} → ${row.toStack} 层`,row.wrong?badge("超过上限","bad"):badge("正常","good")]))}${(round.overLimitPlayers || []).length ? `<p><strong>超过上限的拉断者：</strong>${players(round.overLimitPlayers)}</p>` : ""}${(round.unresolved || []).length ? `<p><strong>未记录移除：</strong>${players(round.unresolved)}</p>` : ""}</article>`).join("") || '<div class="empty">本场没有攫取毒牙记录。</div>'}</div>`;
  }

  function defensiveUses(row) {
    const personal = (row.personalDefensives || []).map(item => `${spell(item.spellID,item.name)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    const consumables = (row.consumables || []).map(item => `${spell(item.spellID,item.spellName)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    return `<span class="flow-status">${personal.length ? `<span class="yes">死亡前 15 秒个人减伤：${personal.join("、")}</span>` : '<span class="no">死亡前 15 秒未记录个人减伤施放</span>'}${row.usedHealthstone ? '<span class="yes">治疗石</span>' : '<span class="no">死亡前 20 秒未用治疗石</span>'}${row.usedHealingPotion ? '<span class="yes">治疗药水</span>' : '<span class="no">死亡前 20 秒未用治疗药水</span>'}${consumables.length ? `<span>${consumables.join("、")}</span>` : ""}</span>`;
  }

  function renderCritical() {
    const data = boss().critical || {}, malice = data.malice || {}, melee = data.nonTankMelee || {}, wrath = data.nonTankMotherWrath || {}, focus = data.platform2To3;
    const focusPanel = focus ? `<section class="panel"><h2>第 2 → 第 3 平台高压流程</h2><p class="muted">${esc(focus.startTime)}–${esc(focus.endTime)}；检查浪潮、吸取、易爆清除与碎场组合期间死亡者的个人减伤和治疗消耗品。当前口径只检查死亡前 15 秒是否有个人减伤施放记录，不推断该技能当时是否冷却可用；治疗石和治疗药水检查死亡前 20 秒。</p>${table(["死亡时间","玩家","致死技能","个人减伤 / 消耗品"], (focus.deaths || []).map(row => [esc(row.time),player(row),spell(row.abilityID,row.ability),defensiveUses(row)]))}</section>` : '<section class="panel"><h2>第 2 → 第 3 平台高压流程</h2><div class="empty">本场尚未进入该流程。</div></section>';
    return `<section class="summary-strip">${metric("恶意漏断", `${malice.completedCount || 0} 次`)}${metric("非坦克近战", `${melee.hitCount || 0} 次`)}${metric("非坦克近战伤害", num(melee.totalDamage))}${metric("蛇母之怒非坦克", `${wrath.castCount || 0} 次`)}</section><section class="panel"><h2>${spell(malice.spellID || 1290779,"恶意")}打断</h2>${table(["时间","来源","结果"], (malice.casts || []).map(row => [esc(row.time),esc(row.source),row.prevented?badge("已阻止","good"):badge("施法成功","bad")]))}</section><section class="panel"><h2>非坦克玩家受到近战攻击</h2>${table(["玩家","次数","总伤害","来源"], (melee.players || []).map(row => [player(row),row.hitCount,num(row.totalDamage),(row.sources || []).map(item => `${esc(item.source)} ×${item.count}`).join("、")]))}</section><section class="panel"><h2>${spell(1298367,"蛇母之怒")}命中非坦克目标</h2><p class="muted">同一次释放期间只计算一次。</p>${table(["时间","玩家"], (wrath.casts || []).map(row => [esc(row.time),player(row)]))}</section>${focusPanel}`;
  }

  function renderContent() {
    const renderers = { survival: renderSurvival, waves: renderWaves, heart: renderHeart, fangs: renderFangs, critical: renderCritical };
    $("content").innerHTML = (renderers[state.tab] || (() => '<div class="empty">该页暂无数据。</div>'))();
    refreshTooltips();
  }

  function render() { renderStats(); renderTabs(); renderContent(); }
  function load(payload) {
    state.payload = payload;
    state.pulls = [...(payload.data?.page1_wipeAnalysis || [])].sort((a,b) => String(b.startTimeIso || `${b.date || ""}${b.fightID || ""}`).localeCompare(String(a.startTimeIso || `${a.date || ""}${a.fightID || ""}`)));
    const requestedFight = Number(new URLSearchParams(location.search).get("fight"));
    const index = state.pulls.findIndex(row => Number(row.fightID) === requestedFight);
    state.pull = index >= 0 ? index : 0;
    state.tab = (payload.meta?.tabDefinitions || [])[0]?.key || "survival";
    $("pullSelect").innerHTML = state.pulls.map((row,index) => `<option value="${index}">Fight ${row.fightID} · ${esc(row.date || "")} ${esc(row.startClock || "")} · ${esc(row.difficultyName || "未知")} · ${row.isKill ? "KILL" : `${Number(row.bossPercentage || 0).toFixed(2)}%`} · ${esc(row.duration || "")}</option>`).join("");
    $("pullSelect").value = String(state.pull);
    $("error").textContent = state.pulls.length ? "" : "分析结果中没有乌拉特克战斗。";
    render();
  }

  $("pullSelect").onchange = event => { state.pull = Number(event.target.value); state.tab = (state.payload?.meta?.tabDefinitions || [])[0]?.key || "survival"; render(); };
  $("fileInput").onchange = async event => { try { load(JSON.parse(await event.target.files[0].text())); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
  const sourcePath = new URLSearchParams(location.search).get("json") || "";
  if (sourcePath) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(sourcePath)}`;
  if (sourcePath) window.MythicReportRuntime.loadPayload(sourcePath).then(load).catch(error => $("error").textContent = error.message);
  else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
})();
