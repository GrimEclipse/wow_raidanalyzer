/* Twin Fangs mechanic views; adjudication lives in the Boss module. */
function twinEmpty(section) {
  return `<div class="empty">${esc(section?.reason || '本次未分析该项目，或报告生成于旧版本。')}</div>`;
}
function twinDamage(rows) {
  return table(['时间','来源','技能 / 说明','伤害','吸收','过量'], (rows || []).map(e => [esc(e.time),esc(e.source),spellLink(e.spellID,e.spell)+(e.mechanicNote?`<br><small>${esc(e.mechanicNote)}</small>`:''),e.amount,e.absorbed,e.overkill]));
}
function twinImmunity(evidence) {
  const e = evidence || {};
  const active = (e.auras || []).map(a => spellLink(a.spellID,a.spell)).join('、');
  const ended = (e.recentlyEnded || []).map(a => `${spellLink(a.spellID,a.spell)} 于本段前 ${esc(a.secondsBefore)} 秒结束`).join('、');
  return active || (e.immuneHit ? 'WCL immune 命中' : ended || '未覆盖免疫');
}
function twinVenomRounds(rounds) {
  if (!rounds?.length) return '';
  return `<section class="panel twin-venom-rounds"><h2>永恒毒液，每轮吃球与叠层</h2>
    <p class="muted">沿用坦克腐蚀洪流后的吃球轮次，按吃球数量从少到多排列，包含全团零吃球玩家。条形依次显示吃球层数、异常技能命中次数、其他叠层；均统计本轮新增。零吃球仅为记录，不自动判错。</p>
    <div class="twin-venom-legend"><span class="twin-orb">吃球（层）</span><span class="twin-abnormal">异常命中（次）</span><span class="twin-other">其他 / 正常（层）</span></div>
    ${rounds.map(round=>{
      const rows=round.players||[];
      const max=Math.max(1,...rows.map(p=>p.orbStacks+p.abnormalHitCount+p.otherStacks));
      const segment=(value,kind,label)=>value?`<span class="twin-venom-segment twin-${kind}" style="width:${value/max*100}%" title="${esc(label)}">${value}</span>`:'';
      return `<details class="twin-venom-round"><summary>第 ${round.index} 轮，${esc(round.time)}–${esc(round.endTime)}，${round.hitCount} 次吃球，${round.zeroPickupCount} 人未吃球</summary>
        <div class="twin-venom-chart" role="list" aria-label="第 ${round.index} 轮全团吃球与叠层">
        ${rows.map(p=>{
          const label=`${p.player}：吃球 ${p.orbCount} 次，增加 ${p.orbStacks} 层；异常命中 ${p.abnormalHitCount} 次，增加 ${p.abnormalStacks} 层；其他 ${p.otherStacks} 层；共新增 ${p.totalGains} 层`;
          return `<div class="twin-venom-row ${p.orbCount===0?'twin-zero-pickup':''}" role="listitem">
            <div class="twin-venom-player">${player(p)}<small>${!p.aliveAtStart?'轮初已死亡':!p.aliveAtEnd?'本轮死亡':p.orbCount===0?'未吃球':`吃球 ${p.orbCount} 次`}</small></div>
            <div class="twin-venom-track" role="img" aria-label="${esc(label)}" title="${esc(label)}">${segment(p.orbStacks,'orb',`吃球增加 ${p.orbStacks} 层`)}${segment(p.abnormalHitCount,'abnormal',`异常命中 ${p.abnormalHitCount} 次，增加 ${p.abnormalStacks} 层`)}${segment(p.otherStacks,'other',`其他 ${p.otherStacks} 层${p.unknownStacks?`，其中 ${p.unknownStacks} 层来源未确认`:''}`)}${p.orbStacks+p.abnormalHitCount+p.otherStacks===0?'<span class="muted twin-venom-zero">0</span>':''}</div>
            <div class="twin-venom-total">新增 <b>${p.totalGains}</b> 层${p.unknownStacks?`<small>来源未确认 ${p.unknownStacks} 层</small>`:''}${p.abnormalHitCount?`<small>异常贡献 ${p.abnormalStacks} 层</small>`:''}${p.orbCount>0&&!p.orbStacks?'<small>吃球叠层未匹配</small>':''}</div>
          </div>`;
        }).join('')}</div></details>`;
    }).join('')}</section>`;
}
function twinImmunityUsage(section) {
  const usage=section.immunityUsage;
  if(section.strategy!=='immunity'||!usage)return '';
  const rows=usage.events||[];
  const renderRows=items=>table(['使用时间','施法者 → 目标','技能 / 结束时间','时机判定','后续盛宴 / 补位记录'],items.map(e=>[
    esc(e.time),`${player(e.caster)} → ${player(e.target)}`,
    `${spellLink(e.spellID,e.spell)}<br><small>${e.endTime?`结束于 ${esc(e.endTime)}`:'未见结束记录'}</small>`,
    `${e.abnormal?'<span class="badge warn">待复核</span> ':''}${esc(e.status)}${e.coverage.length?`<br><small>${e.coverage.map(c=>`覆盖第 ${c.round} 轮第 ${c.strikeIndices.join('、')} 段`).join('；')}</small>`:''}`,
    `${e.nextRound?`第 ${e.nextRound} 轮${e.assigned?'（已安排）':''}，${e.secondsBefore>=0?`提前 ${e.secondsBefore} 秒`:`首段后 ${Math.abs(e.secondsBefore)} 秒`}`:'无后续盛宴'}${e.replacements.map(r=>`<br><small>第 ${r.strikeIndex} 段名单外免疫参与：${players(r.players)}</small>`).join('')}`
  ]));
  return `<section class="panel"><h2>异常时机使用保护 / 无敌 / 冰箱 / 龟壳，${usage.abnormalCount} 次待复核</h2><p class="muted">${esc(usage.evidenceNote)}</p>
    ${rows.some(e=>e.abnormal)?renderRows(rows.filter(e=>e.abnormal)):'<div class="empty">未见异常时机使用记录。</div>'}
    <details><summary>全部免疫使用记录（${rows.length} 次）</summary>${renderRows(rows)}</details></section>`;
}
function twinBroodMap(arena, rows) {
  const points = [...arena.left, ...arena.right];
  const minX = Math.min(...points.map(p=>p[0]))-650, maxX = Math.max(...points.map(p=>p[0]))+650;
  const minY = Math.min(...points.map(p=>p[1]))-650, maxY = Math.max(...points.map(p=>p[1]))+650;
  const x = value => 30+(value-minX)/(maxX-minX)*480;
  const y = value => 30+(maxY-value)/(maxY-minY)*300;
  const dots = ['left','right'].map(side => arena[side].map((point,i) => {
    const events = rows.filter(r=>r.position?.arena===arena.key && r.position.side===side && r.position.slot===i+1);
    const color = events.some(r=>r.successfulCasts) ? '#fb7185' : events.some(r=>r.interrupts.length) ? '#34d399' : '#93806a';
    const label = `${side==='left'?'左':'右'}${i+1}`;
    return `<g><title>${esc(label)}，${point[0]}, ${point[1]}，${events.length} 个蛇头</title><circle cx="${x(point[0])}" cy="${y(point[1])}" r="10" fill="${color}"/><text x="${x(point[0])+14}" y="${y(point[1])+5}" fill="white" font-size="13">${esc(label)}</text></g>`;
  }).join('')).join('');
  const bosses = ['left','right'].map(side=>{const p=arena.bosses[side];return `<text x="${x(p[0])}" y="${y(p[1])-18}" text-anchor="middle" fill="#fbbf24" font-size="12">${side==='left'?'左侧Boss':'右侧Boss'}</text>`;}).join('');
  return `<figure style="margin:0;max-width:580px"><figcaption>${esc(arena.label)}，红色漏断 / 绿色已打断 / 灰色未观测</figcaption><svg role="img" aria-label="${esc(arena.label)}蛇头固定点位" viewBox="0 0 560 380" style="width:100%;background:#1c160f;border-radius:12px">${dots}${bosses}</svg></figure>`;
}
function renderTwin(tab) {
  const data = boss();
  if (tab === 'venom') return twinVenomRounds(data.eternalVenom?.rounds) + renderTwinLegacy(tab);
  if (tab === 'feast') {
    const section = data.feast;
    if (!section?.enabled) return twinEmpty(section);
    return twinImmunityUsage(section) + `<section class="panel"><h2>贪婪盛宴，${section.strategy==='immunity'?'免疫分摊':'非免疫分摊'}</h2><p class="muted">${esc(section.evidenceNote)}</p>
      ${(section.rounds||[]).map(round=>`<article class="card"><h3>第 ${round.index} 轮，${esc(round.time)} ${round.incomplete?'<span class="badge warn">三段记录不完整</span>':''}</h3>
      ${section.strategy==='immunity'?`<p>免疫安排：${players(round.assigned)}</p>${(round.protectionWarnings||[]).map(w=>`<p class="muted">${esc(w)}</p>`).join('')}${!round.assignmentValid?`<p class="muted">${esc(round.configurationNote)} ${esc((round.unresolvedNames||[]).join('、'))}</p>`:''}`:''}
      ${(round.strikes||[]).map(strike=>`<details ${strike.underfilled?'open':''}><summary>第 ${strike.index} 段，${esc(strike.time)}，${strike.participantCount} 人参与 / 至少 ${strike.minimum} 人 ${strike.underfilled?'，人数不足':''}</summary>
      ${table(['玩家','命中结果','伤害','免疫证据'],(strike.displayParticipants||strike.participants).map(p=>[player(p),esc(p.result),p.damage,twinImmunity(p.immunity)]))}
      ${strike.secondaryRaidDamage?.length?`<p class="muted">本段另有 ${strike.secondaryRaidDamage.length} 条延迟全团溅射记录，不计入分摊人数。</p>`:''}
      ${strike.assignmentChecks?.length?table(['安排玩家','判定','免疫覆盖','近期免疫施法'],strike.assignmentChecks.map(p=>[player(p),esc(p.status),twinImmunity(p.immunity),(p.recentCasts||[]).map(c=>`${esc(c.time)} ${spellLink(c.spellID)}（${c.secondsBefore}s 前）`).join('<br>')||'未见记录'])):''}
      ${strike.assignmentChecks?.length?'<p class="muted">记录可证明提前结束或未覆盖，无法证明具体按键操作；近期施法用于核对冷却与重置。</p>':''}</details>`).join('')}
      ${round.failures?.length?`<h4>本轮失误（每人一次）</h4>${table(['责任玩家','伤害段','原因'],round.failures.map(p=>[player(p),esc([...new Set(p.strikeIndices)].join('、')),esc(p.reasons.join('；'))]))}`:''}</article>`).join('')||'<div class="empty">没有盛宴结算。</div>'}</section>`;
  }
  if (tab === 'brood') {
    const section=data.brood;if(!section?.enabled)return twinEmpty(section);
    if(section.collapseExemption)return `<section class="panel"><h2>蛇头打断，崩溃阶段豁免</h2><p>${esc(section.collapseExemption.time)}：已有 ${section.collapseExemption.deadCount} 人死亡且未战复，本场漏断不计归责。</p></section>`;
    const rounds=[...new Set((section.events||[]).map(r=>r.round))];
    return `<section class="panel"><h2>蛇头打断，${section.successfulCastCount} 次首漏断</h2><p class="muted">${esc(section.positionNote)} 未定位 ${section.unresolvedCount} 个。</p>
      ${rounds.map(no=>{const rows=section.events.filter(r=>r.round===no);const arenas=(section.arenas||[]).filter(a=>rows.some(r=>r.position?.arena===a.key));return `<article class="card"><h3>召唤第 ${no||'未知'} 轮</h3>${arenas.map(a=>twinBroodMap(a,rows)).join('')}
      ${table(['首次漏断时间','点位','组别 / 序号','主断','补断','实际打断','结果 / 证据'],rows.map(r=>[esc(r.time),esc(r.position?`${r.position.arenaLabel} ${r.position.label}`:'坐标未确认'),esc(r.groupLabel||'')+' '+(r.groupOrder||'—'),players(r.assigned),players(r.backup),(r.interrupts||[]).map(e=>`${esc(e.time)} ${player(e.player)} ${spellLink(e.spellID)}`).join('<br>')||'—',`${esc(r.leakLabel||r.status)}${r.successfulCasts?` ×${r.successfulCasts}`:''}<br><small>${esc(r.assignmentNote)}</small>${r.tankEvidence?`<br><small>${esc(r.tankEvidence.reason)}，${Math.round((r.tankEvidence.ageMs||0)/100)/10}s 前</small>`:''}`]))}</article>`;}).join('')||'<div class="empty">本场未见脏腑爆裂成功施法。</div>'}</section>`;
  }
  if (tab === 'stone') {
    const section=data.stone;if(!section?.enabled)return twinEmpty(section);
    const cutoffNote=section.tankDeathCutoffMs!=null?`本场首次倒坦在 ${(section.tankDeathCutoffMs/1000).toFixed(1)} 秒，之后不再统计。`:'本场未观测到坦克死亡。';
    return `<section class="panel"><h2>裂石击，${section.raidDamageCount} 次全团伤害</h2><p>${esc(cutoffNote)}</p><p class="muted">优先使用实际接圈目标，其次参考同组三连击目标或读条时仇恨，并展示依据。一次爆发命中多人仍只计一次。</p>${table(['时间','接圈玩家 / 依据','结果','总伤害','受击玩家'],(section.events||[]).map(r=>[esc(r.time),`${r.tank?player(r.tank):'未确认'}<br><small>${esc(r.evidence)}</small>`,r.raidDamage?'<span class="badge bad">产生全团伤害</span>':'未见全团爆发',r.totalDamage,players(r.victims)]))}</section>`;
  }
  if (tab === 'earlyDeaths' || tab === 'venomDeaths') {
    const section=data[tab];if(!section?.enabled)return twinEmpty(section);
    const isEarly=tab==='earlyDeaths';
    return `<section class="panel"><h2>${isEarly?'提前死亡及全部死亡明细':'永恒毒液，带毒死亡与后续爆球'}</h2><p class="muted">${esc(section.evidenceNote)}</p>
      ${isEarly?`<p>间隔阈值 ${section.gapSeconds} 秒，提前死亡 ${section.earlyDeaths?.length||0} 人次</p>`:`<p>带毒死亡 ${section.deaths?.length||0} 人次，按携带层数预期额外球 ${section.expectedGlobuleCount} 个</p>`}
      ${(section.deaths||[]).map(r=>`<details ${isEarly&&r.early?'open':''}><summary>${esc(r.time)}，${player(r)}，${spellLink(r.killingSpellID,r.killingSpell)} ${r.mechanicNote?`（${esc(r.mechanicNote)}）`:""}，带毒 ${r.venomStacks} 层 ${r.early?'，提前死亡':''}</summary>${r.gapToFollowingDeathsSeconds?`<p>距后续死亡 / 战斗结束 ${r.gapToFollowingDeathsSeconds} 秒</p>`:''}${twinDamage(r.precedingDamage)}</details>`).join('')||'<div class="empty">没有对应死亡。</div>'}
      ${!isEarly?`<h3>实测球爆炸</h3>${table(['时间','总伤害','受击玩家','此前15秒带毒死亡'],(section.explosions||[]).map(r=>[esc(r.time),r.totalDamage,players(r.victims),(r.nearbyVenomDeaths||[]).map(p=>`${player(p)} ${esc(p.time)}（${p.stacks}层）`).join('、')||'未见记录']))}<p class="muted">时间关联不等于球来源的唯一因果关系。</p>`:''}</section>`;
  }
  if (tab==='globules' && data.isMythic) {
    return twinVenomRounds(data.globules?.venomRounds) + `<section class="panel"><h2>史诗腐蚀洪流，坦克点名与绿球</h2><p class="muted">区分坦克洪流轮次、球周围壁垒实体和实际吃球。死亡额外球见“带毒死亡”。史诗不使用每人必须吃一个的英雄归责。</p>
      ${table(['轮次','时间','洪流点名','观测壁垒实体'],(data.tankGlobules?.rounds||[]).map(r=>[r.index,esc(r.time),player(r.target),r.bulwarks.length]))}
      ${(data.globules?.rounds||[]).map(r=>`<article class="card"><h3>#${r.index}，${esc(r.time)}，${r.hitCount} 次吃球命中</h3><p>吃球玩家：${(r.eaten||[]).map(p=>`${player(p)} ×${p.count}`).join('、')||'—'}</p><p>${r.exploded?`观测球爆炸：${esc(r.explosionTime)}`:'未见球爆炸'}</p></article>`).join('')}</section>`;
  }
  if (tab==='globules') return twinVenomRounds(data.globules?.venomRounds) + renderTwinLegacy(tab);
  return renderTwinLegacy(tab);
}
function renderTwinLegacy(tab){const data=boss();if(tab==='venom'){const venom=data.eternalVenom||{};const pl=venom.players||[];const abn=venom.abnormalGains||[];if(!state.venomPlayer||!pl.some(p=>p.player===state.venomPlayer))state.venomPlayer=pl[0]?.player||'';const sel=pl.find(p=>p.player===state.venomPlayer)||pl[0]||null;const catBadge=c=>({normal:'<span class="badge">正常叠层</span>',abnormal:'<span class="badge bad">异常叠层</span>',feast:'<span class="badge warn">贪婪盛宴消耗</span>',remove:'<span class="badge">其他移除</span>',clear:'<span class="badge">完全移除</span>',death:'<span class="badge bad">死亡清层</span>'}[c]||esc(c));const options=pl.map(p=>`<option value="${esc(p.player)}"${p.player===state.venomPlayer?' selected':''}>${esc(p.player)}，峰值 ${p.peakStack} 层</option>`).join('');const selRows=sel?sel.events.map(ev=>`<tr class="${ev.category==='abnormal'?'abnormal-row':''}"><td>${esc(ev.time)}</td><td>${ev.delta>0?`+${ev.delta}`:ev.delta}</td><td>${ev.fromStack}→${ev.toStack}</td><td>${catBadge(ev.category)}</td><td>${spellLink(ev.sourceID,ev.source)}</td></tr>`).join(''):'';const html=`<section class="panel abnormal-panel" data-analysis-option="venomReviewEnabled"><h2>异常叠层记录</h2><p class="muted">腐蚀洪流绿圈直击 / 腐蚀液滴爆裂 / 搅动深渊 / 邪恶洪流等异常来源直接叠加的层数；正常吃球与 Boss 直接点名叠层不在此列。</p>${table(["时间","玩家","变化","叠至","来源"],abn.map(row=>[esc(row.time),player(row),`+${row.delta}`,row.toStack,spellLink(row.sourceID,row.source)]))}</section><section class="panel" data-analysis-option="venomReviewEnabled"><h2>永恒毒液叠层明细</h2><div class="venom-picker">查看玩家<select id="venomPlayerSelect">${options}</select></div>${sel?`<h3>${player(sel)}，峰值 ${sel.peakStack} 层，累计叠 ${sel.gainCount}，累计消 ${sel.removedCount}</h3><table><thead><tr><th>时间</th><th>变化</th><th>层数</th><th>归类</th><th>来源 / 原因</th></tr></thead><tbody>${selRows}</tbody></table>`:'<div class="empty">没有永恒毒液记录。</div>'}</section><section class="panel" data-analysis-option="feastReviewEnabled"><h2>贪婪盛宴消层检查</h2>${table(["轮次","时间","应进圈","已消层","未正常消层"],(venom.feastChecks||[]).map(row=>[`#${row.index}`,esc(row.time),players(row.present),players(row.consumed),players(row.missing)]))}</section>`;setTimeout(()=>{const select=document.getElementById("venomPlayerSelect");if(select)select.onchange=event=>{state.venomPlayer=event.target.value;renderContent()}},0);return html};if(tab==='globules')return`<section class="panel"><h2>腐蚀浪潮，每轮吃球</h2><p class="muted">每轮球数与吃球来自 WCL 伤害记录，团队规模为应吃份额：正常每人 1 个，超过 1 个即异常叠层，0 个即没吃。</p><div class="cards">${(data.globules?.rounds||[]).map(row=>`<article class="card"><h3>#${row.index}，${esc(row.time)}，共 <strong>${row.ballCount??row.hitCount}</strong> 球，团队 ${row.teamSize??'—'}（在场 ${row.aliveCount??'—'}）${row.exploded?`，<span class="badge bad">${esc(row.explosionTime)} 爆炸</span>`:''}</h3>${(row.abnormal||[]).length?`<p><span class="badge bad">异常叠层</span> ${row.abnormal.map(item=>`<b>${player(item)} ×${item.count}</b>`).join('、')}</p>`:''}<p><span class="badge good">吃了</span> ${row.eaten?.length?row.eaten.map(item=>`${player(item)}${item.count>1?` ×${item.count}`:''}`).join('、'):'—'}</p><p><span class="badge warn">没吃</span> ${(row.missed||[]).length?players(row.missed):'—'}</p>${row.exploded&&(row.nonParticipants||[]).length?`<p class="muted">爆炸时未参与：${players(row.nonParticipants)}</p>`:''}</article>`).join('')||'<div class="empty">没有腐蚀浪潮轮次。</div>'}</div></section>`;if(tab==='mythic')return`<section class="panel"><h2>史诗难度占位</h2><div class="empty">${esc(data.mythicPlaceholder||'该部分暂时没有可用的信息。')}</div></section>`}
