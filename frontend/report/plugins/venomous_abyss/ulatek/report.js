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
    $("title").textContent = `乌拉特克，Fight ${pull?.fightID || "-"}`;
    $("meta").textContent = `${pull?.difficultyName || "未知难度"}，${pull?.fightPhase || "阶段未记录"}，${pull?.isKill ? "击杀" : `Boss 剩余 ${Number(pull?.bossPercentage || 0).toFixed(2)}%`}，${pull?.date || ""} ${pull?.startClock || ""}`;
    if(state.payload?.meta?.skippedAnalyses?.length){$("meta").textContent += "，未分析：" + state.payload.meta.skippedAnalyses.join("、");}$("wclLink").href = pull?.wclDeepLink || "#";
    const rows = [["战斗时长", pull?.duration || "—"], ["结果", pull?.isKill ? "KILL" : `${Number(pull?.bossPercentage || 0).toFixed(2)}%`], ["难度", pull?.difficultyName || "未知"], ["阵亡", survival.deathCount || 0], ["战复", survival.combatResCount || 0], ["结束存活", `${survival.survivorCount || 0}/${survival.rosterCount || 0}`]];
    $("stats").innerHTML = rows.map(([label, value]) => `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");
  }

  function renderTabs() {
    const definitions = [...(state.payload?.meta?.tabDefinitions || [{key:"survival", label:"全场存活情况"}])];
    if(boss().combatReplay&&!definitions.some(r=>r.key==='replay'))definitions.splice(1,0,{key:'replay',label:'场地回放'});
    if (!definitions.some(row => row.key === state.tab)) state.tab = definitions[0].key;
    $("tabs").innerHTML = definitions.map(row => `<button data-tab="${esc(row.key)}" class="${row.key === state.tab ? "active" : ""}">${esc(row.label)}</button>`).join("");
    document.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => { state.tab = button.dataset.tab; renderTabs(); renderContent(); });
  }

  function renderSurvival() {
    const survival = current()?.survival || {};
    return `<section class="panel"><h2>死亡原因 / 战复时间线</h2><p class="muted">未记录致死技能视为跌落；死亡技能可悬停查看中文 tooltip。</p>${table(["时间","类型","玩家","原因 / 技能"], (survival.timeline || []).map(event => [esc(event.time), event.kind === "combat_res" ? badge("战复", "good") : badge("死亡", "bad"), player(event), event.kind === "combat_res" ? `${player({player:event.source,classColor:event.sourceClassColor})} 使用 ${spell(event.abilityID,event.ability)}` : event.deathCause === "fall" ? "跌落" : spell(event.abilityID,event.ability)]))}</section>`;
  }

  function renderWaves() {
    const data = {...(boss().wavesAndEggs || {})}, deaths = data.waveDeaths || {}, eggs = data.p3Eggs || {};
    if (data.countingHits) data.applicationCount = data.countingHits.length;
    if (data.countingDutyWaveHits) data.eggCarrierHitCount = data.countingDutyWaveHits.length;
    const wretch = boss().mythicWretch || {}, tether = boss().tankInterception || {};
    const steals = (data.stolenCarries || []).filter(row => row.phase === 'P1'), failures = tether.failures || [];
    const assignment = data.eggAssignment || {};
    const dutyNote = (assignment.ready ? `P1 指定搬蛋组 ${assignment.matchedCount} 人` : assignment.source === 'missing' ? 'P1 未配置搬蛋组，暂不判抢蛋' : `P1 搬蛋组仅匹配 ${assignment.matchedCount} 人，暂不判抢蛋`) + '；中波次数在团队同时死亡达到 2 人后停止计数';
    const duties = (data.dutyCarries || data.carries || []).filter(row => row.phase === 'P1');
    const stolenByPickup = new Map(steals.map(row => [`${row.playerID}:${row.timeMs}`, row]));
    const carryByPickup = new Map((data.carries || []).map(row => [`${row.playerID}:${row.phase}:${row.startTime}`, row]));
    const dutyRows = duties.map(row => {
      const stolen = stolenByPickup.get(`${row.playerID}:${row.timeMs}`);
      const carry = carryByPickup.get(`${row.playerID}:${row.phase}:${row.time}`);
      const outcome = [stolen?.failureKinds?.join('、'), carry?.waveHitCount ? `带蛋中波 ${carry.waveHitCount} 次` : '', carry?.earlyHatchCount ? `提前孵化 ${carry.earlyHatchCount} 次` : ''].filter(Boolean);
      return [esc(row.time || row.startTime), esc(row.phase), player(row), stolen ? badge('抢蛋', 'bad') : badge('搬蛋', 'good'), outcome.map(esc).join('、') || '未见处理失败'];
    });
    const tetherRows = failures.map(row => [esc(row.time), row.player ? `${player(row)} ${badge(row.attribution === 'observed-interception-ticks' ? '承接跳数证据' : '位置推定', 'warn')}` : badge('责任坦克未确定', 'warn'), `${row.tickCount}/${tether.expectedTicks || 5}`, row.targetPosition ? '已定位中间畸体' : '缺少畸体位置']);
    const festerRows = (wretch.rounds || []).map(row => [esc(row.time), row.castCompleted ? esc(row.completionTime) : '已中断', row.hits?.length ? row.hits.map(hit => `${player(hit)} ${num(hit.amount)}`).join('、') : '无直接伤害']);
    const eggRounds = (eggs.rounds || []).map(row => [row.index, esc(row.time), row.observedEggCount ?? '—', row.shriekerCount ?? '—', eggs.adjudicationAvailable === false ? '史诗难度不按英雄基准判责' : row.failedEggCount ? badge(`${row.failedEggCount} 只漏蛋`, 'bad') : '无确认漏蛋']);
    const unconfirmedHatches = (data.possibleCollisionHatches || []).filter(row => !row.confirmedCollision);
    const collisionPanel = `<section class="panel"><h2>撞蛋，${(data.eggCollisions || []).length} 次</h2><p class="muted">P2 同样统计。两人同帧失去携蛋并出现孵化时，若场上没有已孵化蝰蛇，剧毒喷溅同时命中双方可确认撞蛋；可靠坐标相距不超过 4 码也可确认。其余列为疑似线索。</p>${table(['时间','阶段','撞蛋玩家','确认依据'],(data.eggCollisions || []).map(row => [esc(row.time),esc(row.phase),(row.players || []).map(player).join(' 和 '),row.splashSpellID ? `${spell(row.splashSpellID,'剧毒喷溅')} ${esc(row.splashTime)}` : `${esc(row.distanceYards)} 码`]))}</section>`;
    const rawDetails = `<details class="panel"><summary>展开原始中波、携蛋与蛋转火记录</summary><p class="muted">原始中波受击归在被命中玩家名下，仅供复盘，不直接判责。受击记录不包含逐道波的出生点和方向，不能据此还原场地波形。</p><h3>中波施加 / 刷新</h3>${table(['时间','阶段','玩家','带蛋','伤害'], (data.hits || []).map(row => [esc(row.time),esc(row.phase),player(row),row.eggCarrier ? badge('携蛋','warn') : '—',num(row.amount)]))}<h3>全部携蛋区间（含非任务阶段）</h3>${table(['阶段','玩家','携带时间','中波','提前孵化'], (data.carries || []).map(row => [esc(row.phase),player(row),`${esc(row.startTime)}–${esc(row.endTime)}`,row.waveHitCount || 0,row.earlyHatchCount || 0]))}<h3>P3 蛋转火</h3>${table(['轮次','时间','蛋','尖啸者','结果'],eggRounds)}</details>`;
    return `<section class="summary-strip">${metric('中波施加 / 刷新', `${data.applicationCount ?? data.hitCount ?? 0} 次`)}${metric('搬蛋', `${duties.length} 次`)}${metric('抢蛋', `${steals.length} 次`)}${metric('漏接', `${failures.length} 次`)}${metric('带蛋中波', `${data.eggCarrierHitCount || 0} 次`)}${data.cleanWaveHits ? metric('有效中波', `${data.cleanWaveHits.length} 次`) : ''}</section><section class="panel"><h2>搬蛋记录与处理结果</h2><p class="muted">${esc(dutyNote)}。共记录 ${duties.length} 次搬蛋；只有指定搬蛋组满 8 人时，其他玩家领蛋才记抢蛋。</p>${table(['时间','阶段','玩家','判定','后续'],dutyRows)}${unconfirmedHatches.length ? `<details><summary>疑似碰蛋线索（${unconfirmedHatches.length}）</summary>${table(['时间','玩家','孵化'],unconfirmedHatches.map(row => [esc(row.time),player(row),esc(row.hatchTime)]))}</details>` : ''}</section>${collisionPanel}<section class="panel"><h2>虚影接线漏给中间畸体</h2><p class="muted">虚影完成毒性孵化后应由坦克接到 5 跳。漏接时回放按接线方向演示五向浪潮，推进速度仅作视觉示意。优先按实际承接跳数归责；零跳时仅在坦克位置明显可区分时推定。</p>${table(['时间','坦克','接线跳数','场地证据'],tetherRows)}</section><section class="panel"><h2>腐败爆发直接命中</h2><p class="muted">只列读条完成瞬间实际受到直伤的玩家；后续持续伤害不重复记入。</p>${table(['读条开始','完成','直接命中'],festerRows)}</section>${deaths.events?.length ? `<details class="panel"><summary>P1 / P3 中波后 1 秒内死亡（${deaths.events.length}）</summary>${table(['阶段','中波','死亡','玩家','致死技能'],deaths.events.map(row => [esc(row.phase),esc(row.waveTime),esc(row.deathTime),player(row),spell(row.abilityID,row.ability)]))}</details>` : ''}${rawDetails}`;
  }

  function renderRagePotions(data) {
    if (!data) return '<h4>易伤窗口爆发药水</h4><p class="muted">旧报告未统计药水生效区间，请重新分析。</p>';
    return `<h4>易伤窗口爆发药水，已生效 ${data.usedCount} / ${data.playerCount} 人</h4><p class="muted">${esc(data.evidenceNote)} 未见生效 ${data.missingCount} 人${data.unknownCount?`，数据缺失 ${data.unknownCount} 人`:''}。</p>
      ${table(['玩家','职责 / 状态','药水判定','药水生效区间','窗口覆盖'], (data.players||[]).map(row=>[
        player(row),`${String(row.role||'').endsWith('tank')?'坦克':'输出'}${row.aliveAtStart?'':'，窗口开始时已死亡'}`,
        row.potionUsed===true?badge('已吃药','good'):row.potionUsed===false?badge('未见生效','bad'):badge('缺少光环数据'),
        (row.effects||[]).map(e=>`${spell(e.spellID,e.spell)}，${e.unknownStart?'开始时间未记录':esc(e.startTime)}–${esc(e.endTime)}${e.openEnded?'（未见移除，按战斗结束截断）':''}<br><small>窗口内 ${esc(e.overlapStart)}–${esc(e.overlapEnd)}</small>`).join('<br>')||'—',
        row.potionUsed===null?'—':`${Number((row.coverageMs||0)/1000).toFixed(2)} 秒，${row.coveragePercent}%`
      ]))}`;
  }

  function renderHeart() {
    const data = boss().rage || {};
    const rounds = data.rounds || [];
    if (rounds.length && data.simulatedSupportDamage === undefined) {
      return '<section class="panel"><h2>被缚之怒伤害需重新分析</h2><p>这份旧结果包含增辉模拟归因，伤害数字可能虚高。请重新分析此场战斗，以查看实际有效伤害与单列的模拟贡献。</p></section>';
    }
    const totalHeartDamage = data.totalHeartDamage ?? rounds.reduce((sum,row)=>sum+(row.heartDamage||0),0);
    const totalBossDamage = data.totalBossDamage ?? rounds.reduce((sum,row)=>sum+(row.bossDamage||0),0);
    const totalDamage = data.totalDamage ?? totalHeartDamage + totalBossDamage;
    const simulatedSupportDamage = data.simulatedSupportDamage || 0;
    const ghost = value => value ? `<span class="muted">(${num(value)})</span>` : '—';
    const damageRows = row => {
      const source = row.damageByPlayer || (row.heartDamageByPlayer || []).map(item => ({...item, heartDamage:item.damage || 0, bossDamage:0, totalDamage:item.damage || 0}));
      const key = state.heartView === "heart" ? "heartDamage" : "totalDamage";
      return [...source].sort((left,right)=>(right[key]||0)-(left[key]||0));
    };
    const damageTable = row => state.heartView === "heart"
      ? table(["玩家","心脏实际伤害","增辉模拟贡献（不计入）"], damageRows(row).filter(item => item.heartDamage > 0 || item.simulatedHeartDamage > 0).map(item => [player(item),num(item.heartDamage),ghost(item.simulatedHeartDamage)]))
      : table(["玩家","实际有效伤害","心脏实际伤害","Boss 本体实际伤害","增辉模拟贡献（不计入）"], damageRows(row).map(item => [player(item),num(item.totalDamage),num(item.heartDamage),num(item.bossDamage),ghost(item.simulatedSupportDamage)]));
    const switcher = `<div class="rage-view-toggle" role="group" aria-label="易伤伤害显示口径"><button type="button" data-heart-view="total" class="${state.heartView === "total" ? "active" : ""}" aria-pressed="${state.heartView === "total"}">总有效伤害</button><button type="button" data-heart-view="heart" class="${state.heartView === "heart" ? "active" : ""}" aria-pressed="${state.heartView === "heart"}">只看心脏伤害</button></div>`;
    return `<section class="summary-strip">${metric("被缚之怒", `${rounds.length} 轮`)}${metric("实际有效伤害", num(totalDamage))}${metric("烈毒之心实际伤害", num(totalHeartDamage))}${metric("Boss 本体实际伤害", num(totalBossDamage))}${simulatedSupportDamage ? metric("增辉模拟贡献（不计入）", `(${num(simulatedSupportDamage)})`) : ''}</section><section class="panel rage-view-panel"><div><h2>易伤期间有效伤害</h2><p class="muted">实际有效伤害 = 烈毒之心命中伤害 + 同一被缚之怒窗口内对乌拉特克本体的命中伤害；宠物和召唤物伤害归入主人。WCL 带 supportID 且标记从受增益者扣除的增辉模拟事件以括号单列，不计入总伤害。</p></div>${switcher}</section><div class="rage-rounds">${rounds.map(row => `<article class="card round-card ${row.deathCount || row.fallingDebrisHitCount ? "bad" : "good"}"><h3>${spell(1286860,`${ordinal(row.index)}被缚之怒`)} <span class="muted">${esc(row.time)}–${esc(row.endTime)}</span> ${badge(`${row.durationSec} 秒`)} ${row.deathCount ? badge(`死亡 ${row.deathCount}`,"bad") : badge("无人死亡","good")}</h3><h4>实际有效伤害 ${num(row.totalDamage ?? row.heartDamage)}，${spell(1299526,"烈毒之心")} ${num(row.heartDamage)} + Boss 本体 ${num(row.bossDamage)}</h4>${row.simulatedSupportDamage ? `<p class="muted">增辉模拟贡献（不计入）：(${num(row.simulatedSupportDamage)})</p>` : ''}<div class="rage-damage-table">${damageTable(row)}</div>${renderRagePotions(row.potions)}<h4>${spell(1286885,"落石")}，${row.fallingDebrisHitCount || 0} 次 / ${num(row.fallingDebrisDamage)} 伤害</h4>${table(["时间","玩家","伤害"], (row.fallingDebrisHits || []).map(item => [esc(item.time),player(item),num(item.amount)]))}<h4>易伤期间死亡</h4>${table(["时间","玩家","致死技能"], (row.deaths || []).map(item => [esc(item.time),player(item),spell(item.abilityID,item.ability)]))}</article>`).join("") || '<div class="empty">本场没有记录到被缚之怒窗口。</div>'}</div>`;
  }

  function renderFangs() {
    const data = boss().fangs || {};
    return `<section class="summary-strip">${metric("点名人数", `${data.rounds?.[0]?.targetCount || 0} 人`)}${metric("超出安全层数", `${data.wrongBreakCount || 0} 人`)}${metric("配置安全层数", `${data.safeStacks ?? 3} 层`)}${metric("凋萎静脉最高", `${data.maxBlightStack || 0} 层`)}</section><div class="cards">${(data.rounds || []).map(round => `<article class="card round-card ${round.wrongBreakCount ? "bad" : "good"}"><h3>${spell(1311611,"攫取毒牙")}，${esc(round.time)} ${badge(`点名 ${round.targetCount || (round.targets || []).length} 人`)} ${round.wrongBreakCount ? badge(`超层 ${round.wrongBreakCount} 人`,"bad") : badge("未超安全层数","good")}</h3><p class="muted">按配置的拉断安全层数（${round.safeStacks ?? data.safeStacks ?? 3} 层）判断；左右场仅作点名与站位参考。每次拉断都返回实际层数，未取得层数证据时不判违规。</p>${(round.sides || []).map(side => `<p><strong>${esc(side.side)}：</strong>${players(side.targets)} <span class="muted">施加 ${esc(side.applyTime)}${side.wardenInstance != null ? `，守卫 #${side.wardenInstance}` : ""}${side.positionX != null ? `，x=${num(side.positionX)}` : ""}</span></p>`).join("")}${table(["拉断时间","场侧","玩家","持有","叠层证据","判定"], (round.breaks || []).map(row => [esc(row.time),esc(row.side || "未确认"),player(row),`${row.heldSec} 秒`,row.evidenceMissing?badge("未取得"): `${row.fromStack} → ${row.toStack} 层`,row.wrong?badge((row.violationReasons || []).join("；"),"bad"):row.evidenceMissing?badge("证据不足"):badge("安全","good")]))}${(round.overLimitPlayers || []).length ? `<p><strong>超出安全层数：</strong>${players(round.overLimitPlayers)}</p>` : ""}${(round.unresolved || []).length ? `<p><strong>未记录移除：</strong>${players(round.unresolved)}</p>` : ""}</article>`).join("") || '<div class="empty">本场没有攫取毒牙记录。</div>'}</div>`;
  }

  function defensiveUses(row) {
    const personal = (row.personalDefensives || []).map(item => `${spell(item.spellID,item.name)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    const consumables = (row.consumables || []).map(item => `${spell(item.spellID,item.spellName)}（死亡前 ${(Number(item.msBeforeDeath || 0)/1000).toFixed(1)} 秒）`);
    return `<span class="flow-status">${personal.length ? `<span class="yes">死亡前 15 秒个人减伤：${personal.join("、")}</span>` : '<span class="no">死亡前 15 秒未记录个人减伤施放</span>'}${row.usedHealthstone ? '<span class="yes">治疗石</span>' : '<span class="no">死亡前 20 秒未用治疗石</span>'}${row.usedHealingPotion ? '<span class="yes">治疗药水</span>' : '<span class="no">死亡前 20 秒未用治疗药水</span>'}${consumables.length ? `<span>${consumables.join("、")}</span>` : ""}</span>`;
  }

  function renderP25Eggs(data) {
    if (!data) return '<section class="panel"><h2>P2.5 连续分摊，携蛋检查</h2><p class="muted">旧报告未包含此项，请重新分析。</p></section>';
    return `<section class="panel"><h2>P2.5 连续分摊，携蛋检查</h2><p class="muted">${esc(data.evidenceNote)}</p>
      ${data.started?`<p>${esc(data.startTime)}–${esc(data.endTime)}，已完成 ${data.completedSoakCount} / ${data.expectedSoakCount} 次分摊 ${data.completed?badge('已记录分摊后携蛋','good'):badge('分摊未完整结束')}</p>`:''}
      ${data.reason?`<p class="muted">${esc(data.reason)}</p>`:''}
      <h3>阶段内带蛋死亡，${data.deathCount} 人次</h3>${table(['死亡时间','玩家','开始携蛋','致死技能'],(data.deaths||[]).map(row=>[esc(row.time),player(row),esc(row.carryStartTime),spell(row.abilityID,row.ability)]))}
      <h3>分摊结束仍携蛋，${data.completed?`${(data.remaining||[]).length} 人，仅供复盘`:'未判定'}</h3>
      ${data.completed?table(['检查时间','玩家','开始携蛋','状态'],(data.remaining||[]).map(row=>[esc(row.time),player(row),esc(row.carryStartTime),badge('仍携蛋','warn')])):'<p class="muted">等待六次分摊完成及结算后日志。</p>'}</section>`;
  }

  function renderPerBiteAndWretch() {
    const bites = boss().critical?.serpentBites || {}, focus = boss().p1WretchFocus || {};
    const biteRows = (bites.rounds || []).flatMap(round => (round.soaks || []).map(soak => [
      `#${round.index}，${esc(soak.time)}`, player(soak.target),
      badge({volatile_purge:'感染易爆清除',calcified_corpse:'钙化尸骸',removed:'已移除',unresolved:'未结算'}[soak.resolution] || soak.resolution),
      `${soak.helperCount} / ${soak.minimumHelpers}`,
      soak.enoughHelpers ? badge('达到 5 人','good') : soak.insufficientHelpers ? badge('不足 5 人','bad') : badge('坐标证据不足','warn'),
      players(soak.participants), players(soak.purgeRecipients), players(soak.positionUnknown)
    ]));
    const focusRows = (focus.players || []).map(row => [player(row), row.wretchCastCount || 0,
      row.otherTargetCastCount || 0, (row.otherTargets || []).map(target => `${esc(target.name || target.gameID)} ×${target.castCount}`).join('、') || '—']);
    const bitePanel = boss().critical?.enabledItems?.serpentBites === false ? '' : `<section class="panel"><h2>逐个毒蛇之咬分摊</h2><p class="muted">每个点名单独核算，至少 5 名其他玩家在 7 码圈内帮忙；另一名点名玩家也可参与。结算后的易爆清除与钙化尸骸分别显示，并列出每个圈的玩家归属。</p>${table(['轮次 / 结算','点名','结算结果','帮忙人数','判定','归属此圈的帮忙者','易爆清除','坐标不足'],biteRows)}</section>`;
    return `${bitePanel}<section class="panel"><h2>P1 疫鳞畸体主目标施法</h2><p class="muted">仅统计 P1 结束前有明确敌方主目标的玩家 cast；无目标施法不计入。其他目标列可用于检查转火。</p>${table(['玩家','疫鳞畸体 cast','其他目标 cast','其他目标'],focusRows)}</section>`;
  }

  function renderCritical() {
    const data = boss().critical || {}, malice = data.malice || {}, melee = data.nonTankMelee || {}, wrath = data.motherWrath || {}, bites = data.serpentBites || {}, coiled = data.coiledPreyDeaths || {}, focus = data.platform2To3;
    const enabled = key => data.enabledItems?.[key] !== false;
    const focusPanel = focus ? `<section class="panel" data-critical="platformTransitions"><h2>第 2 → 第 3 平台高压流程</h2><p class="muted">${esc(focus.startTime)}–${esc(focus.endTime)}；检查浪潮、吸取、易爆清除与碎场组合期间死亡者的个人减伤和治疗消耗品。当前口径只检查死亡前 15 秒是否有个人减伤施放记录，不推断该技能当时是否冷却可用；治疗石和治疗药水检查死亡前 20 秒。</p>${table(["死亡时间","玩家","致死技能","个人减伤 / 消耗品"], (focus.deaths || []).map(row => [esc(row.time),player(row),spell(row.abilityID,row.ability),defensiveUses(row)]))}</section>` : '<section class="panel" data-critical="platformTransitions"><h2>第 2 → 第 3 平台高压流程</h2><div class="empty">本场尚未进入该流程。</div></section>';
    const bitePanel = `<section class="panel" data-critical="serpentBites"><h2>${spell(bites.spellID || 1295905,"毒蛇之咬")}分摊</h2><p class="muted">以 ${spell(bites.participationAuraID || 1313529,"摄入毒液")} 的施加 / 刷新作为实际参与分摊证据；7 码坐标只用于辅助显示最近点名。点名移除后正常转为易爆清除，钙化尸骸单独标记。</p><div class="cards">${(bites.rounds || []).map(round => `<article class="card round-card ${round.nonParticipantCount ? "bad" : "good"}"><h3>#${round.index}，${esc(round.time)}，结算 ${esc(round.snapshotTime)} ${round.nonParticipantCount?badge(`未参与 ${round.nonParticipantCount} 人`,"bad"):badge("全员参与","good")}</h3><p><strong>点名：</strong>${(round.targets || []).map(row => `${player(row)} ${badge({volatile_purge:"易爆清除",calcified_corpse:"钙化尸骸",removed:"已移除",unresolved:"未结算"}[row.resolution] || row.resolution)}`).join("、") || "—"}</p><p><strong>参与：</strong>${players(round.participants)}</p>${round.nonParticipantCount?`<p><strong>未参与：</strong>${players(round.nonParticipants)}</p>`:""}${(round.unknownPlayers || []).length?`<p class="muted">坐标不足（不影响光环判定）：${players(round.unknownPlayers)}</p>`:""}</article>`).join("") || '<div class="empty">没有毒蛇之咬记录。</div>'}</div></section>`;
    const coiledPanel = `<section class="panel" data-critical="coiledPreyDeaths"><h2>${spell(coiled.spellID || 1301510,"盘绕猎物")}死亡</h2>${table(["时间","玩家","致死技能"],(coiled.deaths || []).map(row => [esc(row.time),player(row),spell(row.abilityID,row.ability)]))}</section>`;
    const html = `<section class="summary-strip">${enabled("malice")?metric("恶意漏断", `${malice.completedCount || 0} 次`):""}${enabled("nonTankMelee")?metric("非坦克近战", `${melee.hitCount || 0} 次`):""}${enabled("motherWrath")?metric("蛇母之怒 A 团", `${wrath.raidWideFailureCount || 0} 次`):""}${enabled("coiledPreyDeaths")?metric("死于盘绕猎物", `${coiled.deathCount || 0} 人次`):""}</section>${enabled("p25Eggs")?renderP25Eggs(data.p25Eggs):""}${bitePanel}${coiledPanel}<section class="panel" data-critical="malice"><h2>${spell(malice.spellID || 1290779,"恶意")}打断</h2>${table(["时间","来源","结果"], (malice.casts || []).map(row => [esc(row.time),esc(row.source),row.prevented?badge("已阻止","good"):badge("施法成功","bad")]))}</section><section class="panel" data-critical="nonTankMelee"><h2>非坦克玩家受到近战攻击</h2>${table(["玩家","次数","总伤害","来源"], (melee.players || []).map(row => [player(row),row.hitCount,num(row.totalDamage),(row.sources || []).map(item => `${esc(item.source)} ×${item.count}`).join("、")]))}</section><section class="panel" data-critical="motherWrath"><h2>${spell(1298367,"蛇母之怒")}无人承接 / 全团伤害</h2><p class="muted">正常情况是当前坦克在圈内连续承伤；只有同一轮至少 3 名玩家受到蛇母之怒伤害时才判定为 A 团。承接目标优先取本轮施法目标，缺失时回溯施法前 8 秒内 Boss 最后一次近战目标。</p>${table(["时间","当轮承接目标","目标证据","全团伤害","受影响玩家"], (wrath.failures || []).map(row => [esc(row.time),player(row.receiver),esc(row.receiverEvidence),`${badge(`命中 ${row.affectedCount || 0} 人`,"bad")}，${num(row.totalDamage)} 伤害`,players(row.affectedPlayers)]))}</section>${focusPanel}`;
    const template=document.createElement("template");template.innerHTML=html;
    template.content.querySelectorAll('[data-critical="serpentBites"]').forEach(node=>node.remove());
    template.content.querySelectorAll("[data-critical]").forEach(node=>{if(!enabled(node.dataset.critical))node.remove()});
    return template.innerHTML;
  }

  function renderContent() {
    const renderers = { survival: renderSurvival, replay: ()=>'<div id="ulatekReplay"></div>', waves: renderWaves, heart: renderHeart, fangs: renderFangs, critical: renderCritical };
    $("content").innerHTML = (renderers[state.tab] || (() => '<div class="empty">该页暂无数据。</div>'))();
    if (state.tab === 'critical') $("content").insertAdjacentHTML('beforeend', renderPerBiteAndWretch());
    const exemption=boss().nightlyExemption;
    if(exemption?.active)$("content").insertAdjacentHTML("afterbegin",`<section class="panel"><strong>整晚统计豁免：${esc(exemption.time)} 起已有8人死亡</strong><p>${esc(exemption.reason)}</p></section>`);
    document.querySelectorAll("[data-heart-view]").forEach(button => button.onclick = () => {
      state.heartView = button.dataset.heartView;
      renderContent();
    });
    refreshTooltips();
    if(state.tab==='replay')window.UlatekReplay.mount($('ulatekReplay'),boss(),current()?.durationMs);
  }

  function render() { renderStats(); renderTabs(); renderContent(); }
  function load(payload) {
    state.payload = payload;
    state.pulls = [...(payload.data?.page1_wipeAnalysis || [])].sort((a,b) => String(b.startTimeIso || `${b.date || ""}${b.fightID || ""}`).localeCompare(String(a.startTimeIso || `${a.date || ""}${a.fightID || ""}`)));
    const requestedFight = Number(new URLSearchParams(location.search).get("fight"));
    const index = state.pulls.findIndex(row => Number(row.fightID) === requestedFight);
    state.pull = index >= 0 ? index : 0;
    state.tab = new URLSearchParams(location.search).get('tab') || (payload.meta?.tabDefinitions || [])[0]?.key || "survival";
    $("pullSelect").innerHTML = state.pulls.map((row,index) => `<option value="${index}">Fight ${row.fightID}，${esc(row.date || "")} ${esc(row.startClock || "")}，${esc(row.difficultyName || "未知")}，${esc(row.fightPhase || "阶段未记录")}，${row.isKill ? "KILL" : `${Number(row.bossPercentage || 0).toFixed(2)}%`}，${esc(row.duration || "")}</option>`).join("");
    $("pullSelect").value = String(state.pull);
    $("error").textContent = state.pulls.length ? "" : "分析结果中没有乌拉特克战斗。";
    render();
  }

  $("pullSelect").onchange = event => { state.pull = Number(event.target.value); state.tab = (state.payload?.meta?.tabDefinitions || [])[0]?.key || "survival"; render(); };
  $("fileInput").onchange = async event => { try { load(await window.MythicReportRuntime.readLocalFile(event.target.files[0])); } catch (error) { $("error").textContent = `无法载入：${error.message}`; } };
  const sourcePath = new URLSearchParams(location.search).get("json") || "";
  if (sourcePath) $("overviewLink").href = `/frontend/report/overview.html?json=${encodeURIComponent(sourcePath)}`;
  if (sourcePath) window.MythicReportRuntime.loadPayload(sourcePath).then(load).catch(error => $("error").textContent = error.message);
  else $("error").textContent = "请从全场概览进入，或导入分析 JSON。";
})();
