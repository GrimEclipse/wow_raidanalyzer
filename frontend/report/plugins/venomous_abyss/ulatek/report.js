(function () {
  "use strict";

  const state = { payload: null, pulls: [], pull: 0, tab: "survival", heartView: "total" };
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
    if(state.payload?.meta?.skippedAnalyses?.length){$("meta").textContent += " · 未分析：" + state.payload.meta.skippedAnalyses.join("、");}$("wclLink").href = pull?.wclDeepLink || "#";
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
    const deaths = data.waveDeaths || {}, eggs = data.p3Eggs || {};
    const eggRounds = (eggs.rounds || []).map(round => `<article class="card round-card ${round.failedEggCount ? "bad" : "good"}"><h3>P3 蛋 #${round.index} · ${esc(round.time)} ${badge(`应转 ${round.expectedKillableEggCount ?? 4} 只`)} ${badge(`固定尖啸者 ${round.baselineShriekerCount || 0} 只`)} ${round.failedEggCount ? badge(`漏蛋 ${round.failedEggCount} 只`,"bad") : badge("无额外孵化","good")}</h3>${table(["实例","方位","负责组","结果","总伤害"], (round.eggs || []).map(row => [`#${row.instance ?? "—"}`,esc(row.clockDirection || "方位不足"),esc(row.expectedGroup || "未指定"),row.killed?badge("已击杀","good"):row.confirmedByExtraShrieker?badge("孵化出额外尖啸者","bad"):badge("未确认孵化"),num(row.totalDamage)]))}${(round.failedEggs || []).map((row,index) => `<div class="egg-failure"><h4>未转掉的蛋 #${index + 1} · ${esc(row.clockDirection || "方位不足")} · ${esc(row.expectedGroup || "未指定")} ${row.confirmedByExtraShrieker ? badge("额外尖啸者已确认","bad") : ""}</h4>${table(["玩家","伤害","命中"],(row.damageByPlayer || []).map(item => [player(item),num(item.damage),item.hitCount || 0]))}</div>`).join("")}</article>`).join("") || '<div class="empty">没有进入 P3 蛋流程。</div>';
    return `<section class="summary-strip">${metric("浪潮施加 / 刷新", `${data.applicationCount ?? data.hitCount ?? 0} 次`)}${metric("P1 吃波死亡", `${deaths.p1Count || 0} 人次`)}${metric("P3 吃波死亡", `${deaths.p3Count || 0} 人次`)}${metric("带蛋中波", `${data.eggCarrierHitCount || 0} 次`)}${metric("P3 漏蛋", `${eggs.failedEggCount || 0} 只`)}</section><section class="panel"><h2>${spell(data.spellID || 1292403,"腐蚀浪潮")}施加 / 刷新</h2><p class="muted">按 applydebuff、applydebuffstack、refreshdebuff 事件计数；仅去除完全重复的日志行。中波后 1 秒内本人死亡记为吃波连带死亡。</p>${table(["时间","阶段","玩家","事件","带蛋","1 秒内死亡","伤害"], (data.hits || []).map(row => [esc(row.time), esc(row.phase), player(row),esc(row.eventType),row.eggCarrier ? badge("携带蛇卵", "bad") : "—",row.diedWithinWindow?badge(`死亡 +${row.deathDelayMs}ms`,"bad"):"—",num(row.amount)]))}</section><section class="panel"><h2>P1 / P3 吃波死亡</h2>${table(["阶段","中波","死亡","玩家","延迟","致死技能"], (deaths.events || []).map(row => [esc(row.phase),esc(row.waveTime),esc(row.deathTime),player(row),`${row.delayMs} ms`,spell(row.abilityID,row.ability)]))}</section><section class="panel"><h2>${spell(data.eggAuraID || 1295360,"恶性甲壳")}携带区间（P1 / P3）</h2>${table(["阶段","玩家","携带时间","持续","中波","提前孵化"], (data.carries || []).map(row => [esc(row.phase), player(row), `${esc(row.startTime)}–${esc(row.endTime)}`, `${row.durationSec} 秒`, row.waveHitCount || 0, row.earlyHatchCount || 0]))}</section><section class="panel"><h2>P3 蛋转火</h2><p class="muted">每轮总流程按 4 个槽位；第 3 / 4 轮固定出现 1 / 2 只尖啸者，不算漏蛋。3 点蛋由近战转火，6 点与 9 点蛋由远程转火。只有超过当轮固定基准的额外尖啸者才能确认漏蛋；若日志在孵化前结束，只显示为“未确认孵化”。本项不进入整晚统计。</p><div class="cards">${eggRounds}</div></section>`;
  }

  function renderRagePotions(data) {
    if (!data) return '<h4>易伤窗口爆发药水</h4><p class="muted">旧报告未统计药水生效区间，请重新分析。</p>';
    return `<h4>易伤窗口爆发药水 · 已生效 ${data.usedCount} / ${data.playerCount} 人</h4><p class="muted">${esc(data.evidenceNote)} 未见生效 ${data.missingCount} 人${data.unknownCount?`，数据缺失 ${data.unknownCount} 人`:''}。</p>
      ${table(['玩家','职责 / 状态','药水判定','药水生效区间','窗口覆盖'], (data.players||[]).map(row=>[
        player(row),`${String(row.role||'').endsWith('tank')?'坦克':'输出'}${row.aliveAtStart?'':' · 窗口开始时已死亡'}`,
        row.potionUsed===true?badge('已吃药','good'):row.potionUsed===false?badge('未见生效','bad'):badge('缺少光环数据'),
        (row.effects||[]).map(e=>`${spell(e.spellID,e.spell)} · ${e.unknownStart?'开始时间未记录':esc(e.startTime)}–${esc(e.endTime)}${e.openEnded?'（未见移除，按战斗结束截断）':''}<br><small>窗口内 ${esc(e.overlapStart)}–${esc(e.overlapEnd)}</small>`).join('<br>')||'—',
        row.potionUsed===null?'—':`${Number((row.coverageMs||0)/1000).toFixed(2)} 秒 · ${row.coveragePercent}%`
      ]))}`;
  }

  function renderHeart() {
    const data = boss().rage || {};
    const rounds = data.rounds || [];
    const totalHeartDamage = data.totalHeartDamage ?? rounds.reduce((sum,row)=>sum+(row.heartDamage||0),0);
    const totalBossDamage = data.totalBossDamage ?? rounds.reduce((sum,row)=>sum+(row.bossDamage||0),0);
    const totalDamage = data.totalDamage ?? totalHeartDamage + totalBossDamage;
    const damageRows = row => {
      const source = row.damageByPlayer || (row.heartDamageByPlayer || []).map(item => ({...item, heartDamage:item.damage || 0, bossDamage:0, totalDamage:item.damage || 0}));
      const key = state.heartView === "heart" ? "heartDamage" : "totalDamage";
      return [...source].sort((left,right)=>(right[key]||0)-(left[key]||0));
    };
    const damageTable = row => state.heartView === "heart"
      ? table(["玩家","心脏伤害"], damageRows(row).filter(item => item.heartDamage > 0).map(item => [player(item),num(item.heartDamage)]))
      : table(["玩家","有效伤害总和","心脏伤害","Boss 本体伤害"], damageRows(row).map(item => [player(item),num(item.totalDamage),num(item.heartDamage),num(item.bossDamage)]));
    const switcher = `<div class="rage-view-toggle" role="group" aria-label="易伤伤害显示口径"><button type="button" data-heart-view="total" class="${state.heartView === "total" ? "active" : ""}" aria-pressed="${state.heartView === "total"}">总有效伤害</button><button type="button" data-heart-view="heart" class="${state.heartView === "heart" ? "active" : ""}" aria-pressed="${state.heartView === "heart"}">只看心脏伤害</button></div>`;
    return `<section class="summary-strip">${metric("被缚之怒", `${rounds.length} 轮`)}${metric("易伤有效伤害", num(totalDamage))}${metric("烈毒之心伤害", num(totalHeartDamage))}${metric("Boss 本体伤害", num(totalBossDamage))}</section><section class="panel rage-view-panel"><div><h2>易伤期间有效伤害</h2><p class="muted">总有效伤害 = 烈毒之心伤害 + 同一被缚之怒窗口内对乌拉特克本体造成的伤害；宠物和召唤物伤害归入主人。</p></div>${switcher}</section><div class="rage-rounds">${rounds.map(row => `<article class="card round-card ${row.deathCount || row.fallingDebrisHitCount ? "bad" : "good"}"><h3>${spell(1286860,`${ordinal(row.index)}被缚之怒`)} <span class="muted">${esc(row.time)}–${esc(row.endTime)}</span> ${badge(`${row.durationSec} 秒`)} ${row.deathCount ? badge(`死亡 ${row.deathCount}`,"bad") : badge("无人死亡","good")}</h3><h4>有效伤害 ${num(row.totalDamage ?? row.heartDamage)} · ${spell(1299526,"烈毒之心")} ${num(row.heartDamage)} + Boss 本体 ${num(row.bossDamage)}</h4><div class="rage-damage-table">${damageTable(row)}</div>${renderRagePotions(row.potions)}<h4>${spell(1286885,"落石")} · ${row.fallingDebrisHitCount || 0} 次 / ${num(row.fallingDebrisDamage)} 伤害</h4>${table(["时间","玩家","伤害"], (row.fallingDebrisHits || []).map(item => [esc(item.time),player(item),num(item.amount)]))}<h4>易伤期间死亡</h4>${table(["时间","玩家","致死技能"], (row.deaths || []).map(item => [esc(item.time),player(item),spell(item.abilityID,item.ability)]))}</article>`).join("") || '<div class="empty">本场没有记录到被缚之怒窗口。</div>'}</div>`;
  }

  function renderFangs() {
    const data = boss().fangs || {};
    return `<section class="summary-strip">${metric("点名人数", `${data.rounds?.[0]?.targetCount || 0} 人`)}${metric("违反拉线逻辑", `${data.wrongBreakCount || 0} 人`)}${metric("同场窗口", `${data.batchWindowSec || 3} 秒`)}${metric("凋萎静脉最高", `${data.maxBlightStack || 0} 层`)}</section><div class="cards">${(data.rounds || []).map(round => `<article class="card round-card ${round.wrongBreakCount ? "bad" : "good"}"><h3>${spell(1311611,"攫取毒牙")} · ${esc(round.time)} ${badge(`点名 ${round.targetCount || (round.targets || []).length} 人`)} ${round.wrongBreakCount ? badge("违反逻辑 1 人","bad") : badge("拉线顺序正确","good")}</h3><p class="muted">以 Boss 初始出生点${round.bossInitialPosition ? ` x=${num(round.bossInitialPosition.x)}` : ""}为固定左右场分界。首断后同场 3 秒内全部拉断；对场必须等凋萎静脉完全消除，再从该场首断起 3 秒内全部拉断。发生违规后只归责并输出第一个违规者。</p>${(round.sides || []).map(side => `<p><strong>${esc(side.side)}：</strong>${players(side.targets)} <span class="muted">施加 ${esc(side.applyTime)}${side.wardenInstance != null ? ` · 守卫 #${side.wardenInstance}` : ""}${side.positionX != null ? ` · x=${num(side.positionX)}` : ""}</span></p>`).join("")}${table(["拉断时间","场侧","批次","玩家","持有","叠层证据","判定"], (round.breaks || []).map(row => [esc(row.time),esc(row.side || "未确认"),row.batch?`第 ${row.batch} 批`:"—",player(row),`${row.heldSec} 秒`,row.evidenceMissing?badge("未取得"): `${row.fromStack} → ${row.toStack} 层`,row.wrong?badge((row.violationReasons || []).join("；"),"bad"):row.adjudication==="not_attributed_after_first_violation"?badge("首个违规后不再归责"):badge("正常","good")]))}${(round.overLimitPlayers || []).length ? `<p><strong>首个违反拉线逻辑：</strong>${players(round.overLimitPlayers)}</p>` : ""}${(round.unresolved || []).length ? `<p><strong>未记录移除：</strong>${players(round.unresolved)}</p>` : ""}</article>`).join("") || '<div class="empty">本场没有攫取毒牙记录。</div>'}</div>`;
  }

  function defensiveUses(row) {
    const personal = (row.personalDefensives || []).map(item => `${spell(item.spellID,item.name)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    const consumables = (row.consumables || []).map(item => `${spell(item.spellID,item.spellName)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    return `<span class="flow-status">${personal.length ? `<span class="yes">死亡前 15 秒个人减伤：${personal.join("、")}</span>` : '<span class="no">死亡前 15 秒未记录个人减伤施放</span>'}${row.usedHealthstone ? '<span class="yes">治疗石</span>' : '<span class="no">死亡前 20 秒未用治疗石</span>'}${row.usedHealingPotion ? '<span class="yes">治疗药水</span>' : '<span class="no">死亡前 20 秒未用治疗药水</span>'}${consumables.length ? `<span>${consumables.join("、")}</span>` : ""}</span>`;
  }

  function renderP25Eggs(data) {
    if (!data) return '<section class="panel"><h2>P2.5 连续分摊 · 携蛋检查</h2><p class="muted">旧报告未包含此项，请重新分析。</p></section>';
    return `<section class="panel"><h2>P2.5 连续分摊 · 携蛋检查</h2><p class="muted">${esc(data.evidenceNote)}</p>
      ${data.started?`<p>${esc(data.startTime)}–${esc(data.endTime)} · 已完成 ${data.completedSoakCount} / ${data.expectedSoakCount} 次分摊 ${data.completed?badge('已检查分摊后携蛋','good'):badge('分摊未完整结束')}</p>`:''}
      ${data.reason?`<p class="muted">${esc(data.reason)}</p>`:''}
      <h3>阶段内带蛋死亡 · ${data.deathCount} 人次</h3>${table(['死亡时间','玩家','开始携蛋','致死技能'],(data.deaths||[]).map(row=>[esc(row.time),player(row),esc(row.carryStartTime),spell(row.abilityID,row.ability)]))}
      <h3>分摊结束仍携蛋 · ${data.completed?`${data.mistakeCount} 次玩家失误`:'未判定'}</h3>
      ${data.completed?table(['检查时间','玩家','开始携蛋','判定'],(data.remaining||[]).map(row=>[esc(row.time),player(row),esc(row.carryStartTime),badge('分摊结束仍携蛋','bad')])):'<p class="muted">等待六次分摊完成及结算后日志。</p>'}</section>`;
  }

  function renderCritical() {
    const data = boss().critical || {}, malice = data.malice || {}, melee = data.nonTankMelee || {}, wrath = data.motherWrath || {}, bites = data.serpentBites || {}, coiled = data.coiledPreyDeaths || {}, focus = data.platform2To3;
    const focusPanel = focus ? `<section class="panel"><h2>第 2 → 第 3 平台高压流程</h2><p class="muted">${esc(focus.startTime)}–${esc(focus.endTime)}；检查浪潮、吸取、易爆清除与碎场组合期间死亡者的个人减伤和治疗消耗品。当前口径只检查死亡前 15 秒是否有个人减伤施放记录，不推断该技能当时是否冷却可用；治疗石和治疗药水检查死亡前 20 秒。</p>${table(["死亡时间","玩家","致死技能","个人减伤 / 消耗品"], (focus.deaths || []).map(row => [esc(row.time),player(row),spell(row.abilityID,row.ability),defensiveUses(row)]))}</section>` : '<section class="panel"><h2>第 2 → 第 3 平台高压流程</h2><div class="empty">本场尚未进入该流程。</div></section>';
    const bitePanel = `<section class="panel"><h2>${spell(bites.spellID || 1295905,"毒蛇之咬")}分摊</h2><p class="muted">以 ${spell(bites.participationAuraID || 1313529,"摄入毒液")} 的施加 / 刷新作为实际参与分摊证据；7 码坐标只用于辅助显示最近点名。点名移除后正常转为易爆清除，钙化尸骸单独标记。</p><div class="cards">${(bites.rounds || []).map(round => `<article class="card round-card ${round.nonParticipantCount ? "bad" : "good"}"><h3>#${round.index} · ${esc(round.time)} · 结算 ${esc(round.snapshotTime)} ${round.nonParticipantCount?badge(`未参与 ${round.nonParticipantCount} 人`,"bad"):badge("全员参与","good")}</h3><p><strong>点名：</strong>${(round.targets || []).map(row => `${player(row)} ${badge({volatile_purge:"易爆清除",calcified_corpse:"钙化尸骸",removed:"已移除",unresolved:"未结算"}[row.resolution] || row.resolution)}`).join("、") || "—"}</p><p><strong>参与：</strong>${players(round.participants)}</p>${round.nonParticipantCount?`<p><strong>未参与：</strong>${players(round.nonParticipants)}</p>`:""}${(round.unknownPlayers || []).length?`<p class="muted">坐标不足（不影响光环判定）：${players(round.unknownPlayers)}</p>`:""}</article>`).join("") || '<div class="empty">没有毒蛇之咬记录。</div>'}</div></section>`;
    const coiledPanel = `<section class="panel"><h2>${spell(coiled.spellID || 1301510,"盘绕猎物")}死亡</h2>${table(["时间","玩家","致死技能"],(coiled.deaths || []).map(row => [esc(row.time),player(row),spell(row.abilityID,row.ability)]))}</section>`;
    return `<section class="summary-strip">${metric("恶意漏断", `${malice.completedCount || 0} 次`)}${metric("非坦克近战", `${melee.hitCount || 0} 次`)}${metric("蛇母之怒 A 团", `${wrath.raidWideFailureCount || 0} 次`)}${metric("死于盘绕猎物", `${coiled.deathCount || 0} 人次`)}</section>${renderP25Eggs(data.p25Eggs)}${bitePanel}${coiledPanel}<section class="panel"><h2>${spell(malice.spellID || 1290779,"恶意")}打断</h2>${table(["时间","来源","结果"], (malice.casts || []).map(row => [esc(row.time),esc(row.source),row.prevented?badge("已阻止","good"):badge("施法成功","bad")]))}</section><section class="panel"><h2>非坦克玩家受到近战攻击</h2>${table(["玩家","次数","总伤害","来源"], (melee.players || []).map(row => [player(row),row.hitCount,num(row.totalDamage),(row.sources || []).map(item => `${esc(item.source)} ×${item.count}`).join("、")]))}</section><section class="panel"><h2>${spell(1298367,"蛇母之怒")}无人承接 / 全团伤害</h2><p class="muted">正常情况是当前坦克在圈内连续承伤；只有同一轮至少 3 名玩家受到蛇母之怒伤害时才判定为 A 团。承接目标优先取本轮施法目标，缺失时回溯施法前 8 秒内 Boss 最后一次近战目标。</p>${table(["时间","当轮承接目标","目标证据","全团伤害","受影响玩家"], (wrath.failures || []).map(row => [esc(row.time),player(row.receiver),esc(row.receiverEvidence),`${badge(`命中 ${row.affectedCount || 0} 人`,"bad")} · ${num(row.totalDamage)} 伤害`,players(row.affectedPlayers)]))}</section>${focusPanel}`;
  }

  function renderContent() {
    const renderers = { survival: renderSurvival, waves: renderWaves, heart: renderHeart, fangs: renderFangs, critical: renderCritical };
    $("content").innerHTML = (renderers[state.tab] || (() => '<div class="empty">该页暂无数据。</div>'))();
    document.querySelectorAll("[data-heart-view]").forEach(button => button.onclick = () => {
      state.heartView = button.dataset.heartView;
      renderContent();
    });
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
